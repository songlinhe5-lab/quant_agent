"""
DataSourceRegistry — 源实例注册表（docs/14 §5.1 · BE-ARCH-04）

持有 DataSourceInterface 实例，提供 register / get / fetch。
限流状态走 RateLimitRegistry，禁止与本表职责混淆。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.core.circuit_breaker import CircuitBreakerOpenError
from backend.core.circuit_breaker_integration import fetch_via_breaker_async
from backend.core.metrics import (
    DATASOURCE_AVAILABILITY,
    DATASOURCE_ERRORS,
    DATASOURCE_LATENCY,
    DATASOURCE_RATE_LIMITS,
)

from . import ErrorInfo, Result, ResultStatus
from .call_metrics_store import call_metrics
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
        """按名称取首个可用实例；可选按 capability 过滤（case-insensitive）。

        能力严格匹配原则（BE-ARCH-07i）：
        当传入 ``action`` 且与实例 capabilities 不匹配时，**不再静默回退到首个
        可用实例**——否则"按 action 选源"语义失效，只能靠 fetch 失败逐源重试兜底。
        不匹配时返回 ``None``，由 ``fetch`` 生成明确的 ``SOURCE_NOT_FOUND`` 错误。
        若需兼容历史宽泛 action，可设环境变量 ``DATASOURCE_LOOSE_CAPABILITY=1``
        恢复旧回退行为（仅过渡期使用，不应长期开启）。
        """
        loose = os.environ.get("DATASOURCE_LOOSE_CAPABILITY", "0") == "1"
        with self._lock:
            entries = list(self._sources.get(source_name, []))
        action_upper = action.upper() if action else None
        for entry in entries:
            src = entry.source
            if not src.is_available():
                continue
            if action_upper is not None and action_upper not in [c.upper() for c in src.capabilities]:
                continue
            return src
        # 能力不匹配：显式告警，不再静默回退（除非显式开启 loose 兼容模式）
        if action_upper is not None and entries:
            declared = sorted({c.upper() for e in entries for c in e.source.capabilities})
            logger.warning(
                "[Registry] 源 %s 未声明能力 %s（已声明: %s），按 action 选源失败，返回 None（不再静默回退首实例）",
                source_name,
                action_upper,
                declared,
            )
            if loose:
                for entry in entries:
                    if entry.source.is_available():
                        logger.warning("[Registry] 已按 DATASOURCE_LOOSE_CAPABILITY 恢复回退到首实例")
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
            # 源已在内部自行记录 throttler 时（如 FinnhubService，Result.self_recorded=True），
            # 此处跳过 throttler 重复记录，但仍记录 analyzer 计数（含类别拆分）。
            if not getattr(result, "self_recorded", False):
                throttler.on_rate_limit(result.error)
            analyzer = rate_limit_registry.get_analyzer(source_name)
            analyzer.record_rate_limit(category=(result.error.category if result.error else None))
            await call_metrics.record_business(
                source_name,
                "rate_limited",
                category=(result.error.category.value if result.error else None),
                latency_ms=result.latency_ms,  # ← 记录延迟
            )
            # Phase 3: Prometheus 指标导出
            DATASOURCE_LATENCY.labels(source=source_name, action=action).observe(result.latency_ms)
            DATASOURCE_RATE_LIMITS.labels(
                source=source_name,
                category=result.error.category.value if result.error else "unknown",
            ).inc()
            DATASOURCE_ERRORS.labels(source=source_name, error_type="rate_limit").inc()
        elif result.is_success:
            if not getattr(result, "self_recorded", False):
                throttler.on_success()
            analyzer = rate_limit_registry.get_analyzer(source_name)
            analyzer.record_success(latency_ms=result.latency_ms)
            await call_metrics.record_business(
                source_name,
                "success",
                latency_ms=result.latency_ms,  # ← 记录延迟
            )
            # Phase 3: Prometheus 指标导出
            DATASOURCE_LATENCY.labels(source=source_name, action=action).observe(result.latency_ms)
            DATASOURCE_AVAILABILITY.labels(source=source_name).set(1)  # 标记为可用
        else:
            # 非限流错误: 计入健康统计但不触达退避恢复 (COMM-01)
            if not getattr(result, "self_recorded", False):
                throttler.on_error()
            analyzer = rate_limit_registry.get_analyzer(source_name)
            analyzer.record_error(latency_ms=result.latency_ms)
            await call_metrics.record_business(
                source_name,
                "error",
                latency_ms=result.latency_ms,  # ← 记录延迟
            )
            # Phase 3: Prometheus 指标导出
            DATASOURCE_LATENCY.labels(source=source_name, action=action).observe(result.latency_ms)
            error_type = "circuit_open" if "CIRCUIT_OPEN" in str(result.error) else "network"
            DATASOURCE_ERRORS.labels(source=source_name, error_type=error_type).inc()
            DATASOURCE_AVAILABILITY.labels(source=source_name).set(0)  # 标记为不可用

        return result


datasource_registry = DataSourceRegistry()
