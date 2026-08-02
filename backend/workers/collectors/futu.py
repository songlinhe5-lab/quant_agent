"""Futu OpenD 采集器工厂：watchdog daemon。"""

from __future__ import annotations

from collections.abc import Awaitable, Coroutine
from typing import Any


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    from backend.services.futu import futu_service
    from backend.services.futu.watchdog import get_watchdog

    # 启动看门狗前主动建连一次：避免 backend 先于 OpenD 启动时，
    # 看门狗首轮健康检查直接判定「断连」并陷入指数退避窗口导致长期失联。
    try:
        if futu_service.conn_mgr.status != "CONNECTED":
            futu_service.connect()
            print("  [futu] 主动建连完成，status=", futu_service.conn_mgr.status)
    except Exception as e:
        print(f"  [futu] 主动建连失败（看门狗将持续重试）: {e}")

    print("  [futu] watchdog daemon started")
    return [get_watchdog(futu_service).start()]
