"""
==========================================
Data Subservice — 路由层 (能力感知)
==========================================

子服务作为「数据源节点」部署在远程 VPS，根据 DS_CAPABILITIES 暴露对应的
代理端点 (proxy)。主节点经 DataSourceRouter 调用：
    POST {node.url}/api/v1/data-source/proxy/{capability}

当前支持的能力:
  - yfinance  : 美股/加密货币/外汇 (US-West 节点)
  - tushare   : A股日线/实时/基本面/沪深港通 (北京从节点)
  - akshare   : 沪深港通资金流向等 (北京从节点)

安全: 与主节点 data_source.py 一致的 HMAC 签名 + IP 白名单 + 重放窗口。
"""

import hashlib
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request

from data_subservice.nodeinfo import get_node_info

router = APIRouter()

# ── 安全配置 (须与主节点 DATA_SOURCE_* 一致) ──
_HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
_ALLOWED_IPS = os.getenv("DATA_SOURCE_ALLOWED_IPS", "")
_RATE_LIMIT = os.getenv("DATA_SOURCE_RATE_LIMIT", "100/minute")

_allowed_ip_set = {ip.strip() for ip in _ALLOWED_IPS.split(",") if ip.strip()} if _ALLOWED_IPS else set()

_REPLAY_WINDOW = 300
_request_timestamps: dict = {}

# 子服务实际暴露的能力 (由 main.py 注入，仅暴露本节点声明的能力)
_ENABLED_CAPABILITIES: set = set()


def set_capabilities(caps: list[str]) -> None:
    """由 main.py 启动时注入，控制哪些 proxy 端点可用。"""
    global _ENABLED_CAPABILITIES
    _ENABLED_CAPABILITIES = set(caps)


def _verify_ip(request: Request) -> bool:
    if not _allowed_ip_set:
        return True
    client_ip = request.client.host if request.client else ""
    if client_ip in _allowed_ip_set:
        return True
    return False


