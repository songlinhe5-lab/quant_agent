"""
Finnhub WS 实时 tick 回灌（主节点侧，BE-ARCH-04）

子服务 FinnhubWsClient 将实时 trade/quote 经 Redis pub 到 quant:tick:{symbol}。
主节点 backend 启动本订阅协程，消费频道写入进程内最近 tick 缓存（LRU，TTL 5s），
供 FinnhubDataSource / FMPDataSource 的 quote 在 REST 快照之外优先返回最近实时价。

红线：
  - 不直连外部 WS；外部 WS 收口在 data_subservice（DIST-22）。
  - 订阅端只读 Redis，业务仍经 DataSourceRegistry.fetch（不直接 import 本缓存）。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from threading import Lock
from typing import Any, Optional

import redis.asyncio as aioredis

from backend.core.logger import logger

_TTL = 5.0  # 实时 tick 有效期（秒）


class TickCache:
    """进程内最近 tick 缓存（线程安全，TTL 过期自动失效）。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def put(self, symbol: str, tick: dict[str, Any]) -> None:
        with self._lock:
            self._store[symbol.upper()] = (time.monotonic(), tick)

    def get(self, symbol: str) -> Optional[dict[str, Any]]:
        with self._lock:
            item = self._store.get(symbol.upper())
            if not item:
                return None
            ts, tick = item
            if time.monotonic() - ts > _TTL:
                del self._store[symbol.upper()]
                return None
            return tick


tick_cache = TickCache()


# ── tick_cache 命中率 / 降级率埋点（线程安全，Lock 保护）──────────────
# 用于验证 WS 实时价到底覆盖了多少 quote 查询：hit=命中实时价，miss=降级 REST。
_metrics_lock = Lock()
_hits = 0
_misses = 0


def record_tick_hit() -> None:
    global _hits
    with _metrics_lock:
        _hits += 1


def record_tick_miss() -> None:
    global _misses
    with _metrics_lock:
        _misses += 1


def tick_cache_stats() -> dict[str, Any]:
    """返回实时价命中/降级统计快照。

    返回: {hits, misses, total, hit_rate(0-1, 无查询时为 None)}
    """
    with _metrics_lock:
        hits = _hits
        misses = _misses
    total = hits + misses
    hit_rate = (hits / total) if total else None
    return {"hits": hits, "misses": misses, "total": total, "hit_rate": hit_rate}


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(
        f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}",
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


async def run_tick_ingest(symbols: list[str]) -> None:
    """订阅 quant:tick:{symbol} 频道，回灌 tick_cache。"""
    if not symbols:
        logger.info("[TickIngest] 无订阅标的，回灌协程不启动")
        return
    r = await _redis()
    pubsub = r.pubsub()
    for sym in symbols:
        await pubsub.subscribe(f"quant:tick:{sym.upper()}")
    logger.info("[TickIngest] 已订阅 %d 个实时 tick 频道", len(symbols))
    try:
        async for msg in pubsub.listen():
            if msg is None or msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            sym = data.get("symbol")
            if sym:
                tick_cache.put(sym, data)
    except asyncio.CancelledError:  # noqa: PERF203
        await pubsub.unsubscribe()
        logger.info("[TickIngest] 回灌协程已停止")


def start_tick_ingest_task(symbols: list[str]) -> Optional[asyncio.Task]:
    """由主 app 启动钩子调用，返回后台 Task。"""
    if not symbols:
        return None
    return asyncio.create_task(run_tick_ingest(symbols))
