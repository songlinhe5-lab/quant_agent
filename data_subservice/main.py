"""
Data Subservice — 独立数据源 HTTP 服务（物理解耦版）

作为叶子数据源节点运行，仅依赖 data_subservice._internal（自包含），
不再 import 任何 backend 包模块。对外暴露统一 /api/v1/data 端点，
由主服务经 DataSourceRouter 通过 HMAC 签名调用。
"""

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

from data_subservice._internal.circuit_breaker import circuit_breaker
from data_subservice._internal.logger import logger
from data_subservice._internal.redis_client import redis_client
from data_subservice._internal.service_registry import ServiceRegistry
from data_subservice.akshare_worker import handle_akshare
from data_subservice.nodeinfo import get_node_info
from data_subservice.tushare_worker import handle_tushare
from data_subservice.yfinance_worker import handle_yfinance

load_dotenv()

# ── 配置 ──
HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "change-me-in-prod")
SERVICE_PORT = int(os.getenv("DATASOURCE_PORT", "8000"))
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


@app.post("/api/v1/data", dependencies=[Depends(verify_hmac)])
async def fetch_data(request: Request):
    """统一数据源获取端点。路由到 yfinance / akshare / tushare 实现。"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON 请求体")

    source = payload.get("source", "").lower()
    action = payload.get("action", "")
    params = payload.get("params", {})

    if source == "yfinance":
        result = await handle_yfinance(action, params)
    elif source == "akshare":
        result = await handle_akshare(action, params)
    elif source == "tushare":
        result = await handle_tushare(action, params)
    else:
        raise HTTPException(status_code=400, detail=f"未知数据源: {source}")

    return JSONResponse({"code": 0, "data": result})


@app.get("/metrics/circuit")
async def circuit_metrics():
    return JSONResponse(circuit_breaker.status_snapshot())


# ── 启动事件：可选向主 Redis 注册节点心跳 ──
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Data Subservice 启动完成 (物理解耦模式，无 backend 依赖)")
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
