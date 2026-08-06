"""
Finnhub WS 实时 tick 回灌（主节点侧，BE-ARCH-04 / BE-ARCH-07）

子服务 FinnhubWsClient 将实时 trade/quote 经 Redis pub 到 quant:tick:{symbol}。
主节点 backend 启动本订阅协程，消费频道写入进程内最近 tick 缓存（LRU，TTL 5s），
供 FinnhubDataSource / FMPDataSource 的 quote 在 REST 快照之外优先返回最近实时价。

红线：
  - 不直连外部 WS；外部 WS 收口在 data_subservice（DIST-22）。
  - 订阅端只读 Redis，业务仍经 DataSourceRegistry.fetch（不直接 import 本缓存）。

BE-ARCH-07 重构：
  - 推送平面统一抽象已迁至 ``backend.services.datasource.subscription``。
  - 本模块保留为向后兼容薄代理层，所有实现委托给 ``subscription_service``。
  - 新代码应直接 import ``subscription_service``，禁止继续 import 本模块内部符号。
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

# ── BE-ARCH-07: 委托给推送平面统一入口 ──────────────────────────────────────
from backend.services.datasource.subscription import (
    SubscriptionService,
    TickCache,
    subscription_service,
)
from backend.services.datasource.subscription import (
    _record_tick_hit as record_tick_hit,
)
from backend.services.datasource.subscription import (
    _record_tick_miss as record_tick_miss,
)
from backend.services.datasource.subscription import (
    _tick_cache_stats as tick_cache_stats,
)

# ── 向后兼容：保留全局 tick_cache 实例（旧代码直接 import 用）───────────────
# 新代码应经 subscription_service.get_tick() / put_tick() 访问。
tick_cache = subscription_service._cache

__all__ = [
    # BE-ARCH-07 新入口
    "SubscriptionService",
    "subscription_service",
    # 向后兼容旧符号
    "TickCache",
    "tick_cache",
    "record_tick_hit",
    "record_tick_miss",
    "tick_cache_stats",
    "run_tick_ingest",
    "start_tick_ingest_task",
]


async def run_tick_ingest(symbols: list[str]) -> None:
    """订阅 quant:tick:{symbol} 频道，回灌 tick_cache。

    委托给 subscription_service.start_ingest()。
    """
    await subscription_service._cache  # noqa: B018 - 确保 cache 已初始化
    task = subscription_service.start_ingest(symbols)
    if task is not None:
        await task


def start_tick_ingest_task(symbols: list[str]) -> Optional[asyncio.Task]:
    """由主 app 启动钩子调用，返回后台 Task。

    委托给 subscription_service.start_ingest()。
    """
    return subscription_service.start_ingest(symbols)
