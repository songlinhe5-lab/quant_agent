"""YFinance 采集器工厂：宏观指标 HA daemon。"""

from __future__ import annotations

from collections.abc import Awaitable, Coroutine
from typing import Any


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    from backend.services.yfinance_service import yf_service

    print("  [yfinance] macro_data_daemon started")
    return [yf_service.macro_data_daemon()]
