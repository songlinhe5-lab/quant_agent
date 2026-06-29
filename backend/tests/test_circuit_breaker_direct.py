"""CircuitBreaker 直接单元测试

覆盖状态机: CLOSED → OPEN → HALF_OPEN → CLOSED,
call/call_sync/guard/reset/status_snapshot 全方法。
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    _CircuitEntry,
)
from backend.core.exceptions import CircuitBreakerOpenError


class TestCircuitEntry:
    """_CircuitEntry: 内部状态条目初始化"""

    def test_entry_initial_state_is_closed(self):
        entry = _CircuitEntry("futu_api")
        assert entry.service == "futu_api"
        assert entry.state == CircuitState.CLOSED
        assert entry.failures == 0
        assert entry.last_failure_ts == 0.0
        assert isinstance(entry.lock, asyncio.Lock)


class TestCircuitStateEnum:
    """CircuitState: 枚举值与字符串映射"""

    def test_state_values_are_lowercase_strings(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_state_from_str_lookup(self):
        assert CircuitState("closed") == CircuitState.CLOSED
        assert CircuitState("open") == CircuitState.OPEN


class TestCircuitBreakerGetEntry:
    """_get_entry: 懒创建服务条目"""

    def test_get_entry_creates_new_entry_on_first_call(self):
        cb = CircuitBreaker()
        entry = cb._get_entry("svc_new")
        assert entry.service == "svc_new"
        assert entry.state == CircuitState.CLOSED

    def test_get_entry_returns_same_instance_for_same_service(self):
        cb = CircuitBreaker()
        e1 = cb._get_entry("svc_x")
        e2 = cb._get_entry("svc_x")
        assert e1 is e2

    def test_get_entry_isolates_different_services(self):
        cb = CircuitBreaker()
        e1 = cb._get_entry("svc_a")
        e2 = cb._get_entry("svc_b")
        assert e1 is not e2
        assert e1.service != e2.service


class TestCircuitBreakerCheckState:
    """_check_state: OPEN → HALF_OPEN 自动转换"""

    def test_check_state_closed_returns_closed(self):
        cb = CircuitBreaker()
        entry = cb._get_entry("svc")
        assert cb._check_state(entry) == CircuitState.CLOSED

    def test_check_state_open_within_timeout_stays_open(self):
        cb = CircuitBreaker(recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.last_failure_ts = time.monotonic()  # 刚失败
        assert cb._check_state(entry) == CircuitState.OPEN

    def test_check_state_open_after_timeout_transitions_to_half_open(self):
        cb = CircuitBreaker(recovery_timeout=0.01)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.last_failure_ts = time.monotonic() - 1.0  # 已超时
        with patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE") as m_state, \
             patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS") as m_trans:
            result = cb._check_state(entry)
        assert result == CircuitState.HALF_OPEN
        m_state.labels.assert_called_with(service="svc")
        m_trans.labels.assert_called_with(service="svc", from_state="open", to_state="half_open")


class TestCircuitBreakerGetState:
    """get_state: 只读查询"""

    def test_get_state_returns_current_state_for_new_service(self):
        cb = CircuitBreaker()
        assert cb.get_state("never_used") == CircuitState.CLOSED

    def test_get_state_returns_open_after_failures(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.last_failure_ts = time.monotonic()  # 防止 _check_state 判定超时转 HALF_OPEN
        assert cb.get_state("svc") == CircuitState.OPEN


class TestCircuitBreakerCallAsync:
    """call: 异步函数熔断主流程"""

    @pytest.mark.asyncio
    async def test_call_async_success_returns_result_and_resets_failures(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")
        entry.failures = 2  # 已有失败计数
        func = AsyncMock(return_value="ok")
        result = await cb.call("svc", func, "a", kw=1)
        assert result == "ok"
        func.assert_awaited_once_with("a", kw=1)
        assert entry.state == CircuitState.CLOSED
        assert entry.failures == 0

    @pytest.mark.asyncio
    async def test_call_async_failure_increments_failures_but_not_open(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")
        func = AsyncMock(side_effect=ValueError("boom"))
        with pytest.raises(ValueError):
            await cb.call("svc", func)
        assert entry.failures == 1
        assert entry.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_async_repeated_failures_trigger_open(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")
        func = AsyncMock(side_effect=RuntimeError("down"))
        with patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"), \
             patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"):
            with pytest.raises(RuntimeError):
                await cb.call("svc", func)
            with pytest.raises(RuntimeError):
                await cb.call("svc", func)
        assert entry.failures == 2
        assert entry.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_async_open_state_raises_circuit_breaker_open_error(self):
        cb = CircuitBreaker(max_failures=1, recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.last_failure_ts = time.monotonic()
        func = AsyncMock(return_value="should_not_be_called")
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await cb.call("svc", func)
        assert "svc" in str(exc_info.value)
        func.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_async_half_open_success_restores_closed(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.HALF_OPEN
        func = AsyncMock(return_value="recovered")
        with patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"), \
             patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"):
            result = await cb.call("svc", func)
        assert result == "recovered"
        assert entry.state == CircuitState.CLOSED
        assert entry.failures == 0

    @pytest.mark.asyncio
    async def test_call_async_half_open_failure_returns_to_open(self):
        cb = CircuitBreaker(max_failures=2, recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.HALF_OPEN
        entry.failures = 1  # 预置失败计数,使下一次失败达到 max_failures 阈值触发 OPEN
        func = AsyncMock(side_effect=RuntimeError("still down"))
        with patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"), \
             patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"):
            with pytest.raises(RuntimeError):
                await cb.call("svc", func)
        assert entry.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_async_sync_func_wrapped_without_await(self):
        cb = CircuitBreaker()

        def sync_func(x):
            return x * 2

        result = await cb.call("svc", sync_func, 21)
        assert result == 42


class TestCircuitBreakerCallSync:
    """call_sync: 同步函数熔断"""

    def test_call_sync_success_returns_result(self):
        cb = CircuitBreaker()
        result = cb.call_sync("svc", lambda x: x + 1, 10)
        assert result == 11

    def test_call_sync_failure_increments_failures(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        def boom():
            raise OSError("net")

        with pytest.raises(OSError):
            cb.call_sync("svc", boom)
        assert entry.failures == 1

    def test_call_sync_open_state_raises_error(self):
        cb = CircuitBreaker(recovery_timeout=60.0)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.last_failure_ts = time.monotonic()
        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync("svc", lambda: "nope")

    def test_call_sync_repeated_failures_trigger_open(self):
        cb = CircuitBreaker(max_failures=2)

        def boom():
            raise ValueError("err")

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call_sync("svc", boom)
        assert cb.get_state("svc") == CircuitState.OPEN


class TestCircuitBreakerGuard:
    """guard: 装饰器模式"""

    @pytest.mark.asyncio
    async def test_guard_decorates_async_function_success(self):
        cb = CircuitBreaker()

        @cb.guard("decorated_svc")
        async def fetch():
            return "data"

        result = await fetch()
        assert result == "data"
        assert cb.get_state("decorated_svc") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_guard_propagates_exception_and_tracks_failure(self):
        cb = CircuitBreaker(max_failures=2)

        @cb.guard("decorated_svc")
        async def fetch():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await fetch()
        assert cb._get_entry("decorated_svc").failures == 1


class TestCircuitBreakerReset:
    """reset: 手动重置"""

    def test_reset_single_service_restores_closed(self):
        cb = CircuitBreaker()
        entry = cb._get_entry("svc")
        entry.state = CircuitState.OPEN
        entry.failures = 5
        cb.reset("svc")
        assert entry.state == CircuitState.CLOSED
        assert entry.failures == 0
        assert entry.last_failure_ts == 0.0

    def test_reset_all_services_restores_all_closed(self):
        cb = CircuitBreaker()
        e1 = cb._get_entry("svc_a")
        e2 = cb._get_entry("svc_b")
        e1.state = CircuitState.OPEN
        e2.state = CircuitState.HALF_OPEN
        e1.failures = 3
        e2.failures = 1
        cb.reset()
        assert e1.state == CircuitState.CLOSED
        assert e2.state == CircuitState.CLOSED
        assert e1.failures == 0 and e2.failures == 0


class TestCircuitBreakerStatusSnapshot:
    """status_snapshot: 监控快照"""

    def test_status_snapshot_empty_when_no_services(self):
        cb = CircuitBreaker()
        assert cb.status_snapshot() == {}

    def test_status_snapshot_returns_all_service_states(self):
        cb = CircuitBreaker(max_failures=5, recovery_timeout=30.0)
        e1 = cb._get_entry("svc_a")
        e1.failures = 2
        e2 = cb._get_entry("svc_b")
        e2.state = CircuitState.OPEN
        e2.last_failure_ts = time.monotonic()
        snap = cb.status_snapshot()
        assert set(snap.keys()) == {"svc_a", "svc_b"}
        assert snap["svc_a"]["state"] == "closed"
        assert snap["svc_a"]["failures"] == 2
        assert snap["svc_a"]["max_failures"] == 5
        assert snap["svc_a"]["recovery_timeout"] == 30.0
        assert snap["svc_b"]["state"] == "open"
