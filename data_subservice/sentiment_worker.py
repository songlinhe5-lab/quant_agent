"""Sentiment 采集 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=sentiment) 访问本 worker。
沿用 finnhub_worker 的 handle_* 契约（router 已按此约定解析）。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.logger import logger
from data_subservice._internal.sentiment.apewisdom import apewisdom_service

_SENTIMENT_DISPATCH: dict[str, Any] = {
    "TRENDING": ("get_trending", ["filter", "page", "page_size", "top_n"]),
}


async def handle_sentiment(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """动作分发：action -> apewisdom_service 方法。

    返回普通 dict（由 main.fetch_data 包成 {"code":0,"data":...}）。
    """
    if action not in _SENTIMENT_DISPATCH:
        logger.warning(f"⚠️ [Sentiment] 未知动作: {action}")
        return {"error": f"unknown sentiment action: {action}"}

    method_name, arg_names = _SENTIMENT_DISPATCH[action]
    method = getattr(apewisdom_service, method_name)
    call_args = {k: params.get(k) for k in arg_names if params.get(k) is not None}
    return await method(**call_args)


async def startup() -> None:
    logger.info("[Sentiment-worker] 初始化完成 (ApeWisdom 客户端就绪)")
