"""
Data Subservice — 独立数据源 HTTP 服务（物理解耦版）

作为叶子数据源节点运行，仅依赖 data_subservice._internal（自包含），
不再 import 任何 backend 包模块。对外暴露统一 /api/v1/data 端点，
由主服务经 DataSourceRouter 通过 HMAC 签名调用。
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from data_subservice._internal.circuit_breaker import circuit_breaker
from data_subservice._internal.logger import logger
from data_subservice._internal.metrics import registry as _metrics_registry
from data_subservice._internal.redis_client import redis_client
from data_subservice._internal.service_registry import ServiceRegistry
from data_subservice.nodeinfo import get_node_info
from data_subservice.yfinance_worker import handle_yfinance

# 重型/本地依赖型 worker（akshare/tushare/futu 等）采用延迟导入，避免在仅声明
# yfinance 能力的叶子节点（主服务 backend 测试环境不安装 akshare/tushare/futu）
# 上因 import 失败而无法启动。仅当对应 source 被请求时才 import，缺失时返回 503。
_WORKER_IMPORTS = {
    "akshare": "data_subservice.akshare_worker",
    "tushare": "data_subservice.tushare_worker",
    "futu": "data_subservice.futu_worker",
    "finnhub": "data_subservice.finnhub_worker",
    "fmp": "data_subservice.fmp_worker",
    "fred": "data_subservice.fred_worker",
    "dbnomics": "data_subservice.dbnomics_worker",
    "rbi": "data_subservice.rbi_worker",
    "tavily": "data_subservice.search_worker",
    "bocha": "data_subservice.search_worker",
    "jina": "data_subservice.search_worker",
}

load_dotenv()

# ── 配置 ──
HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "change-me-in-prod")
SERVICE_PORT = int(os.getenv("DATASOURCE_PORT", "8001"))
ENABLE_REDIS_HEARTBEAT = os.getenv("ENABLE_REDIS_HEARTBEAT", "false").lower() == "true"
# 心跳周期须远低于注册表 TTL（默认 30s），否则节点会在 TTL 期满后被判 dead。
# 取 TTL 的 1/3 作为刷新间隔，留足网络抖动余量。
_HEARTBEAT_TTL = int(os.getenv("NODE_HEARTBEAT_TTL", "30"))
_HEARTBEAT_INTERVAL = max(5, _HEARTBEAT_TTL // 3)

# 后台心跳任务句柄，便于 shutdown 时清理
_heartbeat_task: Optional[asyncio.Task] = None

app = FastAPI(title="Quant Agent Data Subservice", version="1.0.0")


# ── HMAC 校验 ──
async def verify_hmac(
    request: Request,
    x_timestamp: Optional[str] = Header(None),
    x_signature: Optional[str] = Header(None),
) -> None:
    if not x_timestamp or not x_signature:
        raise HTTPException(status_code=403, detail="缺少 HMAC 请求头")

    if abs(time.time() - int(x_timestamp)) > 300:
        raise HTTPException(status_code=403, detail="请求时间戳过期")

    body = (await request.body()).decode("utf-8")
    message = f"{x_timestamp}:{body}".encode("utf-8")
    expected = hmac.new(HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(status_code=403, detail="HMAC 签名校验失败")


# ── 路由 ──
@app.get("/health")
async def health():
    # 携带 futu 真实连接状态，避免 /health 成为无意义的死值（node-s1 实战复盘 2026-08-11）
    futu_state = _futu_status_snapshot()
    return JSONResponse(
        {
            "status": "healthy",
            "service": "data-subservice",
            "futu": futu_state,
        }
    )


def _futu_status_snapshot() -> dict:
    """读取常驻进程内 futu_service 单例的真实连接状态。

    注意：必须读取模块级单例（与 startup_event 中 connect 的是同一对象），
    严禁在外部另起进程 import 后读取——那是全新实例，quote_ctx 恒为 None，
    会误判为 DISCONNECTED（node-s1 实战踩坑 2026-08-11）。

    FutuService 自身的 status/quote_ctx 仅为兼容旧接口，connect() 时从
    conn_mgr 同步；真实连接状态以内部 ConnectionManager 为准。
    """
    try:
        from data_subservice.futu_src import futu_service

        conn_mgr = futu_service.conn_mgr
        # DIST-23(2026-08-11 实战): 此前 /futu/status 仅暴露行情连接状态, 掩盖了
        # 交易连接(TrdCtx)未解锁这一隐蔽故障 —— 行情 CONNECTED 但 ACCOUNT_INFO 因
        # OpenD 交易未解锁返回 error, 进而触发主服务 futu_master 全局熔断误杀行情。
        # 现补充交易连接/解锁状态, 让监控一眼看清"行情通、交易未解锁"的真相。
        # 注意: 交易解锁错误记录在 TradeHandler 单例上 (get_account_info 失败时置
        # self.last_trade_error), 而非 ConnectionManager, 故从此处取。
        trade_ctxs = getattr(conn_mgr, "trade_ctxs", None)
        trade_connected = bool(trade_ctxs)
        last_trade_error = getattr(futu_service.trade_handler, "last_trade_error", "") or ""
        return {
            "status": conn_mgr.status,
            "connected": conn_mgr.quote_ctx is not None,
            "target": conn_mgr.target,
            "error_msg": conn_mgr.error_msg,
            # 新增交易通道状态 (与行情通道分离观测)
            "trade_connected": trade_connected,
            "trade_unlocked": trade_connected and not last_trade_error,
            "trade_error": last_trade_error or None,
        }
    except Exception as e:  # 未声明 futu 能力或模块不可用时
        return {
            "status": "unavailable",
            "connected": False,
            "target": None,
            "error_msg": str(e),
            "trade_connected": False,
            "trade_unlocked": False,
            "trade_error": None,
        }


@app.get("/futu/status")
async def futu_status():
    """暴露常驻进程内 Futu OpenD 连接真实状态，供运维直查（不依赖手动进程误读）。"""
    return JSONResponse(_futu_status_snapshot())


def _declared_capabilities() -> set:
    """读取本节点声明的数据源能力 (DS_CAPABILITIES)，未声明则不响应对应请求。

    Fallback: 兼容旧 NODE_CAPABILITIES；再 fallback 到全量（保持向后兼容）。
    """
    # 默认能力集（未显式声明 DS_CAPABILITIES 时）。
    # ⚠️ 注意：部署时必须通过 DS_CAPABILITIES 显式声明本节点能力，否则未声明的能力全部 503。
    # 全量能力集参考：yfinance,akshare,tushare,fmp,futu,finnhub,fred,dbnomics,rbi,tavily,bocha,jina
    raw = os.getenv("DS_CAPABILITIES") or os.getenv("NODE_CAPABILITIES")
    if not raw:
        return {"yfinance", "akshare", "tushare", "fmp", "futu"}
    return {c.strip().lower() for c in raw.split(",") if c.strip()}


@app.post("/api/v1/data", dependencies=[Depends(verify_hmac)])
async def fetch_data(request: Request):
    """统一数据源获取端点。仅响应本节点 DS_CAPABILITIES 声明的能力。"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON 请求体")

    source = payload.get("source", "").lower()
    action = payload.get("action", "")
    params = payload.get("params", {})

    declared = _declared_capabilities()

    # 普通数据源能力：按 DS_CAPABILITIES 门控
    if source not in declared:
        raise HTTPException(
            status_code=503,
            detail=f"数据源能力未启用 (source={source} 不在 DS_CAPABILITIES={sorted(declared)})",
        )

    if source == "yfinance":
        result = await handle_yfinance(action, params)
    elif source in _WORKER_IMPORTS:
        # 延迟导入对应 worker（重型/本地依赖型 SDK 仅在请求时 import）
        try:
            mod = __import__(_WORKER_IMPORTS[source], fromlist=["handle_" + source])
        except ModuleNotFoundError as e:
            raise HTTPException(
                status_code=503,
                detail=f"数据源依赖缺失 (source={source}, 未安装对应 SDK: {e.name})",
            )
        handler = getattr(mod, "handle_" + source, None)
        if handler is None:
            raise HTTPException(status_code=503, detail=f"数据源处理程序未实现: {source}")
        if source in ("tavily", "bocha", "jina"):
            result = await handler(source, action, params)
        else:
            result = await handler(action, params)
    else:
        raise HTTPException(status_code=400, detail=f"未知数据源: {source}")

    return JSONResponse({"code": 0, "data": result})


