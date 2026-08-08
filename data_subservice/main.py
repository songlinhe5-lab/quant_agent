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
from data_subservice.akshare_worker import handle_akshare
from data_subservice.dbnomics_worker import handle_dbnomics
from data_subservice.finnhub_worker import handle_finnhub
from data_subservice.fmp_worker import handle_fmp
from data_subservice.fred_worker import handle_fred
from data_subservice.futu_worker import handle_futu
from data_subservice.nodeinfo import get_node_info
from data_subservice.rbi_worker import handle_rbi
from data_subservice.search_worker import handle_search
from data_subservice.tushare_worker import handle_tushare
from data_subservice.yfinance_worker import handle_yfinance

load_dotenv()

# ── 配置 ──
HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "change-me-in-prod")
SERVICE_PORT = int(os.getenv("DATASOURCE_PORT", "8001"))
ENABLE_REDIS_HEARTBEAT = os.getenv("ENABLE_REDIS_HEARTBEAT", "false").lower() == "true"

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
    return JSONResponse({"status": "healthy", "service": "data-subservice"})


def _declared_capabilities() -> set:
    """读取本节点声明的数据源能力 (DS_CAPABILITIES)，未声明则不响应对应请求。

    Fallback: 兼容旧 NODE_CAPABILITIES；再 fallback 到全量（保持向后兼容）。
    """
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
    elif source == "akshare":
        result = await handle_akshare(action, params)
    elif source == "tushare":
        result = await handle_tushare(action, params)
    elif source == "fmp":
        result = await handle_fmp(action, params)
    elif source == "finnhub":
        # QUOTE/COMPANY_NEWS/MARKET_NEWS/EARNINGS/ECONOMIC_CALENDAR/INSIDER_TRADING/STOCK_HISTORY
        result = await handle_finnhub(action, params)
    elif source == "fred":
        # MACRO_SERIES/ECONOMIC_CALENDAR
        result = await handle_fred(action, params)
    elif source == "dbnomics":
        # ECONOMIC_CALENDAR
        result = await handle_dbnomics(action, params)
    elif source == "rbi":
        # ECONOMIC_CALENDAR
        result = await handle_rbi(action, params)
    elif source in ("tavily", "bocha", "jina"):
        # SEARCH
        result = await handle_search(source, action, params)
    elif source == "futu":
        # Futu 依赖本地 OpenD TCP，仅声明 DS_CAPABILITIES 含 futu 的节点（主节点）响应
        result = await handle_futu(action, params)
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
            from data_subservice.futu_src.watchdog import FutuWatchdog

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
        except Exception as e:
            logger.warning(f"⚠️ Redis 心跳注册失败（子服务仍可独立运行）: {e}")


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
