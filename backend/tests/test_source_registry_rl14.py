"""
RL-14 · 源注册表冷却信号与告警文案回归

覆盖:
  1. 熔断期 fetch 返回 error_category=circuit_open + retry_after + retryable=False
  2. remaining_cooldown 反映真实剩余冷却（与 recovery_timeout 同源）
  3. 告警文案区分「实例全部不可用」与「能力未声明」
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from backend.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from backend.services.datasource.source_registry import DataSourceRegistry


def _fake_source(name: str, capabilities: list[str], available: bool = True) -> MagicMock:
    src = MagicMock()
    src.name = name
    src.capabilities = capabilities
    src.is_available.return_value = available
    return src


def test_remaining_cooldown_reflects_recovery_timeout():
    """剩余冷却与 recovery_timeout 同源，禁止调用方各自硬编码 60s。"""
    cb = CircuitBreaker(max_failures=1, recovery_timeout=30.0)
    cb.record_failure("svc_rl14")
    assert cb.get_state("svc_rl14") == CircuitState.OPEN

    remaining = cb.remaining_cooldown("svc_rl14")
    assert 0 < remaining <= 30.0

    # CLOSED 状态无冷却
    assert cb.remaining_cooldown("never_failed_svc") == 0.0


@pytest.mark.asyncio
async def test_circuit_open_returns_structured_cooldown_signal(monkeypatch):
    """熔断期必须给出可机读的冷却信号，且不可重试。"""
    reg = DataSourceRegistry()
    reg.register(_fake_source("futu_rl14", ["QUOTE"]))

    async def _boom(*args, **kwargs):
        raise CircuitBreakerOpenError(msg="熔断中", service="futu_rl14")

    monkeypatch.setattr("backend.services.datasource.source_registry.fetch_via_breaker_async", _boom)

    result = await reg.fetch("futu_rl14", "QUOTE", {"ticker": "HK.00772"})
    payload = result.to_dict()

    assert payload["error_category"] == "circuit_open"
    assert "retry_after" in payload
    assert payload["retry_after"] >= 0
    # 冷却期内重试必然再次被拒 → 必须显式标记不可重试
    assert payload["error"]["retryable"] is False
    assert payload["error"]["category"] == "circuit_open"


def test_circuit_open_is_not_rate_limit_type():
    """熔断不得被判为限流类，否则会触发 Throttler 退避（双重惩罚）。"""
    from backend.services.datasource import ErrorCategory, ErrorInfo

    err = ErrorInfo(code="CIRCUIT_OPEN", message="熔断", category=ErrorCategory.CIRCUIT_OPEN)
    assert err.is_rate_limit_type is False
    # 限流类仍须为真（白名单未被误伤）
    assert ErrorInfo.rate_limited().is_rate_limit_type is True


@pytest.mark.asyncio
async def test_circuit_open_does_not_trigger_throttle_suppression(monkeypatch):
    """熔断后源不应进入 Throttler 抑制期。

    回归背景: 熔断 category 曾因「非 NORMAL 即限流」的判定被计入 throttler.on_rate_limit，
    触发 301s 抑制——熔断器 20~60s 冷却结束后，源仍被抑制 5 分钟不可用，
    表现为 QUOTE 长时间取不到数据。
    """
    from backend.services.datasource.registry import rate_limit_registry

    reg = DataSourceRegistry()
    reg.register(_fake_source("futu_nothrottle", ["QUOTE"]))
    throttler = rate_limit_registry.get_throttler("futu_nothrottle")
    throttler.reset()

    async def _boom(*args, **kwargs):
        raise CircuitBreakerOpenError(msg="熔断中", service="futu_nothrottle")

    monkeypatch.setattr("backend.services.datasource.source_registry.fetch_via_breaker_async", _boom)

    try:
        await reg.fetch("futu_nothrottle", "QUOTE", {"ticker": "HK.00772"})
        assert throttler.should_throttle() is False
        assert throttler.remaining_throttle_seconds() == 0.0
    finally:
        throttler.reset()


def test_warns_instance_unavailable_not_capability(caplog):
    """实例全部不可用：不得再报"未声明能力"（此前二者共用一条文案，自相矛盾）。"""
    reg = DataSourceRegistry()
    reg.register(_fake_source("futu", ["QUOTE"], available=False))

    with caplog.at_level(logging.WARNING, logger="backend.services.datasource.source_registry"):
        assert reg.get("futu", "QUOTE") is None

    assert "全部不可用" in caplog.text
    assert "未声明能力" not in caplog.text


def test_warns_capability_not_declared_when_available(caplog):
    """实例可用但能力不匹配：报"未声明能力"。"""
    reg = DataSourceRegistry()
    reg.register(_fake_source("futu", ["HISTORY"], available=True))

    with caplog.at_level(logging.WARNING, logger="backend.services.datasource.source_registry"):
        assert reg.get("futu", "QUOTE") is None

    assert "未声明能力" in caplog.text
    assert "全部不可用" not in caplog.text
