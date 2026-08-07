"""Quant Agent 熔断器（Circuit Breaker）

复制自 backend.core.circuit_breaker，物理解耦到 data_subservice._internal。
- exceptions / logger 改为相对 import（来自 _internal）
- metrics 依赖降级为 no-op 桩：子服务为独立数据源节点，不上报 Prometheus 主集群，
  熔断状态变化仅打日志，不写 gauge。
- ErrorCategory 懒加载逻辑保留 try/except ImportError，子服务无此枚举时走字符串 fallback。
"""

import asyncio
import functools
import os
import time
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from data_subservice._internal.exceptions import CircuitBreakerOpenError
from data_subservice._internal.logger import logger


# ── metrics 降级桩（no-op）──
# 子服务作为边缘数据源节点，不接入主集群 Prometheus，
# 用无操作的 gauge/counter 占位，保证原调用点语义不变。
class _NoOpMetric:
    def labels(self, *args, **kwargs) -> "_NoOpMetric":
        return self

    def set(self, *args, **kwargs) -> None:
        return None

    def inc(self, *args, **kwargs) -> None:
        return None


_CIRCUIT_BREAKER_STATE = _NoOpMetric()
_CIRCUIT_BREAKER_TRANSITIONS = _NoOpMetric()

T = TypeVar("T")

# 熔断参数配置（env 优先，禁止硬编码 60s）
_CIRCUIT_BREAKER_MAX_FAILURES = int(os.getenv("CIRCUIT_BREAKER_MAX_FAILURES", "3"))
_CIRCUIT_BREAKER_COOLDOWN_S = float(os.getenv("CIRCUIT_BREAKER_COOLDOWN_S", "60"))


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _CircuitEntry:
    """单个服务的熔断状态条目"""

    __slots__ = ("state", "failures", "last_failure_ts", "lock", "service")

    def __init__(self, service: str):
        self.service: str = service
        self.state: CircuitState = CircuitState.CLOSED
        self.failures: int = 0
        self.last_failure_ts: float = 0.0
        self.lock: asyncio.Lock = asyncio.Lock()


