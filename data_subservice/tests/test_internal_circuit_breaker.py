"""CircuitBreaker 单元测试 (零 backend 依赖, 纯逻辑)"""

import asyncio

import pytest

from data_subservice._internal.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    circuit_breaker,
    get_circuit_breaker,
    get_cooldown_seconds,
)
from data_subservice._internal.exceptions import CircuitBreakerOpenError


class TestCircuitBreakerCall:
    @pytest.mark.asyncio
    async def test_success_reset_state(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)
        assert await cb.call("svc", lambda: "ok") == "ok"
        assert cb.get_state("svc") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_increments_then_breaks(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)

        def boom():
            raise ValueError("x")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call("svc", boom)
        assert cb.get_state("svc") == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_state_raises_circuit_open_error(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            await cb.call("svc", lambda: (_ for _ in ()).throw(ValueError("e")))
        # now open
        with pytest.raises(CircuitBreakerOpenError) as exc:
            await cb.call("svc", lambda: "ok")
        assert exc.value.data["service"] == "svc"

    @pytest.mark.asyncio
    async def test_async_func_called_via_await(self):
        cb = CircuitBreaker(max_failures=3, recovery_timeout=60)

        async def af():
            return "async-ok"

        assert await cb.call("svc", af) == "async-ok"

    @pytest.mark.asyncio
    async def test_half_open_recovers_after_timeout(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=0.05)
        with pytest.raises(ValueError):
            await cb.call("svc", lambda: (_ for _ in ()).throw(ValueError("e")))
        assert cb.get_state("svc") == CircuitState.OPEN
        await asyncio.sleep(0.1)
        # half-open -> success resets
        assert await cb.call("svc", lambda: "ok") == "ok"
        assert cb.get_state("svc") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_rate_limit_error_skips_failure_count(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)

        class RateLimitErr(Exception):
            _error_category = "rate_limit"

        def rl():
            raise RateLimitErr("rl")

        with pytest.raises(RateLimitErr):
            await cb.call("svc", rl)
        # not broken because rate-limit error skipped
        assert cb.get_state("svc") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_error_classifier_skips_failure(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)

        def boom():
            raise ValueError("v")

        with pytest.raises(ValueError):
            await cb.call("svc", boom, error_classifier=lambda e: isinstance(e, ValueError))
        assert cb.get_state("svc") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_error_classifier_raises_is_ignored(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)

        def boom():
            raise ValueError("v")

        with pytest.raises(ValueError):
            await cb.call("svc", boom, error_classifier=lambda e: 1 / 0)
        # classifier raised -> treated as not skip -> failure counted
        assert cb.get_state("svc") == CircuitState.OPEN


class TestCircuitBreakerSync:
    def test_call_sync_success(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)
        assert cb.call_sync("svc", lambda: 7) == 7
        assert cb.get_state("svc") == CircuitState.CLOSED

    def test_call_sync_open_raises(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            cb.call_sync("svc", lambda: (_ for _ in ()).throw(ValueError("e")))
        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync("svc", lambda: 1)

    def test_call_sync_rate_limit_skips(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)

        class RL(Exception):
            _error_category = "rate_limit"

        with pytest.raises(RL):
            cb.call_sync("svc", lambda: (_ for _ in ()).throw(RL("r")))
        assert cb.get_state("svc") == CircuitState.CLOSED


class TestCircuitBreakerGuard:
    @pytest.mark.asyncio
    async def test_guard_decorator(self):
        cb = CircuitBreaker(max_failures=3, recovery_timeout=60)

        @cb.guard("guarded")
        async def op(x):
            return x * 2

        assert await op(5) == 10
        assert cb.get_state("guarded") == CircuitState.CLOSED


class TestCircuitBreakerRecord:
    def test_record_failure_breaks_after_max(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)
        cb.record_failure("svc")
        assert cb.get_state("svc") == CircuitState.CLOSED
        cb.record_failure("svc")
        assert cb.get_state("svc") == CircuitState.OPEN

    def test_record_failure_rate_limit_skips(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        cb.record_failure("svc", is_rate_limit=True)
        assert cb.get_state("svc") == CircuitState.CLOSED

    def test_record_success_resets(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        cb.record_failure("svc")
        assert cb.get_state("svc") == CircuitState.OPEN
        cb.record_success("svc")
        assert cb.get_state("svc") == CircuitState.CLOSED

    def test_reset_single(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        cb.record_failure("a")
        cb.record_failure("b")
        cb.reset("a")
        assert cb.get_state("a") == CircuitState.CLOSED
        assert cb.get_state("b") == CircuitState.OPEN

    def test_reset_all(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60)
        cb.record_failure("a")
        cb.record_failure("b")
        cb.reset()
        assert cb.get_state("a") == CircuitState.CLOSED
        assert cb.get_state("b") == CircuitState.CLOSED

    def test_status_snapshot(self):
        cb = CircuitBreaker(max_failures=3, recovery_timeout=42)
        cb.record_failure("a")
        snap = cb.status_snapshot()
        assert snap["a"]["state"] == "closed"
        assert snap["a"]["failures"] == 1
        assert snap["a"]["max_failures"] == 3
        assert snap["a"]["recovery_timeout"] == 42


class TestGlobals:
    def test_singleton_identity(self):
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2 is circuit_breaker

    def test_custom_returns_new(self):
        cb = get_circuit_breaker(max_failures=99, recovery_timeout=1.0)
        assert cb is not circuit_breaker
        assert cb._max_failures == 99

    def test_get_cooldown_seconds(self):
        assert isinstance(get_cooldown_seconds(), float)
