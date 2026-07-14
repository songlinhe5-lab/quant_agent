"""
Data Subservice — 分布式数据源子服务节点
==========================================

独立 FastAPI 应用，作为数据源节点运行在远程 VPS 上。
启动时自动向 ServiceRegistry 注册，持续发送心跳保活。

环境变量:
  DS_NODE_ID        — 节点唯一标识 (必填)
  DS_NODE_PORT      — 监听端口 (默认 8000)
  DS_REGION         — 节点区域 (默认 us-west)
  DS_WEIGHT         — 路由权重 (默认 10)
  DS_CAPABILITIES   — 逗号分隔的能力列表 (默认 yfinance)
  REDIS_HOST        — Redis 地址 (默认 localhost)
  REDIS_PORT        — Redis 端口 (默认 6379)
  REDIS_PASSWORD    — Redis 密码 (可选)

任务编号: DIST-05
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from backend.core.logger import logger
from backend.core.service_registry import NodeInfo, ServiceRegistry
from data_subservice.routes import router as ds_router
from data_subservice.yfinance_worker import YFinanceWorker

# DIST-22: 可选 Finnhub Worker
try:
    from data_subservice.finnhub_worker import FinnhubWorker
except ImportError:
    FinnhubWorker = None  # type: ignore

# ─────────────────────────────────────────
#  环境变量配置
# ─────────────────────────────────────────
DS_NODE_ID = os.getenv("DS_NODE_ID", "")
DS_NODE_PORT = int(os.getenv("DS_NODE_PORT", "8000"))
DS_REGION = os.getenv("DS_REGION", "us-west")
DS_WEIGHT = int(os.getenv("DS_WEIGHT", "10"))
DS_CAPABILITIES = [c.strip() for c in os.getenv("DS_CAPABILITIES", "yfinance").split(",") if c.strip()]

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

HEARTBEAT_INTERVAL = int(os.getenv("DS_HEARTBEAT_INTERVAL", "10"))
MAX_RETRY_DELAY = int(os.getenv("DS_MAX_RETRY_DELAY", "60"))  # 指数退避最大延迟秒数
INITIAL_RETRY_DELAY = 1  # 初始重试延迟秒数

# ─────────────────────────────────────────
#  全局状态
# ─────────────────────────────────────────
_redis_client: Optional[aioredis.Redis] = None
_registry: Optional[ServiceRegistry] = None
_heartbeat_task: Optional[asyncio.Task] = None
_yf_worker: Optional[YFinanceWorker] = None
_fh_worker = None  # DIST-22: FinnhubWorker
_start_time: float = 0.0


def _build_node_url() -> str:
    """构造节点 URL"""
    return f"http://0.0.0.0:{DS_NODE_PORT}"


def _build_node_info() -> NodeInfo:
    """从环境变量构造 NodeInfo"""
    return NodeInfo(
        node_id=DS_NODE_ID,
        url=_build_node_url(),
        region=DS_REGION,
        weight=DS_WEIGHT,
        capabilities=DS_CAPABILITIES,
    )


# ─────────────────────────────────────────
#  心跳后台任务
# ─────────────────────────────────────────

async def _heartbeat_loop():
    """
    定时向 ServiceRegistry 发送心跳。

    每 HEARTBEAT_INTERVAL 秒发送一次，附带 uptime_seconds 指标。
    心跳失败时采用指数退避重试策略，避免 Redis 故障时疯狂重试。
    """
    global _registry
    retry_delay = INITIAL_RETRY_DELAY
    consecutive_failures = 0

    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if _registry is None:
                continue

            uptime = time.time() - _start_time
            metrics = {"uptime_seconds": uptime}
            ok = await _registry.heartbeat(DS_NODE_ID, metrics=metrics)
            if ok:
                # 心跳成功，重置重试延迟
                if consecutive_failures > 0:
                    logger.info(f"[DataSubservice] 心跳恢复正常: {DS_NODE_ID} (连续失败 {consecutive_failures} 次后)")
                    consecutive_failures = 0
                    retry_delay = INITIAL_RETRY_DELAY
                logger.debug(f"[DataSubservice] 心跳成功: {DS_NODE_ID}, uptime={uptime:.0f}s")
            else:
                consecutive_failures += 1
                logger.warning(
                    f"[DataSubservice] 心跳失败: {DS_NODE_ID} "
                    f"(连续第 {consecutive_failures} 次，下次重试延迟 {retry_delay}s)"
                )
                # 指数退避：额外等待后再尝试
                await asyncio.sleep(min(retry_delay, MAX_RETRY_DELAY))
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"[DataSubservice] 心跳异常: {e} (连续第 {consecutive_failures} 次)")
            await asyncio.sleep(min(retry_delay, MAX_RETRY_DELAY))
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)


# ─────────────────────────────────────────
#  Lifespan: Startup / Shutdown
# ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理：启动注册 + 心跳，关闭注销 + 清理"""
    global _redis_client, _registry, _heartbeat_task, _yf_worker, _start_time

    # ── Startup ──
    if not DS_NODE_ID:
        raise RuntimeError("DS_NODE_ID 环境变量未设置，子服务无法启动")

    logger.info(f"[DataSubservice] 正在启动节点: {DS_NODE_ID} (region={DS_REGION}, capabilities={DS_CAPABILITIES})")

    # 1. 初始化 Redis 连接
    _redis_client = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        protocol=2,
    )
    # 验证连接
    try:
        await _redis_client.ping()
        logger.info("[DataSubservice] Redis 连接成功")
    except Exception as e:
        logger.error(f"[DataSubservice] Redis 连接失败: {e}")
        raise

    # 2. 创建 ServiceRegistry 实例
    _registry = ServiceRegistry(_redis_client)

    # 3. 注册节点（带指数退避重试）
    node = _build_node_info()
    retry_delay = INITIAL_RETRY_DELAY
    max_register_retries = 5
    for attempt in range(1, max_register_retries + 1):
        registered = await _registry.register(node)
        if registered:
            logger.info(f"[DataSubservice] 节点注册成功: {DS_NODE_ID} -> {node.url}")
            break
        if attempt < max_register_retries:
            logger.warning(f"[DataSubservice] 节点注册失败 (第 {attempt}/{max_register_retries} 次)，{retry_delay}s 后重试...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
    else:
        logger.error(f"[DataSubservice] 节点注册失败: {DS_NODE_ID} (重试 {max_register_retries} 次后放弃)")
        raise RuntimeError(f"节点 {DS_NODE_ID} 注册到 ServiceRegistry 失败")

    # 4. 启动心跳后台任务
    _start_time = time.time()
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info(f"[DataSubservice] 心跳任务已启动 (间隔={HEARTBEAT_INTERVAL}s)")

    # 5. 启动 yfinance worker (如果 capabilities 包含 yfinance)
    if "yfinance" in DS_CAPABILITIES:
        try:
            _yf_worker = YFinanceWorker()
            await _yf_worker.start()
            logger.info("[DataSubservice] YFinanceWorker 已启动 (macro_data_daemon 运行中)")
        except Exception as e:
            logger.error(f"[DataSubservice] YFinanceWorker 启动失败: {e}")
            _yf_worker = None

    # 6. DIST-22: 启动 finnhub worker (可选)
    if "finnhub" in DS_CAPABILITIES and FinnhubWorker is not None:
        try:
            global _fh_worker
            _fh_worker = FinnhubWorker(redis_client=_redis_client)
            await _fh_worker.start()
            logger.info("[DataSubservice] FinnhubWorker 已启动 (DIST-22)")
        except Exception as e:
            logger.error(f"[DataSubservice] FinnhubWorker 启动失败: {e}")
            _fh_worker = None

    logger.info(f"[DataSubservice] ✅ 节点就绪，监听端口 {DS_NODE_PORT}")

    yield

    # ── Shutdown ──
    logger.info(f"[DataSubservice] 正在关闭节点: {DS_NODE_ID}")

    # 1. 取消心跳任务
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        try:
            await asyncio.wait_for(_heartbeat_task, timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("[DataSubservice] 心跳任务已停止")

    # 2. 停止 yfinance worker
    if _yf_worker:
        await _yf_worker.stop()
        logger.info("[DataSubservice] YFinanceWorker 已停止")

    # 2b. DIST-22: 停止 finnhub worker
    if _fh_worker:
        await _fh_worker.stop()
        logger.info("[DataSubservice] FinnhubWorker 已停止")

    # 3. 注销节点
    if _registry:
        await _registry.deregister(DS_NODE_ID)
        logger.info(f"[DataSubservice] 节点已注销: {DS_NODE_ID}")

    # 4. 关闭 Redis 连接
    if _redis_client:
        await _redis_client.aclose()
        logger.info("[DataSubservice] Redis 连接已关闭")

    logger.info("[DataSubservice] ✅ 节点已安全关闭")


# ─────────────────────────────────────────
#  FastAPI 应用
# ─────────────────────────────────────────

app = FastAPI(
    title="Quant Agent - Data Subservice",
    description="分布式数据源子服务节点",
    version="0.1.0",
    lifespan=lifespan,
)

# DIST-07: 注册数据接口路由
app.include_router(ds_router)


# ─────────────────────────────────────────
#  端点
# ─────────────────────────────────────────

@app.get("/health")
async def health():
    """
    节点健康检查。

    返回节点 ID、运行时长、基本信息和 yfinance daemon 状态。
    """
    uptime = time.time() - _start_time if _start_time else 0
    result = {
        "status": "healthy",
        "node_id": DS_NODE_ID,
        "region": DS_REGION,
        "capabilities": DS_CAPABILITIES,
        "uptime_seconds": round(uptime, 1),
    }
    if _yf_worker:
        result["yfinance_daemon_running"] = _yf_worker.is_daemon_running
    return result


@app.get("/ds/health")
async def datasource_health():
    """
    数据源健康总览。

    返回本节点所有数据源的健康状态，包含 yfinance 真实健康信息。
    """
    uptime = time.time() - _start_time if _start_time else 0
    sources = {}
    for cap in DS_CAPABILITIES:
        if cap == "yfinance" and _yf_worker:
            yf_health = _yf_worker.get_health()
            sources[cap] = {
                "status": "available" if yf_health.get("status") == "healthy" else "degraded",
                "mode": "local_daemon",
                "detail": yf_health,
            }
        else:
            sources[cap] = {"status": "available", "mode": "internal"}

    return {
        "status": "healthy",
        "node_id": DS_NODE_ID,
        "region": DS_REGION,
        "uptime_seconds": round(uptime, 1),
        "sources": sources,
    }


# DIST-07: /ds/{source}/{action} 代理端点已由 data_subservice/routes.py 中的
# /api/v1/data-source/proxy/yfinance 和 /api/v1/data-source/proxy/batch_quote 替代


# ─────────────────────────────────────────
#  直接运行入口
# ─────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "data_subservice.main:app",
        host="0.0.0.0",
        port=DS_NODE_PORT,
        reload=False,
        log_level="info",
    )
