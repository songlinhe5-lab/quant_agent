"""
DataSourceRegistry — 源实例注册表（docs/14 §5.1 · BE-ARCH-04）

持有 DataSourceInterface 实例，提供 register / get / fetch。
限流状态走 RateLimitRegistry，禁止与本表职责混淆。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from backend.core.circuit_breaker import CircuitBreakerOpenError
from backend.core.circuit_breaker_integration import fetch_via_breaker_async

from . import ErrorInfo, Result, ResultStatus
from .protocol import DataSourceInterface
from .registry import rate_limit_registry


class _SourceEntry:
    __slots__ = ("instance_id", "source")

    def __init__(self, source: DataSourceInterface, instance_id: str):
        self.source = source
        self.instance_id = instance_id


class DataSourceRegistry:
    """
    数据源实例全局注册表。

    用法:
        datasource_registry.register(LegacyYFinanceDataSource())
        result = await datasource_registry.fetch("yfinance", "history", {"ticker": "AAPL"})
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # source_name -> list of instances (multi-node ready)
        self._sources: dict[str, list[_SourceEntry]] = {}

    def register(
        self,
        source: DataSourceInterface,
        instance_id: Optional[str] = None,
    ) -> str:
        """注册数据源实例；返回 instance_id。同名同 id 则替换。"""
        iid = instance_id or f"{source.name}-default"
        entry = _SourceEntry(source, iid)
        with self._lock:
            bucket = self._sources.setdefault(source.name, [])
            for i, existing in enumerate(bucket):
                if existing.instance_id == iid:
                    bucket[i] = entry
                    break
            else:
                bucket.append(entry)
        # 预热限流条目
        rate_limit_registry.get_or_create(source.name)
        return iid

    def unregister(self, source_name: str, instance_id: Optional[str] = None) -> bool:
        """注销实例；未指定 instance_id 则移除该源全部实例。"""
        with self._lock:
            if source_name not in self._sources:
                return False
            if instance_id is None:
                del self._sources[source_name]
                return True
            before = len(self._sources[source_name])
            self._sources[source_name] = [e for e in self._sources[source_name] if e.instance_id != instance_id]
            removed = len(self._sources[source_name]) < before
            if not self._sources[source_name]:
                del self._sources[source_name]
            return removed

    def has(self, source_name: str) -> bool:
        with self._lock:
            return bool(self._sources.get(source_name))

    def list_names(self) -> list[str]:
        with self._lock:
            return list(self._sources.keys())

    def get(self, source_name: str, action: Optional[str] = None) -> Optional[DataSourceInterface]:
        """按名称取首个可用实例；可选按 capability 过滤。"""
        with self._lock:
            entries = list(self._sources.get(source_name, []))
        for entry in entries:
            src = entry.source
            if not src.is_available():
                continue
            if action is not None and action not in src.capabilities:
                continue
            return src
        # 能力不匹配时仍返回第一个可用实例（兼容宽泛 action）
        for entry in entries:
            if entry.source.is_available():
                return entry.source
        return None

    def clear(self) -> None:
        """测试用：清空源实例。"""
        with self._lock:
            self._sources.clear()

    async def fetch(self, source_name: str, action: str, params: Optional[dict[str, Any]] = None) -> Result:
        """
        主路径：限流检查 → Interface.fetch。

        退避期内返回 rate_limited，不调用具体源（避免加剧限流）。
        """
        params = params or {}
        source = self.get(source_name, action)
        if source is None:
            return Result.make_error(
                ErrorInfo.normal(
                    "SOURCE_NOT_FOUND",
                    f"数据源未注册或不可用: {source_name}",
                    retryable=False,
                ),
                source=source_name,
            )

        throttler = rate_limit_registry.get_throttler(source_name)
        if throttler.should_throttle():
            wait = throttler.remaining_throttle_seconds()
            return Result.make_rate_limited(
                ErrorInfo.rate_limited(
                    message=f"{source_name} 处于限流退避期",
                    retry_after=wait,
                ),
                source=source_name,
            )

        t0 = time.perf_counter()
        try:
            result = await fetch_via_breaker_async(source_name, source.fetch, action, params)
        except CircuitBreakerOpenError:
            # 熔断器 OPEN：直接返回错误结果，不调用具体源（避免对熔断中服务施压）
            result = Result.make_error(
                ErrorInfo.normal(
                    "CIRCUIT_OPEN",
                    f"数据源 {source_name} 处于熔断状态，调用已跳过",
                    retryable=True,
                ),
                source=source_name,
            )
        latency = (time.perf_counter() - t0) * 1000.0
        if result.latency_ms <= 0:
            result.latency_ms = latency

        if result.status == ResultStatus.RATE_LIMITED or (result.error and result.error.is_rate_limit_type):
            throttler.on_rate_limit(result.error)
            analyzer = rate_limit_registry.get_analyzer(source_name)
            analyzer.record_rate_limit()
        elif result.is_success:
            throttler.on_success()

        return result


datasource_registry = DataSourceRegistry()
