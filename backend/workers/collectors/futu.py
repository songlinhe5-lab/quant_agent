"""Futu OpenD 采集器工厂：watchdog daemon。"""

from __future__ import annotations

from collections.abc import Awaitable, Coroutine
from typing import Any


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    from backend.services.futu.watchdog import get_watchdog
    from backend.services.futu_service import futu_service

    print("  [futu] watchdog daemon started")
    return [get_watchdog(futu_service).start()]
