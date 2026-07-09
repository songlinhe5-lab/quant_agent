"""
Data Subservice — HTTP 数据接口路由
======================================

为 YFinanceRouter (DIST-02) 提供子服务侧的 HTTP 端点。
包含 HMAC 签名验证、限流错误分类 (429 → error_category) 和路由器路径兼容。

端点:
  /v1/quote          — 实时行情 (微批处理)
  /v1/history        — 历史 K 线
  /v1/batch          — 微批处理行情
  /v1/indicators     — 技术指标
  /v1/search         — 标的搜索
  /v1/macro          — 宏观指标快照 (从 Redis 缓存读取)
  /v1/health         — yfinance 数据源健康状态

兼容路由 (YFinanceRouter URL 适配):
  /api/v1/data-source/proxy/yfinance    → 按 fetch_type 分发
  /api/v1/data-source/proxy/batch_quote → /v1/batch

Redis 键空间:
  yf_macro_cache_{ticker}  — macro_data_daemon 写入的宏观指标缓存 (TTL=12h)

任务编号: DIST-07
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.core.logger import logger

# ─────────────────────────────────────────
#  环境变量
# ─────────────────────────────────────────
_HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
_ALLOWED_IPS = os.getenv("DATA_SOURCE_ALLOWED_IPS", "")
_allowed_ip_set = set(ip.strip() for ip in _ALLOWED_IPS.split(",") if ip.strip()) if _ALLOWED_IPS else set()
_REPLAY_WINDOW = 300  # 5 分钟防重放窗口

# 重放检测缓存 (ip:timestamp → 验证时间)
_request_timestamps: Dict[str, int] = {}

router = APIRouter(tags=["Data Subservice API"])


# ─────────────────────────────────────────
#  安全验证
# ─────────────────────────────────────────

def _verify_ip(request: Request) -> bool:
    """IP 白名单验证。未配置白名单时放行所有请求。"""
    if not _allowed_ip_set:
        return True
    client_ip = request.client.host if request.client else ""
    if client_ip in _allowed_ip_set:
        return True
    logger.warning(f"[DataSubservice] IP 白名单拒绝: {client_ip}")
    return False


def _verify_signature(request: Request, body: dict) -> bool:
    """
    HMAC-SHA256 签名验证 + 时间戳防重放。

    与主服务 backend/routers/data_source.py 的验证逻辑保持一致。
    未配置 HMAC_SECRET 时放行所有请求 (开发模式)。
    """
    if not _HMAC_SECRET:
        return True

    signature = request.headers.get("X-Data-Source-Signature", "")
    if not signature:
        logger.warning("[DataSubservice] 请求缺少 HMAC 签名")
        return False

    timestamp = request.headers.get("X-Data-Source-Timestamp", "")
    if not timestamp:
        logger.warning("[DataSubservice] 请求缺少时间戳")
        return False

    try:
        req_timestamp = int(timestamp)
    except ValueError:
        logger.warning("[DataSubservice] 时间戳格式无效")
        return False

    # 时间窗口校验
    now = int(time.time())
    if abs(now - req_timestamp) > _REPLAY_WINDOW:
        logger.warning(f"[DataSubservice] 请求时间戳过期: {req_timestamp}, 当前: {now}")
        return False

    # 防重放检测
    client_ip = request.client.host if request.client else ""
    signature_key = f"{client_ip}:{timestamp}"
    if signature_key in _request_timestamps:
        logger.warning("[DataSubservice] 重放攻击检测")
        return False
    _request_timestamps[signature_key] = now

    # HMAC 签名校验
    body_with_ts = body.copy()
    body_with_ts["__timestamp"] = timestamp
    expected = hashlib.sha256(
        _HMAC_SECRET.encode("utf-8")
        + json.dumps(body_with_ts, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return signature == expected


def _cleanup_old_timestamps() -> None:
    """清理过期的重放检测缓存"""
    now = int(time.time())
    to_remove = [k for k, ts in _request_timestamps.items() if now - ts > _REPLAY_WINDOW]
    for k in to_remove:
        del _request_timestamps[k]


# ─────────────────────────────────────────
#  限流错误检测
# ─────────────────────────────────────────

_RATE_LIMIT_KEYWORDS = ["429", "限流", "Rate limit", "Too Many Requests", "YFRateLimitError"]


def _detect_error_category(result: dict) -> dict:
    """
    检测 YFinanceWorker 返回中的限流信号，注入 error_category。

    YFinanceRouter 据此判断:
    - error_category == "rate_limit" → failover 到下一节点，不计入熔断
    - error_category == "normal" 或不存在 → 计入失败计数
    """
    msg = str(result.get("message", ""))
    if any(kw in msg for kw in _RATE_LIMIT_KEYWORDS):
        result["error_category"] = "rate_limit"
    return result


# ─────────────────────────────────────────
#  辅助函数
# ─────────────────────────────────────────

def _get_worker():
    """获取全局 YFinanceWorker 实例，不可用时返回 None"""
    from data_subservice.main import _yf_worker
    return _yf_worker


def _get_redis():
    """获取全局 Redis 客户端实例"""
    from data_subservice.main import _redis_client
    return _redis_client


async def _security_check(request: Request) -> Optional[JSONResponse]:
    """
    统一安全校验入口。返回 None 表示通过，否则返回错误响应。
    """
    _cleanup_old_timestamps()

    if not _verify_ip(request):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "message": "IP not allowed"},
        )

    body = await request.json()
    if not _verify_signature(request, body):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid signature"},
        )

    return None


def _worker_unavailable() -> JSONResponse:
    """YFinanceWorker 未初始化时返回 503"""
    return JSONResponse(
        status_code=503,
        content={"status": "error", "message": "YFinanceWorker 未初始化"},
    )


# ─────────────────────────────────────────
#  /v1/* 端点
# ─────────────────────────────────────────

@router.post("/v1/quote")
async def v1_quote(request: Request):
    """
    实时行情 (微批处理)。

    请求体: {"ticker": "AAPL", ...}
    响应:   YFinanceWorker.batched_quote 的返回值
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    try:
        result = await worker.batched_quote(ticker, req_type="quote")
        return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/quote 异常: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/v1/history")
