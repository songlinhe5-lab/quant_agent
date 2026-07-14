"""AKShare 采集器工厂：北京 VPS Redis 中继 daemon。"""

from __future__ import annotations

from collections.abc import Awaitable, Coroutine
from typing import Any


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    from backend.workers.akshare_collector import akshare_collector_daemon

    print("  [akshare] collector daemon started (Redis 中继模式)")
    return [akshare_collector_daemon()]