def _verify_signature(request: Request, body: dict) -> bool:
    if not _HMAC_SECRET:
        return True
    signature = request.headers.get("X-Data-Source-Signature", "")
    if not signature:
        return False
    timestamp = request.headers.get("X-Data-Source-Timestamp", "")
    if not timestamp:
        return False
    try:
        req_timestamp = int(timestamp)
    except ValueError:
        return False
    now = int(time.time())
    if abs(now - req_timestamp) > _REPLAY_WINDOW:
        return False
    client_ip = request.client.host if request.client else ""
    signature_key = f"{client_ip}:{timestamp}"
    if signature_key in _request_timestamps:
        return False
    _request_timestamps[signature_key] = now
    body_with_ts = body.copy()
    body_with_ts["__timestamp"] = timestamp
    expected = hashlib.sha256(
        _HMAC_SECRET.encode("utf-8") + json.dumps(body_with_ts, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return signature == expected


def _cleanup_old_timestamps() -> None:
    now = int(time.time())
    for key in [k for k, ts in _request_timestamps.items() if now - ts > _REPLAY_WINDOW]:
        del _request_timestamps[key]


def _require_capability(cap: str, request: Request):
    """校验 IP + 签名 + 能力是否已启用，失败直接抛 HTTPException。"""
    _cleanup_old_timestamps()
    if not _verify_ip(request):
        raise HTTPException(status_code=403, detail="IP not allowed")
    if not _verify_signature(request, request._ds_body):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if cap not in _ENABLED_CAPABILITIES:
        raise HTTPException(status_code=404, detail=f"capability '{cap}' not enabled on this node")


# ==========================================
# YFinance 代理 (US-West 节点)
# ==========================================
@router.post("/api/v1/data-source/proxy/yfinance")
async def proxy_yfinance(request: Request):
    """代理 yfinance 请求，委托 yfinance_worker 执行。"""
    body = await request.json()
    request._ds_body = body
    _require_capability("yfinance", request)

    from data_subservice.yfinance_worker import handle

    ticker = body.get("ticker", "")
    fetch_type = body.get("fetch_type", "")
    kwargs = body.get("kwargs", {})
    try:
        return {"success": True, "data": await handle(ticker, fetch_type, kwargs)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": str(e)}


# ==========================================
# Tushare 代理 (北京从节点)
# ==========================================
@router.post("/api/v1/data-source/proxy/tushare")
async def proxy_tushare(request: Request):
    """代理 Tushare 请求 (A股日线/实时/基本面/沪深港通)。"""
    body = await request.json()
    request._ds_body = body
    _require_capability("tushare", request)

    action = body.get("action", "")
    params = body.get("params", {}) or {}

    try:
        from backend.services.tushare.service import tushare_service

        svc = tushare_service
        if action == "stock_history":
            raw = svc.get_daily_history(
                ticker=str(params.get("ticker", "")),
                start_date=params.get("start_date"),
                end_date=params.get("end_date"),
                num=int(params.get("num", 100)),
                adj=params.get("adj", "qfq"),
            )
        elif action == "stock_quote":
            raw = svc.get_realtime_quote(ticker=str(params.get("ticker", "")))
        elif action == "fundamental":
            sub = params.get("sub", "daily_basic")
            if sub == "income":
                raw = svc.get_income(ticker=str(params.get("ticker", "")), period=params.get("period"))
            elif sub == "fina_indicator":
                raw = svc.get_fina_indicator(ticker=str(params.get("ticker", "")), period=params.get("period"))
            elif sub == "balancesheet":
                raw = svc.get_balancesheet(ticker=str(params.get("ticker", "")), period=params.get("period"))
            elif sub == "cashflow":
                raw = svc.get_cashflow(ticker=str(params.get("ticker", "")), period=params.get("period"))
            else:
                raw = svc.get_daily_basic(ticker=str(params.get("ticker", "")), trade_date=params.get("trade_date"))
        elif action == "fund_flow":
            raw = svc.get_moneyflow_hsgt(start_date=params.get("start_date"), end_date=params.get("end_date"))
        elif action == "stock_list":
            raw = svc.get_stock_basic(
                list_status=params.get("list_status", "L"),
                exchange=params.get("exchange"),
                fields=params.get("fields"),
            )
        elif action == "lowfreq_history":
            raw = svc.get_lowfreq_history(
                ticker=str(params.get("ticker", "")),
                freq=params.get("freq", "weekly"),
                start_date=params.get("start_date"),
                end_date=params.get("end_date"),
                num=int(params.get("num", 100)),
            )
        elif action == "macro":
            raw = svc.get_macro(
                api_name=str(params.get("api_name", "")),
                **{k: v for k, v in params.items() if k not in ("api_name",)},
            )
        else:
            return {"success": False, "message": f"unsupported tushare action: {action}"}
        return raw
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": str(e)}


# ==========================================
# AKShare 代理 (北京从节点)
# ==========================================
@router.post("/api/v1/data-source/proxy/akshare")
async def proxy_akshare(request: Request):
    """代理 AKShare 请求 (沪深港通资金流向等)。"""
    body = await request.json()
    request._ds_body = body
    _require_capability("akshare", request)

    action = body.get("action", "")
    kwargs = body.get("kwargs", {}) or {}

    try:
        from backend.services.akshare import akshare_service

        if action == "southbound":
            raw = await akshare_service.get_southbound_flow()
        elif action == "northbound":
            raw = await akshare_service.get_northbound_flow()
        elif action == "hsgt_holders":
            raw = await akshare_service.get_hsgt_top_holders(symbol=kwargs.get("symbol", "00700"))
        elif action == "company_news":
            raw = await akshare_service.get_company_news(ticker=kwargs.get("ticker", ""))
        elif action == "stock_quote":
            raw = await akshare_service.get_stock_quote(ticker=kwargs.get("ticker", ""))
        elif action == "stock_history":
            raw = await akshare_service.get_stock_history(ticker=kwargs.get("ticker", ""), num=kwargs.get("num", 60))
        elif action == "economic_calendar":
            raw = await akshare_service.get_economic_calendar(days_ahead=kwargs.get("days_ahead", 7))
        else:
            return {"status": "error", "message": f"unsupported akshare action: {action}"}
        return raw
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


# ==========================================
# 健康检查 / 节点信息
# ==========================================
@router.get("/api/v1/ping")
async def ping():
    return {"status": "ok", "node": get_node_info().node_id}


@router.get("/api/v1/node/info")
async def node_info():
    return get_node_info().model_dump()


@router.get("/api/v1/datasource/registry/nodes")
async def registry_nodes():
    from backend.core.service_registry import service_registry

    return {"nodes": service_registry.get_all_nodes()}
