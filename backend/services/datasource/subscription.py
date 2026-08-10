"""
SubscriptionService — 推送数据平面统一入口（BE-ARCH-07）

位于 DataSourceInterface 请求-响应平面之外，提供**推送/订阅平面**的统一抽象。
高频 tick 流经 Redis pubsub 旁路流通，本服务封装该旁路，对外暴露干净接口：
  - get_tick(symbol) → 最新实时价（进程内 LRU 缓存，TTL 5s）
  - record_hit() / record_miss() → 命中率埋点
  - stats() → 命中/降级统计快照
  - start_ingest(symbols) → 启动 Redis pubsub 回灌协程

设计文档：docs/14 §2.5 双平面数据流

铁律：
  - 本服务不直连外部 WS；外部 WS 收口在 data_subservice（DIST-22）。
  - 业务层经本服务获取实时价，禁止直接 import tick_cache 或 Redis pubsub 频道。
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

# ────────────────────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────────────────────

_TICK_TTL_SEC = 5.0  # 实时 tick 有效期（秒），超过即视为过期


# ────────────────────────────────────────────────────────────────────────────
# TickCache — 进程内最近 tick 缓存（线程安全，LRU + TTL）
# ────────────────────────────────────────────────────────────────────────────


class TickCache:
    """进程内最近 tick 缓存（线程安全，TTL 过期自动失效）。

    存储结构：{symbol: (timestamp, tick_data)}
    - timestamp: time.monotonic() 时间戳
    - tick_data: Finnhub WS 原始消息（trade/quote）
    - TTL: _TICK_TTL_SEC 秒，超过即视为过期并删除
    """

    def __init__(self, ttl_sec: float = _TICK_TTL_SEC) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()
        self._ttl = ttl_sec

    def put(self, symbol: str, tick: dict[str, Any]) -> None:
        """写入最新 tick（覆盖旧值）。"""
        with self._lock:
            self._store[symbol.upper()] = (time.monotonic(), tick)

    def get(self, symbol: str) -> Optional[dict[str, Any]]:
        """读取最新 tick；TTL 过期返回 None。"""
        with self._lock:
            item = self._store.get(symbol.upper())
            if not item:
                return None
            ts, tick = item
            if time.monotonic() - ts > self._ttl:
                del self._store[symbol.upper()]
                return None
            return tick

    def clear(self) -> None:
        """清空缓存（测试用）。"""
        with self._lock:
            self._store.clear()


# ────────────────────────────────────────────────────────────────────────────
# 命中率埋点（线程安全，Lock 保护）
# ────────────────────────────────────────────────────────────────────────────

_metrics_lock = Lock()
_hits = 0
_misses = 0


def _record_tick_hit() -> None:
    """记录一次实时价命中（hit）。"""
    global _hits
    with _metrics_lock:
        _hits += 1
    _sync_prometheus(hit=True)


def _record_tick_miss() -> None:
    """记录一次实时价降级（miss）。"""
    global _misses
    with _metrics_lock:
        _misses += 1
    _sync_prometheus(hit=False)


def _sync_prometheus(hit: bool) -> None:
    """将命中/降级事件同步到 Prometheus（Counter 增量 inc，Gauge 重算命中率）。"""
    try:
        from backend.core.metrics import (
            TICK_CACHE_HIT_RATE,
            TICK_CACHE_HITS,
            TICK_CACHE_MISSES,
        )

        if hit:
            TICK_CACHE_HITS.inc()
        else:
            TICK_CACHE_MISSES.inc()
        with _metrics_lock:
            h, m = _hits, _misses
        total = h + m
        TICK_CACHE_HIT_RATE.set((h / total) if total else float("nan"))
    except Exception:  # noqa: BLE001
        return


def _tick_cache_stats() -> dict[str, Any]:
    """返回实时价命中/降级统计快照。

    返回: {hits, misses, total, hit_rate(0-1, 无查询时为 None)}
    """
    with _metrics_lock:
        hits = _hits
        misses = _misses
    total = hits + misses
    hit_rate = (hits / total) if total else None
    return {"hits": hits, "misses": misses, "total": total, "hit_rate": hit_rate}


# ────────────────────────────────────────────────────────────────────────────
# Broker / Kline 缓存（进程内，TTL 过期）
# ────────────────────────────────────────────────────────────────────────────


class _PolyCache:
    """进程内最近 broker / kline 推送缓存（线程安全，TTL 过期自动失效）。

    与 TickCache 同构，承载 quant:broker:* / quant:kline:* 频道回灌的数据。
    """

    def __init__(self, ttl_sec: float = _TICK_TTL_SEC) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()
        self._ttl = ttl_sec

    def put(self, symbol: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._store[symbol.upper()] = (time.monotonic(), data)

    def get(self, symbol: str) -> Optional[dict[str, Any]]:
        with self._lock:
            item = self._store.get(symbol.upper())
            if not item:
                return None
            ts, data = item
            if time.monotonic() - ts > self._ttl:
                del self._store[symbol.upper()]
                return None
            return data

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ────────────────────────────────────────────────────────────────────────────
# Redis pubsub 回灌
# ────────────────────────────────────────────────────────────────────────────


async def _redis() -> aioredis.Redis:
    """创建 Redis 异步连接（用于 pubsub 订阅）。"""
    return aioredis.from_url(
        f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}",
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )


async def _run_tick_ingest(symbols: list[str], cache: TickCache) -> None:
    """订阅 quant:tick:{symbol} 频道，回灌 tick_cache。

    由 SubscriptionService.start_ingest() 调用，不直接暴露给业务层。
    """
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
            except (json.DecodeError, TypeError):
                continue
            sym = data.get("symbol")
            if sym:
                cache.put(sym, data)
    except asyncio.CancelledError:  # noqa: PERF203
        await pubsub.unsubscribe()
        logger.info("[TickIngest] 回灌协程已停止")


async def _run_poly_ingest(
    symbols: list[str],
    cache: _PolyCache,
    channel_prefix: str,
) -> None:
    """订阅 quant:{prefix}:{symbol} 频道，回灌 _PolyCache。

    通用回灌协程，供 start_broker_ingest / start_kline_ingest 复用。
    channel_prefix 为 "broker" 或 "kline"。
    """
    if not symbols:
        logger.info(f"[PolyIngest:{channel_prefix}] 无订阅标的，回灌协程不启动")
        return
    r = await _redis()
    pubsub = r.pubsub()
    for sym in symbols:
        await pubsub.subscribe(f"quant:{channel_prefix}:{sym.upper()}")
    logger.info("[PolyIngest:%s] 已订阅 %d 个频道", channel_prefix, len(symbols))
    try:
        async for msg in pubsub.listen():
            if msg is None or msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            sym = data.get("ticker") or data.get("symbol")
            if sym:
                cache.put(sym, data)
    except asyncio.CancelledError:  # noqa: PERF203
        await pubsub.unsubscribe()
        logger.info("[PolyIngest:%s] 回灌协程已停止", channel_prefix)


# ────────────────────────────────────────────────────────────────────────────
# SubscriptionService — 推送平面统一入口
# ────────────────────────────────────────────────────────────────────────────


class SubscriptionService:
    """推送数据平面统一入口。

    封装 Redis pubsub 旁路，对外暴露干净接口：
      - get_tick(symbol) → 最新实时价（进程内 LRU 缓存，TTL 5s）
      - record_hit() / record_miss() → 命中率埋点
      - stats() → 命中/降级统计快照
      - start_ingest(symbols) → 启动 Redis pubsub 回灌协程

    业务层经本服务获取实时价，禁止直接 import tick_cache 或 Redis pubsub 频道。
    """

    def __init__(self, cache: Optional[TickCache] = None) -> None:
        self._cache = cache or TickCache()
        self._ingest_task: Optional[asyncio.Task] = None
        # BE-ARCH-07h-2: broker / kline 推送平面缓存与回灌任务
        self._broker_cache = _PolyCache()
        self._kline_cache = _PolyCache()
        self._broker_task: Optional[asyncio.Task] = None
        self._kline_task: Optional[asyncio.Task] = None

    # ── 实时价查询 ──

    def get_tick(self, symbol: str) -> Optional[dict[str, Any]]:
        """获取最新实时价（进程内 LRU 缓存，TTL 5s）。

        Args:
            symbol: 标的代码（如 "AAPL", "00700.HK"）

        Returns:
            Finnhub WS 原始消息（trade/quote），TTL 过期返回 None。
        """
        return self._cache.get(symbol)

    def put_tick(self, symbol: str, tick: dict[str, Any]) -> None:
        """写入最新 tick（覆盖旧值）。

        通常由 Redis pubsub 回灌协程调用，业务层不应直接调用。
        """
        self._cache.put(symbol, tick)

    # ── 经纪商队列查询（BE-ARCH-07h-2）──

    def get_broker(self, symbol: str) -> Optional[dict[str, Any]]:
        """获取最新经纪商队列推送（进程内 LRU 缓存，TTL 5s）。

        Args:
            symbol: 标的代码（如 "HK.00700" 或 "00700.HK"）

        Returns:
            Futu broker 推送消息，TTL 过期返回 None。
        """
        return self._broker_cache.get(symbol)

    def put_broker(self, symbol: str, data: dict[str, Any]) -> None:
        """写入最新 broker 推送（覆盖旧值）。通常由回灌协程调用。"""
        self._broker_cache.put(symbol, data)

    # ── 实时 K 线查询（BE-ARCH-07h-2）──

    def get_kline(self, symbol: str) -> Optional[dict[str, Any]]:
        """获取最新实时 K 线推送（进程内 LRU 缓存，TTL 5s）。

        Args:
            symbol: 标的代码

        Returns:
            Futu kline 推送消息，TTL 过期返回 None。
        """
        return self._kline_cache.get(symbol)

    def put_kline(self, symbol: str, data: dict[str, Any]) -> None:
        """写入最新 kline 推送（覆盖旧值）。通常由回灌协程调用。"""
        self._kline_cache.put(symbol, data)

    # ── 命中率埋点 ──

    def record_hit(self) -> None:
        """记录一次实时价命中（hit）。"""
        _record_tick_hit()

    def record_miss(self) -> None:
        """记录一次实时价降级（miss）。"""
        _record_tick_miss()

    def stats(self) -> dict[str, Any]:
        """返回实时价命中/降级统计快照。

        Returns:
            {hits, misses, total, hit_rate(0-1, 无查询时为 None)}
        """
        return _tick_cache_stats()

    # ── Redis pubsub 回灌 ──

    def start_ingest(self, symbols: list[str]) -> Optional[asyncio.Task]:
        """启动 Redis pubsub 回灌协程。

        由主 app 启动钩子调用，返回后台 Task。重复调用会取消旧任务。

        Args:
            symbols: 订阅标的列表（如 ["AAPL", "MSFT", "TSLA"]）

        Returns:
            后台 Task，或 None（symbols 为空时）。
        """
        if not symbols:
            logger.info("[SubscriptionService] 无订阅标的，跳过启动")
            return None

        # 取消旧任务（若有）
        if self._ingest_task is not None and not self._ingest_task.done():
            self._ingest_task.cancel()

        self._ingest_task = asyncio.create_task(_run_tick_ingest(symbols, self._cache))
        return self._ingest_task

    def stop_ingest(self) -> None:
        """停止 Redis pubsub 回灌协程。"""
        if self._ingest_task is not None and not self._ingest_task.done():
            self._ingest_task.cancel()
            self._ingest_task = None

    # ── Broker / Kline 推送平面回灌（BE-ARCH-07h-2）──

    def start_broker_ingest(self, symbols: list[str]) -> Optional[asyncio.Task]:
        """启动 quant:broker:{symbol} 频道回灌协程。

        由主 app 启动钩子调用，与 start_ingest 并行。重复调用会取消旧任务。
        """
        if not symbols:
            logger.info("[SubscriptionService] 无 broker 订阅标的，跳过启动")
            return None
        if self._broker_task is not None and not self._broker_task.done():
            self._broker_task.cancel()
        self._broker_task = asyncio.create_task(_run_poly_ingest(symbols, self._broker_cache, "broker"))
        return self._broker_task

    def start_kline_ingest(self, symbols: list[str]) -> Optional[asyncio.Task]:
        """启动 quant:kline:{symbol} 频道回灌协程。

        由主 app 启动钩子调用，与 start_ingest 并行。重复调用会取消旧任务。
        """
        if not symbols:
            logger.info("[SubscriptionService] 无 kline 订阅标的，跳过启动")
            return None
        if self._kline_task is not None and not self._kline_task.done():
            self._kline_task.cancel()
        self._kline_task = asyncio.create_task(_run_poly_ingest(symbols, self._kline_cache, "kline"))
        return self._kline_task

    def stop_poly_ingest(self) -> None:
        """停止 broker / kline 回灌协程。"""
        for task in (self._broker_task, self._kline_task):
            if task is not None and not task.done():
                task.cancel()
        self._broker_task = None
        self._kline_task = None


# ────────────────────────────────────────────────────────────────────────────
# 全局单例（供业务层直接调用）
# ────────────────────────────────────────────────────────────────────────────

subscription_service = SubscriptionService()
