"""Finnhub / 市场守护进程工厂：仅 master 节点启 global daemon。"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Coroutine
from typing import Any


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    node_type = os.getenv("NODE_TYPE", "master")
    if node_type != "master":
        print("  [finnhub] slave mode: data fetching only, no daemon")
        return []

    from backend.services.market_daemon import run_global_daemon

    print("  [market-daemon] global daemon started")
    return [run_global_daemon()]
