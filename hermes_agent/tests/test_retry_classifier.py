"""AGENT-18 · 重试分类与退避单元测试"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermes_agent.retry_classifier import (
    CONTENT_FILTER_ERROR_CODE,
    ErrorCategory,
    ExponentialBackoff,
    RetryBudget,
    RetryConfig,
    RetryDecision,
    classify_llm_error,
    should_retry_with_backoff,
)


class FakeResp:
    def __init__(self, status_code=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeErr(Exception):
    def __init__(self, msg="", status_code=None, headers=None, retry_after=None):
        super().__init__(msg)
        self.status_code = status_code
        if headers is not None or retry_after is not None:
            h = headers or {}
            if retry_after is not None:
                h.setdefault("Retry-After", str(retry_after))
            self.response = FakeResp(status_code, h)


# ── 分类测试 ──────────────────────────────────────────────────────────────────


def test_network_timeout():
    e = Exception("ReadTimeout: The read operation timed out")
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.NETWORK
    assert info.is_retryable


def test_network_connection_reset():
    e = Exception("ConnectionResetError: [Errno 54] Connection reset by peer")
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.NETWORK
    assert info.is_retryable


def test_rate_limit_429():
    e = FakeErr("Rate limit exceeded", status_code=429, retry_after=2.5)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.RATE_LIMIT
    assert info.is_retryable
    assert info.retry_after == 2.5


def test_rate_limit_429_no_retry_after():
    e = FakeErr("Too many requests", status_code=429)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.RATE_LIMIT
    assert info.is_retryable
    # 无 Retry-After -> 退避算法兜底
    assert info.retry_after is None


def test_server_error_502():
    e = FakeErr("Bad Gateway", status_code=502)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.SERVER_ERROR
    assert info.is_retryable


def test_bad_request_400():
    e = FakeErr("Invalid parameter: temperature", status_code=400)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.BAD_REQUEST
    assert not info.is_retryable


def test_other_4xx_non_retryable():
    e = FakeErr("Not Found", status_code=404)
    info = classify_llm_error(e, status_code=404)
    assert info.category == ErrorCategory.BAD_REQUEST
    assert not info.is_retryable


def test_content_filter_by_status():
    e = FakeErr("content filtered", status_code=400)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.CONTENT_FILTER
    assert not info.is_retryable
    assert info.error_code == CONTENT_FILTER_ERROR_CODE


def test_content_filter_by_message():
    e = Exception("Your prompt was flagged by our content policy")
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.CONTENT_FILTER
    assert info.error_code == CONTENT_FILTER_ERROR_CODE


def test_auth_error():
    e = FakeErr("Invalid API key provided", status_code=401)
    info = classify_llm_error(e)
    assert info.category == ErrorCategory.AUTH
    assert not info.is_retryable


# ── 退避测试 ──────────────────────────────────────────────────────────────────


def test_exponential_backoff_growth():
    b = ExponentialBackoff(base_delay=1.0, max_delay=100.0, exponent=2.0)
    d0 = b.next_attempt_delay()
    d1 = b.next_attempt_delay()
    d2 = b.next_attempt_delay()
    # 指数增长（考虑抖动后仍然近似）
    assert d1 > d0
    assert d2 > d1


def test_exponential_backoff_cap():
    b = ExponentialBackoff(base_delay=1.0, max_delay=5.0, exponent=2.0)
    for _ in range(10):
        d = b.next_attempt_delay()
        assert d <= 5.0


def test_backoff_jitter_bounds():
    b = ExponentialBackoff(base_delay=2.0, max_delay=100.0, exponent=2.0)
    for attempt in range(5):
        raw = b.get_delay(attempt)
        expected_cap = min(2.0 * (2.0**attempt), 100.0)
        # full-jitter: 延迟在 [0, capped] 区间内
        assert 0 <= raw <= expected_cap + 1e-6


def test_backoff_min_delay_lower_bound():
    # AGENT-18 补丁：full-jitter 加最小间隔硬下限，消除 <min_delay 的无效重试
    b = ExponentialBackoff(base_delay=2.0, max_delay=100.0, exponent=2.0, min_delay=0.5)
    for attempt in range(5):
        raw = b.get_delay(attempt)
        expected_cap = min(2.0 * (2.0**attempt), 100.0)
        assert 0.5 <= raw <= expected_cap + 1e-6


def test_backoff_min_delay_capped_degrade():
    # capped 低于 min_delay 时退化为固定 capped（不超过上限）
    b = ExponentialBackoff(base_delay=0.2, max_delay=0.3, exponent=1.0, min_delay=0.5)
    for _ in range(20):
        d = b.next_attempt_delay()
        assert d <= 0.3


# ── 预算测试 ──────────────────────────────────────────────────────────────────


def test_retry_budget_exhaustion():
    cfg = RetryConfig(max_attempts=2, base_delay=0.01, max_delay=0.1)
    budget = RetryBudget(cfg)
    budget.start()
    e = FakeErr("timeout", status_code=500)
    info = classify_llm_error(e)
    assert budget.can_retry(info)[0] is True
    budget.record_retry(info, 0.0, RetryDecision.RETRY_BACKOFF, "x")
    budget.record_retry(info, 0.0, RetryDecision.RETRY_BACKOFF, "x")
    # 已用 2 次，max_attempts=2 -> 不可重试
    assert budget.can_retry(info)[0] is False
    assert budget.attempt_budget_remaining == 0


def test_retry_budget_non_retryable():
    cfg = RetryConfig(max_attempts=3)
    budget = RetryBudget(cfg)
    budget.start()
    info = classify_llm_error(FakeErr("bad", status_code=400))
    can, reason = budget.can_retry(info)
    assert can is False
    assert "non-retryable" in reason


# ── 便捷函数测试 ──────────────────────────────────────────────────────────────


def test_should_retry_429_uses_retry_after():
    should, delay, reason = should_retry_with_backoff(FakeErr("rl", status_code=429, retry_after=3.0), status_code=429)
    assert should is True
    assert delay == 3.0
    assert "Retry-After" in reason


def test_should_retry_not_for_400():
    should, delay, _ = should_retry_with_backoff(FakeErr("bad", status_code=400), status_code=400)
    assert should is False
    assert delay is None


def test_should_retry_backoff_5xx():
    should, delay, _ = should_retry_with_backoff(FakeErr("server", status_code=503), status_code=503)
    assert should is True
    assert delay is not None and delay >= 0


# ── 配置从环境变量 ───────────────────────────────────────────────────────────


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AGENT18_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("AGENT18_BASE_DELAY", "0.5")
    monkeypatch.setenv("AGENT18_MAX_DELAY", "10.0")
    monkeypatch.setenv("AGENT18_MIN_DELAY", "0.3")
    cfg = RetryConfig.from_env()
    assert cfg.max_attempts == 5
    assert cfg.base_delay == 0.5
    assert cfg.max_delay == 10.0
    assert cfg.min_delay == 0.3


def test_config_from_env_invalid_fallback(monkeypatch):
    monkeypatch.setenv("AGENT18_MAX_ATTEMPTS", "not-an-int")
    cfg = RetryConfig.from_env()
    assert cfg.max_attempts == RetryConfig.max_attempts  # 回退默认值
