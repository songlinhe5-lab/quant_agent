"""YFinance 采集器工厂：宏观指标 HA daemon（远程子服务模式）。

后端进程不再本地执行 yfinance。宏观数据经 DataSourceRouter 联邦到
US-YF-A/B 子服务节点拉取，并写入 Redis ``yf_macro_cache_*`` 供
macro_app / routers 读取。实际 yfinance 执行在子服务侧完成。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Coroutine
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 宏观指标 ticker 列表（与子服务 yfinance 宏观采集一致）
_MACRO_TICKERS = [
    "^VIX",
    "^GSPC",
    "^IXIC",
    "^DJI",
    "^RUT",
    "GC=F",
    "CL=F",
    "BTC-USD",
    "EURUSD=X",
    "USDJPY=X",
    "^TNX",
    "^TYX",
    "TLT",
    "HYG",
    "EMB",
]


async def _refresh_macro_once() -> None:
    """经子服务拉一次宏观指标快照，写入 Redis 缓存。"""
    from backend.core.redis_client import redis_client
    from backend.services.datasource.router import data_source_router

    for ticker in _MACRO_TICKERS:
        try:
            result = await data_source_router.fetch_yfinance(ticker, "quote", req_type="quote")
            if not result.get("success"):
                logger.warning(
                    "yfinance macro refresh failed",
                    ticker=ticker,
                    message=result.get("message"),
                )
                continue
            data = result.get("data") or {}
            await redis_client.set(
                f"yf_macro_cache_{ticker.lower()}",
                json.dumps(data, default=str),
                ex=3600,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("yfinance macro refresh error", ticker=ticker, error=str(exc))


async def macro_data_daemon() -> None:
    """周期性拉取宏观指标快照（远程子服务）。"""
    print("  [yfinance] macro_data_daemon started (remote subservice mode)")
    while True:
        await _refresh_macro_once()
        await asyncio.sleep(300)  # 5 分钟刷新间隔


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    return [macro_data_daemon()]
