"""
Quant Agent 熔断器（Circuit Breaker）

对齐 docs/10 §1.4 错误码 3003 (CIRCUIT_BREAKER_OPEN) 和 docs/11 Redis Key `circuit:*`。

状态机：
  CLOSED ──[连续失败 ≥ max_failures]──► OPEN
  OPEN   ──[超过 recovery_timeout 秒]──► HALF_OPEN
  HALF_OPEN ──[探测成功]──► CLOSED
  HALF_OPEN ──[探测失败]──► OPEN

用法（同步 / 异步均支持）：
    from backend.core.circuit_breaker import circuit_breaker, CircuitBreakerOpenError

    # 异步用法
    result = await circuit_breaker.call("futu_api", some_async_func, arg1, arg2)

    # 同步用法（在线程池中调用）
    result = await asyncio.to_thread(circuit_breaker.call_sync, "yfinance_api", some_sync_func, arg1)

    # 装饰器用法
    @circuit_breaker.guard("openai_api")
    async def call_llm(prompt: str):
        ...
"""  # noqa: E501

import asyncio
import functools
import time
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from backend.core.exceptions import CircuitBreakerOpenError
from backend.core.logger import logger
from backend.core.metrics import CIRCUIT_BREAKER_STATE, CIRCUIT_BREAKER_TRANSITIONS

