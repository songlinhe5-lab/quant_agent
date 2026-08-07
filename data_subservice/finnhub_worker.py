"""Finnhub 采集 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=finnhub) 访问本 worker。
沿用 fmp_worker 的 handle_* 契约（router 已按此约定解析）。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.finnhub import finnhub_service
from data_subservice._internal.logger import logger

_FINNHUB_DISPATCH: dict[str, Any] = {
    "QUOTE": ("get_quote", ["symbol"]),
    "COMPANY_NEWS": ("get_company_news", ["ticker", "days_back"]),
    "MARKET_NEWS": ("get_market_news", ["category"]),
    "EARNINGS": ("get_earnings_calendar", ["days_ahead", "days_back"]),
    "ECONOMIC_CALENDAR": ("get_economic_calendar", ["days_ahead", "days_back"]),
    "INSIDER_TRADING": ("get_insider_transactions", ["ticker", "limit"]),
    "STOCK_HISTORY": ("get_stock_history", ["ticker", "days_back"]),
}


async def handle_finnhub(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """动作分发：action -> finnhub_service 方法。

    返回普通 dict（由 main.fetch_data 包成 {"code":0,"data":...}）。
    """
    if action not in _FINNHUB_DISPATCH:
        logger.warning(f"⚠️ [Finnhub] 未知动作: {action}")
        return {"error": f"unknown finnhub action: {action}"}

    method_name, arg_names = _FINNHUB_DISPATCH[action]
    method = getattr(finnhub_service, method_name)
    call_args = {k: params.get(k) for k in arg_names if params.get(k) is not None}
    return await method(**call_args)


async def startup() -> None:
    logger.info("[Finnhub-worker] 初始化完成 (Finnhub REST 客户端就绪)")
