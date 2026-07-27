"""
ARCH-02 验证：统一熔断器接入各数据源 Adapter 的 fetch 主路径。

覆盖：
- 冷却时间 env 配置（CIRCUIT_BREAKER_COOLDOWN_S）接入单例
- 同步主路径 fetch_via_breaker_sync：成功/失败/熔断 OPEN 跳过/异常传播
- 异步主路径 fetch_via_breaker_async：成功/熔断 OPEN 抛异常
"""

import asyncio

import pytest

from backend.adapters.ports.data_source_port import DataSourceResult
from backend.core import circuit_breaker as cb_mod
from backend.core.circuit_breaker import CircuitState, circuit_breaker
from backend.core.circuit_breaker_integration import (
    fetch_via_breaker_async,
    fetch_via_breaker_sync,
)
from backend.core.exceptions import CircuitBreakerOpenError


@pytest.fixture(autouse=True)
def _reset_breaker():
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


def _success_fetch(action, params):
    return DataSourceResult.success({"ok": True}, source="test")


def _error_fetch(action, params):
    return DataSourceResult.error("boom")


# ── env 配置 ────────────────────────────────────────────────
def test_cooldown_derived_from_env_constant():
    # CIRCUIT_BREAKER_COOLDOWN_S 在 import 时读入模块级常量，并与单例 recovery_timeout 对齐
    assert cb_mod.get_cooldown_seconds() > 0
    assert cb_mod.get_cooldown_seconds() == circuit_breaker._recovery_timeout


# ── 同步主路径 ──────────────────────────────────────────────
def test_sync_success_records_success():
    res = fetch_via_breaker_sync("svc_a", _success_fetch, "quote", {})
    assert res.is_success()
    assert circuit_breaker.get_state("svc_a") == CircuitState.CLOSED
    assert circuit_breaker._entries["svc_a"].failures == 0


def test_sync_error_records_failure():
    res = fetch_via_breaker_sync("svc_b", _error_fetch, "quote", {})
    assert not res.is_success()
    assert circuit_breaker._entries["svc_b"].failures == 1


def test_sync_open_state_skips_real_call():
    calls = {"n": 0}

    def _boom(action, params):
        calls["n"] += 1
        return DataSourceResult.success({})

    for _ in range(cb_mod._CIRCUIT_BREAKER_MAX_FAILURES):
        fetch_via_breaker_sync("svc_c", _error_fetch, "quote", {})
    assert circuit_breaker.get_state("svc_c") == CircuitState.OPEN
    res = fetch_via_breaker_sync("svc_c", _boom, "quote", {})
    assert not res.is_success()
    assert calls["n"] == 0  # 熔断中不应真正调用下游


def test_sync_exception_propagates_and_records_failure():
    def _raise(action, params):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        fetch_via_breaker_sync("svc_d", _raise, "quote", {})
    assert circuit_breaker._entries["svc_d"].failures == 1


# ── 异步主路径 ──────────────────────────────────────────────
async def _async_success(action, params):
    return DataSourceResult.success({"ok": True}, source="test")


async def _async_error(action, params):
    return DataSourceResult.error("boom")


def test_async_success_records_success():
    res = asyncio.run(fetch_via_breaker_async("asvc2", _async_success, "quote", {}))
    assert res.is_success()
    assert circuit_breaker.get_state("asvc2") == CircuitState.CLOSED


def test_async_open_raises_circuit_breaker_open():
    for _ in range(cb_mod._CIRCUIT_BREAKER_MAX_FAILURES):
        asyncio.run(fetch_via_breaker_async("asvc", _async_error, "quote", {}))
    assert circuit_breaker.get_state("asvc") == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        asyncio.run(fetch_via_breaker_async("asvc", _async_success, "quote", {}))
