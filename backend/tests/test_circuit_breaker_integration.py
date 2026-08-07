"""
ARCH-02 验证：统一熔断器接入数据源 fetch 异步主路径。

覆盖：
- 冷却时间 env 配置（CIRCUIT_BREAKER_COOLDOWN_S）接入单例
- 异步主路径 fetch_via_breaker_async：成功/失败/熔断 OPEN 抛异常

注：同步路径（fetch_via_breaker_sync / DataSourceResult）已随旧 adapters 树废弃并删除（2026-08-07）。
"""

import asyncio

import pytest

from backend.core import circuit_breaker as cb_mod
from backend.core.circuit_breaker import CircuitState, circuit_breaker
from backend.core.circuit_breaker_integration import fetch_via_breaker_async
from backend.core.exceptions import CircuitBreakerOpenError
from backend.services.datasource import ErrorInfo, Result, ResultStatus


@pytest.fixture(autouse=True)
def _reset_breaker():
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


async def _async_success(action, params):
    return Result(status=ResultStatus.SUCCESS, data={"ok": True}, source="test")


async def _async_error(action, params):
    return Result(status=ResultStatus.ERROR, error=ErrorInfo(code="TEST", message="boom"))


# ── env 配置 ────────────────────────────────────────────────
def test_cooldown_derived_from_env_constant():
    # CIRCUIT_BREAKER_COOLDOWN_S 在 import 时读入模块级常量，并与单例 recovery_timeout 对齐
    assert cb_mod.get_cooldown_seconds() > 0
    assert cb_mod.get_cooldown_seconds() == circuit_breaker._recovery_timeout


# ── 异步主路径 ──────────────────────────────────────────────
def test_async_success_records_success():
    res = asyncio.run(fetch_via_breaker_async("asvc2", _async_success, "quote", {}))
    assert res.is_success
    assert circuit_breaker.get_state("asvc2") == CircuitState.CLOSED


def test_async_error_records_failure():
    res = asyncio.run(fetch_via_breaker_async("asvc3", _async_error, "quote", {}))
    assert not res.is_success
    assert circuit_breaker._entries["asvc3"].failures == 1


def test_async_open_raises_circuit_breaker_open():
    for _ in range(cb_mod._CIRCUIT_BREAKER_MAX_FAILURES):
        asyncio.run(fetch_via_breaker_async("asvc", _async_error, "quote", {}))
    assert circuit_breaker.get_state("asvc") == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        asyncio.run(fetch_via_breaker_async("asvc", _async_success, "quote", {}))


def test_async_exception_propagates_and_records_failure():
    async def _raise(action, params):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        asyncio.run(fetch_via_breaker_async("asvc4", _raise, "quote", {}))
    assert circuit_breaker._entries["asvc4"].failures == 1