async def v1_history(request: Request):
    """
    历史 K 线。

    请求体: {"ticker": "AAPL", "period": "1mo", "interval": "1d", ...}
    响应:   {"success": bool, "data": ..., "message": str}
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    # 提取 history 专属参数，其余透传
    kwargs = {k: v for k, v in body.items() if k not in ("ticker",)}

    try:
        result = await worker.fetch(ticker, "history", ttl=3600, **kwargs)
        return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/history 异常: {e}")
        return {"success": False, "data": None, "message": str(e)}


@router.post("/v1/batch")
async def v1_batch(request: Request):
    """
    微批处理行情。

    请求体: {"ticker": "AAPL", "req_type": "quote", ...}
    响应:   YFinanceWorker.batched_quote 的返回值
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    req_type = body.get("req_type", "quote")
    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    kwargs = {k: v for k, v in body.items() if k not in ("ticker", "req_type")}

    try:
        result = await worker.batched_quote(ticker, req_type=req_type, **kwargs)
        return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/batch 异常: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/v1/indicators")
async def v1_indicators(request: Request):
    """
    技术指标。

    请求体: {"ticker": "AAPL", ...}
    响应:   YFinanceWorker.tech_indicators 的返回值
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    kwargs = {k: v for k, v in body.items() if k != "ticker"}

    try:
        result = await worker.tech_indicators(ticker, **kwargs)
        return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/indicators 异常: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/v1/search")
async def v1_search(request: Request):
    """
    标的搜索。

    请求体: {"query": "Apple"}
    响应:   YFinanceWorker.search 的返回值
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    query = body.get("query", "")
    if not query:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 query 参数"},
        )

    try:
        result = await worker.search(query)
        return result
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/search 异常: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/v1/macro")
async def v1_macro(request: Request):
    """
    宏观指标快照。

    从 Redis 缓存读取 macro_data_daemon 写入的 yf_macro_cache_{ticker} 数据。
    支持可选的 ?ticker= 查询参数过滤特定标的。
    """
    redis_client = _get_redis()
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Redis 未连接"},
        )

    # 默认宏观指标列表 (与 macro_data_daemon 保持一致)
    default_tickers = [
        "^GSPC", "^IXIC", "^HSI", "^TNX", "JPY=X", "DX-Y.NYB",
        "CNH=X", "BTC-USD", "GC=F", "CL=F", "^VIX", "^N225",
    ]

    ticker_param = request.query_params.get("ticker", "")
    tickers = [t.strip() for t in ticker_param.split(",") if t.strip()] if ticker_param else default_tickers

    result = {}
    try:
        for ticker in tickers:
            cache_key = f"yf_macro_cache_{ticker}"
            cached = await redis_client.get(cache_key)
            if cached:
                result[ticker] = json.loads(cached)
    except Exception as e:
        logger.error(f"[DataSubservice] /v1/macro Redis 读取异常: {e}")
        return {"status": "error", "message": str(e)}

    if not result:
        return {"status": "success", "data": {}, "message": "无宏观指标缓存数据"}

    return {"status": "success", "data": result}