class CircuitBreaker:
    """异步优先的熔断器管理器"""

    def __init__(self, max_failures: int = 3, recovery_timeout: float = 60.0):
        self._max_failures = max_failures
        self._recovery_timeout = recovery_timeout
        self._entries: dict[str, _CircuitEntry] = {}

    def _get_entry(self, service: str) -> _CircuitEntry:
        if service not in self._entries:
            self._entries[service] = _CircuitEntry(service)
        return self._entries[service]

    def _check_state(self, entry: _CircuitEntry) -> CircuitState:
        if entry.state == CircuitState.OPEN:
            elapsed = time.monotonic() - entry.last_failure_ts
            if elapsed >= self._recovery_timeout:
                entry.state = CircuitState.HALF_OPEN
                _CIRCUIT_BREAKER_STATE.labels(service=entry.service).set(1)
                _CIRCUIT_BREAKER_TRANSITIONS.labels(
                    service=entry.service, from_state="open", to_state="half_open"
                ).inc()
                logger.info("⏳ [CircuitBreaker] 熔断器进入半开状态 (等待探测)")
        return entry.state

    def get_state(self, service: str) -> CircuitState:
        entry = self._get_entry(service)
        return self._check_state(entry)

    def _should_skip_failure(self, exc: Exception, error_classifier: Optional[Callable] = None) -> bool:
        if error_classifier is not None:
            try:
                return bool(error_classifier(exc))
            except Exception:
                pass
        return self.is_rate_limit_error(exc)

    def is_rate_limit_error(self, exc: Exception) -> bool:
        category = getattr(exc, "_error_category", None)
        if category is not None:
            try:
                if isinstance(category, str):
                    return str(category) != "normal"
            except (ValueError, TypeError):
                pass
        return False

    async def call(
        self,
        service: str,
        func: Callable,
        *args: Any,
        error_classifier: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Any:
        entry = self._get_entry(service)

        async with entry.lock:
            state = self._check_state(entry)
            if state == CircuitState.OPEN:
                remaining = self._recovery_timeout - (time.monotonic() - entry.last_failure_ts)
                logger.warning(f"🚫 [CircuitBreaker] {service} 熔断中，剩余 {remaining:.0f}s")
                raise CircuitBreakerOpenError(
                    msg=f"外部 API [{service}] 熔断中，约 {max(0, int(remaining))}s 后自动恢复",
                    service=service,
                )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
        except Exception as exc:
            async with entry.lock:
                if self._should_skip_failure(exc, error_classifier):
                    logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数: {exc}")
                else:
                    entry.failures += 1
                    entry.last_failure_ts = time.monotonic()
                    if entry.failures >= self._max_failures:
                        prev_state = entry.state.value
                        entry.state = CircuitState.OPEN
                        _CIRCUIT_BREAKER_STATE.labels(service=service).set(2)
                        _CIRCUIT_BREAKER_TRANSITIONS.labels(
                            service=service, from_state=prev_state, to_state="open"
                        ).inc()
                        logger.error(
                            f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！"
                            f"将在 {self._recovery_timeout}s 后自动半开探测。"
                        )
                    else:
                        logger.warning(
                            f"⚠️ [CircuitBreaker] {service} 失败 {entry.failures}/{self._max_failures}: {exc}"
                        )
            raise

        async with entry.lock:
            if entry.state == CircuitState.HALF_OPEN:
                logger.info(f"✅ [CircuitBreaker] {service} 半开探测成功，恢复正常！")
            prev_state = entry.state.value
            entry.state = CircuitState.CLOSED
            _CIRCUIT_BREAKER_STATE.labels(service=service).set(0)
            if prev_state != "closed":
                _CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="closed").inc()
            entry.failures = 0
            entry.last_failure_ts = 0.0

        return result

    def call_sync(
        self,
        service: str,
        func: Callable,
        *args: Any,
        error_classifier: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Any:
        entry = self._get_entry(service)

        state = self._check_state(entry)
        if state == CircuitState.OPEN:
            remaining = self._recovery_timeout - (time.monotonic() - entry.last_failure_ts)
            raise CircuitBreakerOpenError(
                msg=f"外部 API [{service}] 熔断中，约 {max(0, int(remaining))}s 后自动恢复",
                service=service,
            )

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            if self._should_skip_failure(exc, error_classifier):
                logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数: {exc}")
            else:
                entry.failures += 1
                entry.last_failure_ts = time.monotonic()
                if entry.failures >= self._max_failures:
                    entry.state = CircuitState.OPEN
                    logger.error(f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！")
            raise

        entry.state = CircuitState.CLOSED
        entry.failures = 0
        entry.last_failure_ts = 0.0
        return result

    def guard(self, service: str):
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.call(service, func, *args, **kwargs)

            return wrapper

        return decorator

    def record_failure(self, service: str, is_rate_limit: bool = False) -> None:
        entry = self._get_entry(service)
        if is_rate_limit:
            logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数")
            return

        entry.failures += 1
        entry.last_failure_ts = time.monotonic()
        if entry.failures >= self._max_failures:
            prev_state = entry.state.value
            entry.state = CircuitState.OPEN
            _CIRCUIT_BREAKER_STATE.labels(service=service).set(2)
            _CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="open").inc()
            logger.error(
                f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！"
                f"将在 {self._recovery_timeout}s 后自动半开探测。"
            )
        else:
            logger.warning(f"⚠️ [CircuitBreaker] {service} 失败 {entry.failures}/{self._max_failures}")

    def record_success(self, service: str) -> None:
        entry = self._get_entry(service)
        if entry.state == CircuitState.HALF_OPEN:
            logger.info(f"✅ [CircuitBreaker] {service} 半开探测成功，恢复正常！")
        prev_state = entry.state.value
        entry.state = CircuitState.CLOSED
        _CIRCUIT_BREAKER_STATE.labels(service=service).set(0)
        if prev_state != "closed":
            _CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="closed").inc()
        entry.failures = 0
        entry.last_failure_ts = 0.0

    def reset(self, service: Optional[str] = None) -> None:
        if service:
            entry = self._get_entry(service)
            entry.state = CircuitState.CLOSED
            entry.failures = 0
            entry.last_failure_ts = 0.0
            logger.info(f"🔄 [CircuitBreaker] {service} 已手动重置为 CLOSED")
        else:
            for name, entry in self._entries.items():
                entry.state = CircuitState.CLOSED
                entry.failures = 0
                entry.last_failure_ts = 0.0
            logger.info("🔄 [CircuitBreaker] 所有服务熔断器已重置")

    def status_snapshot(self) -> dict[str, dict]:
        result = {}
        for service, entry in self._entries.items():
            state = self._check_state(entry)
            result[service] = {
                "state": state.value,
                "failures": entry.failures,
                "max_failures": self._max_failures,
                "recovery_timeout": self._recovery_timeout,
            }
        return result


# 全局单例（冷却时间由 env CIRCUIT_BREAKER_COOLDOWN_S 配置，禁止硬编码 60s）
circuit_breaker = CircuitBreaker(
    max_failures=_CIRCUIT_BREAKER_MAX_FAILURES,
    recovery_timeout=_CIRCUIT_BREAKER_COOLDOWN_S,
)


def get_circuit_breaker(
    max_failures: int = _CIRCUIT_BREAKER_MAX_FAILURES,
    recovery_timeout: float = _CIRCUIT_BREAKER_COOLDOWN_S,
) -> CircuitBreaker:
    if max_failures == _CIRCUIT_BREAKER_MAX_FAILURES and recovery_timeout == _CIRCUIT_BREAKER_COOLDOWN_S:
        return circuit_breaker
    return CircuitBreaker(max_failures=max_failures, recovery_timeout=recovery_timeout)


def get_cooldown_seconds() -> float:
    return _CIRCUIT_BREAKER_COOLDOWN_S
