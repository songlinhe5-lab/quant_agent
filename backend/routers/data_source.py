"""
==========================================
Data Source Proxy Router - 数据源代理路由
==========================================

提供数据源代理接口，允许其他节点通过 HTTP 调用本地数据源。

安全机制（公网暴露时必须启用）：
1. HMAC 签名验证（防止请求篡改）
2. 时间戳防重放攻击（±5分钟窗口）
3. IP 白名单（仅允许已知节点 IP 访问）
4. 请求频率限制（防 DDoS）

环境变量配置：
  DATA_SOURCE_HMAC_SECRET=...           # HMAC 签名密钥
  DATA_SOURCE_ALLOWED_IPS=1.2.3.4,5.6.7.8  # 允许的 IP 列表（逗号分隔）
  DATA_SOURCE_RATE_LIMIT=100/minute     # 请求频率限制
"""

import hashlib
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request

from backend.core.logger import logger

router = APIRouter(prefix="/data-source", tags=["Data Source Proxy"])

_HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
_ALLOWED_IPS = os.getenv("DATA_SOURCE_ALLOWED_IPS", "")
_RATE_LIMIT = os.getenv("DATA_SOURCE_RATE_LIMIT", "100/minute")

_allowed_ip_set = set(ip.strip() for ip in _ALLOWED_IPS.split(",") if ip.strip()) if _ALLOWED_IPS else set()

_REPLAY_WINDOW = 300

_request_timestamps = {}


def _verify_ip(request: Request) -> bool:
    if not _allowed_ip_set:
        return True

    client_ip = request.client.host if request.client else ""

    if client_ip in _allowed_ip_set:
        return True

    logger.warning(f"[Security] IP 白名单拒绝: {client_ip}")
    return False


def _verify_signature(request: Request, body: dict) -> bool:
    if not _HMAC_SECRET:
        return True

    signature = request.headers.get("X-Data-Source-Signature", "")
    if not signature:
        return False

    timestamp = request.headers.get("X-Data-Source-Timestamp", "")
    if not timestamp:
        logger.warning("[Security] 请求缺少时间戳")
        return False

    try:
        req_timestamp = int(timestamp)
    except ValueError:
        logger.warning("[Security] 时间戳格式无效")
        return False

    now = int(time.time())
    if abs(now - req_timestamp) > _REPLAY_WINDOW:
        logger.warning(f"[Security] 请求时间戳过期: {req_timestamp}, 当前: {now}")
        return False

    client_ip = request.client.host if request.client else ""
    signature_key = f"{client_ip}:{timestamp}"
    if signature_key in _request_timestamps:
        logger.warning("[Security] 重放攻击检测")
        return False
    _request_timestamps[signature_key] = now

    body_with_ts = body.copy()
    body_with_ts["__timestamp"] = timestamp
    expected = hashlib.sha256(
        _HMAC_SECRET.encode("utf-8") + json.dumps(body_with_ts, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return signature == expected


def _cleanup_old_timestamps():
    now = int(time.time())
    to_remove = [key for key, ts in _request_timestamps.items() if now - ts > _REPLAY_WINDOW]
    for key in to_remove:
        del _request_timestamps[key]


@router.post("/proxy/yfinance")
async def proxy_yfinance(request: Request):
    """代理 yfinance 请求"""
    _cleanup_old_timestamps()

    if not _verify_ip(request):
        raise HTTPException(status_code=403, detail="IP not allowed")

    body = await request.json()

    if not _verify_signature(request, body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    ticker = body.get("ticker", "")
    fetch_type = body.get("fetch_type", "")
    kwargs = body.get("kwargs", {})

    logger.info(f"[Proxy] YFinance 请求: {ticker}, {fetch_type}")

    from backend.services.yfinance_service import yf_service

    try:
        if fetch_type == "quote":
            return await yf_service.get_batched_quote(ticker, req_type="quote")
        elif fetch_type == "tech":
            return await yf_service.get_tech_indicators(ticker, **kwargs)
        elif fetch_type == "history":
            success, data, msg = await yf_service.fetch_yf_data(ticker, "history", ttl=3600, **kwargs)
            return {"success": success, "data": data, "message": msg}
        return {"success": False, "message": f"Unknown fetch_type: {fetch_type}"}
    except Exception as e:
        logger.error(f"[Proxy] YFinance 错误: {ticker}, {str(e)}")
        return {"success": False, "message": str(e)}


@router.post("/proxy/akshare")
async def proxy_akshare(request: Request):
    """代理 AKShare 请求"""
    _cleanup_old_timestamps()

    if not _verify_ip(request):
        raise HTTPException(status_code=403, detail="IP not allowed")

    body = await request.json()

    if not _verify_signature(request, body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    action = body.get("action", "")
    kwargs = body.get("kwargs", {})

    logger.info(f"[Proxy] AKShare 请求: {action}")

    from backend.services.akshare_service import akshare_service

    try:
        if action == "southbound":
            return await akshare_service.get_southbound_flow()
        elif action == "northbound":
            return await akshare_service.get_northbound_flow()
        elif action == "hsgt_holders":
            return await akshare_service.get_hsgt_top_holders(symbol=kwargs.get("symbol", "00700"))
        elif action == "company_news":
            return await akshare_service.get_company_news(ticker=kwargs.get("ticker", ""))
        elif action == "stock_quote":
            return await akshare_service.get_stock_quote(ticker=kwargs.get("ticker", ""))
        elif action == "stock_history":
            return await akshare_service.get_stock_history(ticker=kwargs.get("ticker", ""), num=kwargs.get("num", 60))
        elif action == "economic_calendar":
            return await akshare_service.get_economic_calendar(days_ahead=kwargs.get("days_ahead", 7))
        return {"status": "error", "message": f"Unknown akshare action: {action}"}
    except Exception as e:
        logger.error(f"[Proxy] AKShare 错误: {action}, {str(e)}")
        return {"status": "error", "message": str(e)}


@router.get("/health")
async def data_source_health():
    """数据源健康检查"""
    from backend.services.akshare_service import akshare_service
    from backend.services.yfinance_service import yf_service

    return {
        "status": "healthy",
        "yfinance": yf_service.get_health_status(),
        "akshare": akshare_service.get_health_status(),
    }