T = TypeVar("T")


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
    """
    异步优先的熔断器管理器。

    - max_failures:     连续失败次数阈值，达到后触发 OPEN（默认 3）
    - recovery_timeout: OPEN 状态持续时间（秒），超时自动转 HALF_OPEN（默认 60）

    RL-03 限流退避解耦:
    - is_rate_limit_error: 可覆盖的过滤钩子，返回 True 时不计入失败计数
    - error_classifier:    call()/call_sync() 可选参数，按异常实例动态判定
    - record_failure():    外部调用者手动记录失败（支持 is_rate_limit 标记）
    """

    def __init__(self, max_failures: int = 3, recovery_timeout: float = 60.0):
        self._max_failures = max_failures
        self._recovery_timeout = recovery_timeout
        self._entries: dict[str, _CircuitEntry] = {}

    def _get_entry(self, service: str) -> _CircuitEntry:
        """获取或懒创建服务对应的熔断条目"""
        if service not in self._entries:
            self._entries[service] = _CircuitEntry(service)
        return self._entries[service]

    def _check_state(self, entry: _CircuitEntry) -> CircuitState:
        """根据当前时间判断是否需要从 OPEN 转为 HALF_OPEN"""
        if entry.state == CircuitState.OPEN:
            elapsed = time.monotonic() - entry.last_failure_ts
            if elapsed >= self._recovery_timeout:
                entry.state = CircuitState.HALF_OPEN
                CIRCUIT_BREAKER_STATE.labels(service=entry.service).set(1)
                CIRCUIT_BREAKER_TRANSITIONS.labels(service=entry.service, from_state="open", to_state="half_open").inc()
                logger.info("⏳ [CircuitBreaker] 熔断器进入半开状态 (等待探测)")
        return entry.state

    def get_state(self, service: str) -> CircuitState:
        """查询指定服务的熔断状态（只读）"""
        entry = self._get_entry(service)
        return self._check_state(entry)

    def _should_skip_failure(self, exc: Exception, error_classifier: Optional[Callable] = None) -> bool:
        """
        判断异常是否应跳过失败计数（限流类错误）。

        判定优先级:
        1. error_classifier 回调（per-call 动态判定，结果具有最终决定权）
        2. is_rate_limit_error 方法（全局/可覆盖钩子，仅当无 classifier 时使用）
        """
        # 1. per-call 动态判定（最终决定权）
        if error_classifier is not None:
            try:
                return bool(error_classifier(exc))
            except Exception:
                pass

        # 2. 全局钩子（仅当无 classifier 时）
        return self.is_rate_limit_error(exc)

    def is_rate_limit_error(self, exc: Exception) -> bool:
        """
        限流错误过滤钩子（可覆盖）。

        默认实现：检查异常是否携带 ErrorCategory 标记。
        子类或外部可覆盖此方法以自定义判定逻辑。

        Returns:
            True → 限流类错误，不计入熔断器失败计数
            False → 普通错误，正常计入
        """
        # 检查异常是否携带 error_category 属性（由 data_source_router 注入）
        category = getattr(exc, "_error_category", None)
        if category is not None:
            from backend.services.datasource import ErrorCategory

            try:
                if isinstance(category, ErrorCategory):
                    return category != ErrorCategory.NORMAL
                # 字符串形式
                return str(category) != "normal"
            except (ImportError, ValueError):
                pass
        return False

    async def call(
        self,
        service: str,
        func: Callable,
        *args: Any,
        error_classifier: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Any:  # noqa: E501
        """
        通过熔断器调用异步函数。

        Args:
            error_classifier: 可选回调，接收异常实例，返回 True 表示限流错误（不计入熔断）

        Raises:
            CircuitBreakerOpenError: 熔断器处于 OPEN 状态时
        """
        entry = self._get_entry(service)

        async with entry.lock:
            state = self._check_state(entry)
            if state == CircuitState.OPEN:
                remaining = self._recovery_timeout - (time.monotonic() - entry.last_failure_ts)  # noqa: E501
                logger.warning(f"🚫 [CircuitBreaker] {service} 熔断中，剩余 {remaining:.0f}s")  # noqa: E501
                raise CircuitBreakerOpenError(
                    msg=f"外部 API [{service}] 熔断中，约 {max(0, int(remaining))}s 后自动恢复",  # noqa: E501
                    service=service,
                )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
        except Exception as exc:
            async with entry.lock:
                # RL-03: 限流类错误不计入熔断器失败计数
                if self._should_skip_failure(exc, error_classifier):
                    logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数: {exc}")
                else:
                    entry.failures += 1
                    entry.last_failure_ts = time.monotonic()
                    if entry.failures >= self._max_failures:
                        prev_state = entry.state.value
                        entry.state = CircuitState.OPEN
                        CIRCUIT_BREAKER_STATE.labels(service=service).set(2)
                        CIRCUIT_BREAKER_TRANSITIONS.labels(
                            service=service, from_state=prev_state, to_state="open"
                        ).inc()
                        logger.error(
                            f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！"  # noqa: E501
                            f"将在 {self._recovery_timeout}s 后自动半开探测。"
                        )
                    else:
                        logger.warning(
                            f"⚠️ [CircuitBreaker] {service} 失败 {entry.failures}/{self._max_failures}: {exc}"  # noqa: E501
                        )
            raise

        # 调用成功 → 重置计数
        async with entry.lock:
            if entry.state == CircuitState.HALF_OPEN:
                logger.info(f"✅ [CircuitBreaker] {service} 半开探测成功，恢复正常！")
            prev_state = entry.state.value
            entry.state = CircuitState.CLOSED
            CIRCUIT_BREAKER_STATE.labels(service=service).set(0)
            if prev_state != "closed":
                CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="closed").inc()
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
        """
        通过熔断器调用同步函数（供 asyncio.to_thread 使用）。

        Args:
            error_classifier: 可选回调，接收异常实例，返回 True 表示限流错误

        注意：此方法使用同步锁（threading.Lock），仅在 to_thread 上下文中使用。
        """

        entry = self._get_entry(service)

        # 同步版状态检查（无锁，简单判断）
        state = self._check_state(entry)
        if state == CircuitState.OPEN:
            remaining = self._recovery_timeout - (time.monotonic() - entry.last_failure_ts)  # noqa: E501
            raise CircuitBreakerOpenError(
                msg=f"外部 API [{service}] 熔断中，约 {max(0, int(remaining))}s 后自动恢复",  # noqa: E501
                service=service,
            )

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            # RL-03: 限流类错误不计入熔断器失败计数
            if self._should_skip_failure(exc, error_classifier):
                logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数: {exc}")
            else:
                entry.failures += 1
                entry.last_failure_ts = time.monotonic()
                if entry.failures >= self._max_failures:
                    entry.state = CircuitState.OPEN
                    logger.error(f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！")  # noqa: E501
            raise

        entry.state = CircuitState.CLOSED
        entry.failures = 0
        entry.last_failure_ts = 0.0
        return result

    def guard(self, service: str):
        """
        装饰器：为异步函数自动包裹熔断保护。

        用法：
            @circuit_breaker.guard("openai_api")
            async def call_llm(prompt: str):
                return await client.chat.completions.create(...)
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.call(service, func, *args, **kwargs)

            return wrapper

        return decorator

    def record_failure(self, service: str, is_rate_limit: bool = False) -> None:
        """
        外部调用者手动记录失败（供 data_source_router 等使用）。

        Args:
            service: 服务名称
            is_rate_limit: 是否为限流类错误（True 时不计入失败计数）
        """
        entry = self._get_entry(service)
        if is_rate_limit:
            logger.debug(f"⚡ [CircuitBreaker] {service} 限流类错误，跳过失败计数")
            return

        entry.failures += 1
        entry.last_failure_ts = time.monotonic()
        if entry.failures >= self._max_failures:
            prev_state = entry.state.value
            entry.state = CircuitState.OPEN
            CIRCUIT_BREAKER_STATE.labels(service=service).set(2)
            CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="open").inc()
            logger.error(
                f"🔴 [CircuitBreaker] {service} 连续失败 {entry.failures} 次，触发熔断！"
                f"将在 {self._recovery_timeout}s 后自动半开探测。"
            )
        else:
            logger.warning(f"⚠️ [CircuitBreaker] {service} 失败 {entry.failures}/{self._max_failures}")

    def record_success(self, service: str) -> None:
        """外部调用者手动记录成功（重置失败计数）"""
        entry = self._get_entry(service)
        if entry.state == CircuitState.HALF_OPEN:
            logger.info(f"✅ [CircuitBreaker] {service} 半开探测成功，恢复正常！")
        prev_state = entry.state.value
        entry.state = CircuitState.CLOSED
        CIRCUIT_BREAKER_STATE.labels(service=service).set(0)
        if prev_state != "closed":
            CIRCUIT_BREAKER_TRANSITIONS.labels(service=service, from_state=prev_state, to_state="closed").inc()
        entry.failures = 0
        entry.last_failure_ts = 0.0

    def reset(self, service: Optional[str] = None) -> None:
        """手动重置熔断器（用于测试或运维恢复）"""
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
        """获取所有服务的熔断状态快照（供 /health 或监控使用）"""
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


# 全局单例（默认：3 次连续失败触发熔断，60 秒后自动半开探测）
circuit_breaker = CircuitBreaker(max_failures=3, recovery_timeout=60.0)

# 导出工厂函数，方便按需创建不同配置实例
def get_circuit_breaker(max_failures: int = 3, recovery_timeout: float = 60.0) -> CircuitBreaker:
    """按需创建新的电路断路器实例（默认返回全局单例配置）"""
    if max_failures == 3 and recovery_timeout == 60.0:
        return circuit_breaker
    return CircuitBreaker(max_failures=max_failures, recovery_timeout=recovery_timeout)