@router.get("/v1/health")
async def v1_health():
    """
    yfinance 数据源健康状态。

    返回 YFinanceWorker 的健康信息 (熔断/限流/daemon 状态)。
    """
    worker = _get_worker()
    if not worker:
        return {
            "status": "degraded",
            "message": "YFinanceWorker 未初始化",
        }

    health = worker.get_health()
    return {"status": "success", "data": health}


# ─────────────────────────────────────────
#  路由器兼容路径 (YFinanceRouter URL 适配)
# ─────────────────────────────────────────

@router.post("/api/v1/data-source/proxy/yfinance")
async def proxy_yfinance(request: Request):
    """
    YFinanceRouter 兼容端点。

    路由器发送: POST /api/v1/data-source/proxy/yfinance
    请求体: {"ticker": "AAPL", "fetch_type": "history"|"quote"|"tech", ...}

    根据 fetch_type 分发到对应的 /v1/* 处理逻辑:
    - fetch_type="quote"  → batched_quote
    - fetch_type="tech"   → tech_indicators
    - fetch_type="history" (默认) → fetch
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    fetch_type = body.get("fetch_type", "history")
    kwargs = body.get("kwargs", {})

    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    logger.info(f"[DataSubservice] proxy/yfinance: ticker={ticker}, fetch_type={fetch_type}")

    try:
        if fetch_type == "quote":
            result = await worker.batched_quote(ticker, req_type="quote", **kwargs)
            return _detect_error_category(result)
        elif fetch_type == "tech":
            result = await worker.tech_indicators(ticker, **kwargs)
            return _detect_error_category(result)
        else:
            # 默认 history
            result = await worker.fetch(ticker, "history", ttl=3600, **kwargs)
            return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] proxy/yfinance 异常: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/v1/data-source/proxy/batch_quote")
async def proxy_batch_quote(request: Request):
    """
    YFinanceRouter 兼容端点 — 微批处理行情。

    路由器发送: POST /api/v1/data-source/proxy/batch_quote
    请求体: {"ticker": "AAPL", "req_type": "quote", ...}
    """
    sec = await _security_check(request)
    if sec:
        return sec

    worker = _get_worker()
    if not worker:
        return _worker_unavailable()

    body = await request.json()
    ticker = body.get("ticker", "")
    req_type = body.get("req_type", "quote")
    kwargs = {k: v for k, v in body.items() if k not in ("ticker", "req_type")}

    if not ticker:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "缺少 ticker 参数"},
        )

    logger.info(f"[DataSubservice] proxy/batch_quote: ticker={ticker}, req_type={req_type}")

    try:
        result = await worker.batched_quote(ticker, req_type=req_type, **kwargs)
        return _detect_error_category(result)
    except Exception as e:
        logger.error(f"[DataSubservice] proxy/batch_quote 异常: {e}")
        return {"status": "error", "message": str(e)}
