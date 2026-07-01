"""
==========================================
Slave Collector API - 从节点轻量 API (多 Master)
==========================================
从节点运行的极简 FastAPI 应用:
- GET  /health            本节点健康状态
- POST /collect/{action}  按需数据采集 (供 Master 调用，写入调用方 Master 的 Redis)

多 Master 支持:
  - MASTER_NODES 配置多个 master 节点 (含各自 Redis 连接信息)
  - 心跳同时注册到所有 master 的 Redis
  - 按需查询时，数据写入调用方 master 指定的 Redis
  - 后台 daemon 推送写入所有 master 的 Redis

启动方式:
  uvicorn backend.slave_app:app --host 0.0.0.0 --port 8001
"""

import asyncio
import json
import os
import socket
import sys
import time
import uuid
import warnings
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from dotenv import load_dotenv

warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")
socket.setdefaulttimeout(15.0)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend.core.redis_client import redis_batch_writer, redis_client  # noqa: E402
from backend.workers.collector_registry import (  # noqa: E402
    get_enabled_collectors,
    start_collector_daemons,
)

NODE_UUID = str(uuid.uuid4())
NODE_ID = os.getenv("SLAVE_ID", socket.gethostname())
NODE_HOST = os.getenv("NODE_HOST", socket.gethostname())
NODE_PORT = int(os.getenv("NODE_PORT", "8001"))
ENABLED_COLLECTORS = get_enabled_collectors()
_daemon_tasks: list = []


# ==========================================
# 多 Master Redis 连接管理器
# ==========================================
class MultiRedisManager:
    """管理与多个 Master Redis 实例的连接池"""

    def __init__(self):
        self._clients: Dict[str, aioredis.Redis] = {}  # master_id → Redis
        self._masters: List[Dict[str, Any]] = []

    def parse_masters(self):
        """从 MASTER_NODES 环境变量解析 master 节点列表"""
        raw = os.getenv("MASTER_NODES", "")
        if not raw:
            return
        try:
            self._masters = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [MultiRedis] MASTER_NODES JSON 解析失败: {raw[:80]}")
            return

        for m in self._masters:
            mid = m.get("id", m.get("host", "unknown"))
            try:
                client = aioredis.Redis(
                    host=m["host"],
                    port=int(m.get("port", 6379)),
                    password=m.get("password") or None,
                    decode_responses=True,
                )
                self._clients[mid] = client
                print(f"  [MultiRedis] connected: {mid} → {m['host']}:{m.get('port', 6379)}")
            except Exception as e:
                print(f"  [MultiRedis] failed to create client for {mid}: {e}")

    def get_client(self, master_id: str) -> Optional[aioredis.Redis]:
        """获取指定 master 的 Redis 客户端"""
        return self._clients.get(master_id)

    def get_client_by_host(self, host: str, port: int = 6379) -> Optional[aioredis.Redis]:
        """根据 host:port 查找匹配的客户端"""
        for client_id, m in zip(self._clients.keys(), self._masters):
            if m.get("host") == host and int(m.get("port", 6379)) == port:
                return self._clients[client_id]
        return None

    def get_or_create_client(self, redis_info: Dict[str, Any]) -> Optional[aioredis.Redis]:
        """根据 redis_info 获取已有连接或创建新连接"""
        host = redis_info.get("host", "")
        port = int(redis_info.get("port", 6379))

        # 先查找已有连接
        existing = self.get_client_by_host(host, port)
        if existing:
            return existing

        # 创建新连接 (运行时动态发现的 master)
        try:
            client = aioredis.Redis(
                host=host,
                port=port,
                password=redis_info.get("password") or None,
                decode_responses=True,
            )
            key = f"{host}:{port}"
            self._clients[key] = client
            print(f"  [MultiRedis] dynamic connect: {key}")
            return client
        except Exception as e:
            print(f"  [MultiRedis] dynamic connect failed {host}:{port}: {e}")
            return None

    @property
    def all_clients(self) -> Dict[str, aioredis.Redis]:
        return self._clients

    async def close_all(self):
        """关闭所有连接"""
        for client in self._clients.values():
            try:
                await client.aclose()
            except Exception:
                pass
        self._clients.clear()


# 全局多 Master 管理器
multi_redis = MultiRedisManager()