@app.get("/metrics/circuit")
async def circuit_metrics():
    return JSONResponse(circuit_breaker.status_snapshot())


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 抓取端点（FMP 等数据源指标，独立 registry）。"""
    return JSONResponse(
        content=generate_latest(_metrics_registry).decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── 启动事件：可选向主 Redis 注册节点心跳 + Futu 长连接 ──
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Data Subservice 启动完成 (物理解耦模式，无 backend 依赖)")

    # Futu OpenD 长连接仅在本节点 DS_CAPABILITIES 声明 futu 时拉起（主节点 VPS 宿主）
    if "futu" in _declared_capabilities():
        try:
            from data_subservice.futu_src import futu_service
            from data_subservice.futu_src.push_handler import set_main_loop
            from data_subservice.futu_src.watchdog import FutuWatchdog

            # BE-ARCH-08c①: connect() 经 asyncio.to_thread 在工作线程执行，
            # _register_push_handlers 内 asyncio.get_running_loop() 会抛 RuntimeError。
            # 先把主事件循环引用注入 push_handler，作为子线程回退的双保险，
            # 否则推送桥接 (_main_loop=None) 会静默丢弃所有 OpenD 推送回调。
            set_main_loop(asyncio.get_event_loop())

            # 初始建连（线程池执行，不阻塞事件循环）
            await asyncio.to_thread(futu_service.connect)
            asyncio.create_task(FutuWatchdog(futu_service).start())
            logger.info("🔌 Futu OpenD 长连接已拉起（主节点），看门狗守护进程启动")
        except Exception as e:
            logger.error(f"❌ Futu OpenD 启动失败: {e}")

    if ENABLE_REDIS_HEARTBEAT:
        try:
            node = get_node_info()
            registry = ServiceRegistry(redis_client)
            await registry.register(node)
            logger.info(f"📡 已向主 Redis 注册节点心跳: {node.node_id}")
            # 启动后台周期心跳，避免 TTL 到期后节点被判 dead（07l③ 修复）
            global _heartbeat_task
            _heartbeat_task = asyncio.create_task(_heartbeat_loop(node.node_id, registry))
        except Exception as e:
            logger.warning(f"⚠️ Redis 心跳注册失败（子服务仍可独立运行）: {e}")


async def _heartbeat_loop(node_id: str, registry: ServiceRegistry) -> None:
    """周期性刷新 Redis 心跳，间隔远低于注册表 TTL。"""
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            ok = await registry.heartbeat(node_id)
            if not ok:
                logger.warning(f"⚠️ 节点 {node_id} 心跳刷新失败")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ 心跳循环异常: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass


# ── 远程节点调用（供主服务反向代理或子服务间互调，可选）──
async def fetch_from_node(node_url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict:
    """向其它子节点发起 HMAC 签名请求（子服务间可选协作）。"""
    timestamp = str(int(time.time()))
    body = json.dumps(payload, ensure_ascii=False)
    message = f"{timestamp}:{body}".encode("utf-8")
    signature = hmac.new(HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{node_url}/api/v1/data", content=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
