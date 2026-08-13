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

# 宏观指标 ticker 列表（覆盖 macro_app.assets_config 19 个 + 情绪/雷达附加指标）。
# 读侧 fetch_single_asset 按 yf_code.lower() 读 yf_macro_cache_*，写侧必须与读侧
# assets_config 的 yf 代码一一对应，否则对应资产读不到缓存 → value=0 面板空白。
_MACRO_TICKERS = [
    # ── 大类资产走势 assets_config 的 19 个 ──
    "^GSPC",
    "ES=F",
    "^IXIC",
    "NQ=F",
    "^HSI",
    "HSTECH.HK",
    "^TNX",
    "JPY=X",
    "DX-Y.NYB",
    "USDCNH=X",
    "BTC-USD",
    "GC=F",
    "CL=F",
    "HG=F",
    "^VIX",
    "^N225",
    "XLK",
    "XLE",
    "KWEB",
    # ── 情绪风向标 / 风险雷达附加指标 ──
    "^DJI",
    "^RUT",
    "EURUSD=X",
    "USDJPY=X",
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
            # 拉 HISTORY K线（而非 QUOTE 快照），使读侧 macro_app.fetch_single_asset
            # 能提取 close 序列渲染 sparkline。读侧按 K线 list 解析（close/date 字段），
            # 写 QUOTE dict 会导致读侧解析失败 → 大类资产/雷达/情绪全空。
            result = await data_source_router.fetch_yfinance(ticker, "history", period="1mo", interval="1d")
            if not result.get("success"):
                logger.warning(
                    "yfinance macro refresh failed",
                    ticker=ticker,
                    message=result.get("message"),
                )
                continue
            payload = result.get("data") or {}
            # 子服务 HISTORY 信封: {"symbol","interval","count","data":[...K线...],"source"}
            records = payload.get("data") or payload.get("records") or []
            await redis_client.set(
                f"yf_macro_cache_{ticker.lower()}",
                json.dumps(records, default=str),
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