# ==========================================
# Lifespan: 启动/关闭
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时注册能力 + 启动 daemon，关闭时清理"""
    global _daemon_tasks

    print(f"\n{'=' * 50}")
    print(f"  [Slave] {NODE_ID} starting")
    print(f"  Collectors: {ENABLED_COLLECTORS}")
    print(f"{'=' * 50}\n")

    # 1. 解析多 Master 配置
    multi_redis.parse_masters()
    master_count = len(multi_redis.all_clients)
    print(f"  [MultiRedis] {master_count} master(s) configured")

    # 2. 启动本地 Redis 批量写入 (仅当无 MASTER_NODES 时启用)
    _use_local_redis = master_count == 0
    if _use_local_redis:
        redis_batch_writer.start()
        print("  [LocalRedis] batch_writer started (no MASTER_NODES, fallback mode)")
    else:
        print(f"  [LocalRedis] skipped (daemon data → {master_count} master Redis)")

    # 3. 启动采集器守护进程
    _daemon_tasks = await start_collector_daemons(ENABLED_COLLECTORS)

    # 4. 启动多 Master 心跳注册
    heartbeat_task = asyncio.create_task(_multi_heartbeat_loop())

    # 5. 启动通知
    try:
        from backend.services.notification_service import notification_service

        asyncio.create_task(
            notification_service.send_alert(
                f"[Slave {NODE_ID}] online, collectors={ENABLED_COLLECTORS}, masters={master_count}"
            )
        )
    except Exception:
        pass

    yield  # 运行中

    # 关闭
    heartbeat_task.cancel()
    for t in _daemon_tasks:
        t.cancel()
    await multi_redis.close_all()
    if _use_local_redis:
        await redis_batch_writer.stop()
        await redis_client.aclose()
    print(f"  [Slave {NODE_ID}] shutdown complete")


app = FastAPI(title="Quant Collector Slave", lifespan=lifespan)


# ==========================================
# 多 Master 心跳注册循环
# ==========================================
async def _multi_heartbeat_loop():
    """每 5 秒向所有 Master 的 Redis 注册节点信息，追踪连接状态"""
    _consecutive_master_failures: Dict[str, int] = {}  # master_id → 连续失败次数

    while True:
        node_info = {
            "uuid": NODE_UUID,
            "node_id": NODE_ID,
            "role": "slave",
            "host": NODE_HOST,
            "port": NODE_PORT,
            "collectors": ENABLED_COLLECTORS,
            "started_at": time.time(),
            "status": "healthy",
        }
        node_json = json.dumps(node_info)
        node_key = f"quant:node:{NODE_ID}"

        # 写入每个 master 的 Redis，追踪连接状态
        for master_id, client in multi_redis.all_clients.items():
            try:
                await client.set(node_key, node_json, ex=15)
                # 成功: 重置失败计数
                if _consecutive_master_failures.get(master_id, 0) > 0:
                    print(f"  [Heartbeat] master '{master_id}' reconnected")
                _consecutive_master_failures[master_id] = 0
            except Exception as e:
                _consecutive_master_failures[master_id] = _consecutive_master_failures.get(master_id, 0) + 1
                fail_count = _consecutive_master_failures[master_id]
                if fail_count <= 3 or fail_count % 10 == 0:
                    print(f"  [Heartbeat] master '{master_id}' write failed ({fail_count}x): {e}")

        # 同时写入本地 Redis (仅当 MASTER_NODES 未配置时作为兜底)
        if not multi_redis.all_clients:
            try:
                await redis_client.set(node_key, node_json, ex=15)
            except Exception:
                pass

        await asyncio.sleep(5)


# ==========================================
# 请求模型
# ==========================================
class CollectRequest(BaseModel):
    """
    采集请求模型 - 兼容两种 payload 格式:
    新格式: {"ticker": "AAPL", "params": {"period": "3mo"}, "callback_redis": {...}}
    旧格式: {"ticker": "AAPL", "period": "3mo", "callback_redis": {...}}  (参数平铺在顶层)
    """
    ticker: str | None = None
    params: Dict[str, Any] | None = None
    # Master 回调信息: slave 将结果写入此 Redis
    callback_redis: Dict[str, Any] | None = None

    class Config:
        extra = "allow"  # 允许额外字段 (兼容旧版平铺参数)


# ==========================================
# API 端点
# ==========================================
@app.get("/health")
async def health():
    """从节点健康检查 + 采集器状态 + 多 Master 连接状态"""
    collector_status = {}
    for name in ENABLED_COLLECTORS:
        if name == "futu":
            try:
                from backend.services.futu_service import futu_service

                collector_status[name] = futu_service.status
            except Exception as e:
                collector_status[name] = f"error: {e}"
        elif name == "yfinance":
            collector_status[name] = "active (daemon with distributed lock)"
        elif name == "finnhub":
            collector_status[name] = "active"
        elif name == "akshare":
            collector_status[name] = "active (request-based)"

    # 多 Master 连接状态
    master_status = {}
    for mid, client in multi_redis.all_clients.items():
        try:
            await client.ping()
            master_status[mid] = "connected"
        except Exception as e:
            master_status[mid] = f"error: {e}"

    return {
        "code": 0,
        "data": {
            "node_id": NODE_ID,
            "role": "slave",
            "collectors": ENABLED_COLLECTORS,
            "collector_status": collector_status,
            "masters": master_status,
            "daemon_tasks_alive": sum(1 for t in _daemon_tasks if not t.done()),
            "uptime_seconds": int(time.time() - app.state.start_time) if hasattr(app.state, "start_time") else 0,
        },
    }


@app.post("/collect/{action}")
async def collect(action: str, req: CollectRequest):
    """
    按需数据采集接口 (供 Master ClusterManager 调用)

    Master 在请求中携带 callback_redis 信息，
    Slave 采集完毕后将结果写入该 Master 的 Redis 缓存。

    兼容新旧 payload 格式:
    - 新格式: ticker + params (结构化)
    - 旧格式: ticker + 平铺参数 (params 为空时从 model_extra 提取)
    """
    ticker = req.ticker

    # 兼容旧版平铺参数: 如果 params 为空，从 model_extra 中提取额外字段作为 params
    params = dict(req.params or {})
    if not params and req.model_extra:
        # 旧版格式: 所有非 ticker/callback_redis 的字段都作为 params
        params = {k: v for k, v in req.model_extra.items() if k not in ("ticker", "callback_redis")}

    if not ticker and action not in ("fetch_fund_flow",):
        raise HTTPException(status_code=400, detail="ticker is required")

    try:
        # 1. 执行数据采集
        result = await _dispatch_collect(action, ticker, params)

        # 2. 如果 Master 提供了回调 Redis 信息，将结果写入该 Master 的缓存
        if req.callback_redis:
            await _write_to_master_redis(req.callback_redis, action, ticker, result)

        return {"code": 0, "data": result, "source_node": NODE_ID}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _write_to_master_redis(
    redis_info: Dict[str, Any],
    action: str,
    ticker: str | None,
    data: Any,
):
    """将采集结果写入调用方 Master 的 Redis 缓存"""
    try:
        client = multi_redis.get_or_create_client(redis_info)
        if not client:
            return

        # 构造缓存 key: quant:cache:{action}:{ticker}
        cache_key = f"quant:cache:{action}"
        if ticker:
            cache_key += f":{ticker}"

        # 序列化并写入，TTL=300s (5分钟)
        await client.set(
            cache_key,
            json.dumps({"data": data, "source_node": NODE_ID, "ts": time.time()}),
            ex=300,
        )
    except Exception as e:
        print(f"  [callback_redis] write failed: {e}")


async def _dispatch_collect(action: str, ticker: str | None, params: Dict[str, Any]) -> Any:
    """根据 action 分发到对应的采集服务"""

    # === YFinance ===
    if "yfinance" in ENABLED_COLLECTORS:
        from backend.services.yfinance_service import yf_service

        if action == "fetch_quote":
            return await yf_service.fetch_yf_data(ticker, "quote")
        elif action == "fetch_history":
            period = params.get("period", "3mo")
            interval = params.get("interval", "1d")
            return await yf_service.fetch_yf_data(ticker, "history", period=period, interval=interval)
        elif action == "fetch_info":
            return await yf_service.fetch_yf_data(ticker, "info")

    # === Futu ===
    if "futu" in ENABLED_COLLECTORS:
        from backend.services.futu_service import futu_service

        if action == "fetch_quote":
            return await futu_service.get_quote(ticker)
        elif action == "fetch_history":
            ktype = params.get("ktype", "K_DAY")
            num = params.get("num", 100)
            return await futu_service.get_history(ticker, ktype=ktype, num=num)
        elif action == "fetch_fund_flow":
            return await futu_service.get_fund_flow(ticker)

    # === Finnhub ===
    if "finnhub" in ENABLED_COLLECTORS:
        from backend.services.finnhub_service import finnhub_service

        if action == "fetch_history":
            days_back = params.get("days_back", 90)
            return await finnhub_service.get_stock_history(ticker, days_back=days_back)

    # === AKShare ===
    if "akshare" in ENABLED_COLLECTORS:
        from backend.services.akshare_service import akshare_service

        if action == "fetch_fund_flow":
            return await akshare_service.get_southbound_flow()
        elif action == "fetch_history":
            num = params.get("num", 100)
            return await akshare_service.get_stock_history(ticker, num=num)

    raise ValueError(f"Action '{action}' not supported by any enabled collector. Enabled: {ENABLED_COLLECTORS}")


# ==========================================
# App state
# ==========================================
@app.on_event("startup")
async def _on_startup():
    app.state.start_time = time.time()
