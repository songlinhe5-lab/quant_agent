"""
RL-02: RateLimitThrottler 退避引擎单测
======================================

验证:
- 四种退避策略的计算曲线 (none / linear / exponential / adaptive)
- 退避期内 should_throttle() 返回 True
- 退避恢复后逐步降速
- 服务端 Retry-After 优先采纳
- 抖动防雷群效应
- 并发安全性
- get_status() 返回正确的 RateLimitStatus
"""

import threading
import time
from unittest.mock import patch

import pytest

from backend.services.datasource import (
    ErrorInfo,
    RateLimitInfo,
    RateLimitStatus,
)
from backend.services.datasource.throttler import BackoffStrategy, RateLimitThrottler


# ─────────────────────────────────────────
#  BackoffStrategy 枚举
# ─────────────────────────────────────────

class TestBackoffStrategy:
    def test_enum_values(self):
        assert BackoffStrategy.NONE == "none"
        assert BackoffStrategy.LINEAR == "linear"
        assert BackoffStrategy.EXPONENTIAL == "exponential"
        assert BackoffStrategy.ADAPTIVE == "adaptive"

    def test_enum_from_string(self):
        assert BackoffStrategy("none") == BackoffStrategy.NONE
        assert BackoffStrategy("adaptive") == BackoffStrategy.ADAPTIVE


# ─────────────────────────────────────────
#  初始化与配置
# ─────────────────────────────────────────

class TestThrottlerInit:
    def test_default_strategy_is_adaptive(self):
        t = RateLimitThrottler("test_source")
        assert t.strategy == BackoffStrategy.ADAPTIVE

    def test_explicit_strategy(self):
        t = RateLimitThrottler("test_source", strategy=BackoffStrategy.LINEAR)
        assert t.strategy == BackoffStrategy.LINEAR

    def test_env_var_strategy(self):
        with patch.dict("os.environ", {"DATASOURCE_MYDS_BACKOFF_STRATEGY": "exponential"}):
            t = RateLimitThrottler("myds")
            assert t.strategy == BackoffStrategy.EXPONENTIAL

    def test_env_var_base_delay(self):
        with patch.dict("os.environ", {"DATASOURCE_MYDS_BACKOFF_BASE_DELAY": "5.0"}):
            t = RateLimitThrottler("myds")
            # 通过触发限流来验证 base_delay 生效
            wait = t.on_rate_limit()
            assert wait >= 5.0

    def test_env_var_max_delay(self):
        with patch.dict("os.environ", {"DATASOURCE_MYDS_BACKOFF_MAX_DELAY": "10.0"}):
            t = RateLimitThrottler("myds", strategy=BackoffStrategy.EXPONENTIAL)
            # 连续限流多次，退避时间不应超过 max_delay + jitter
            for _ in range(20):
                wait = t.on_rate_limit()
            assert wait <= 10.0 + 1.0  # max_delay + max jitter

    def test_source_name(self):
        t = RateLimitThrottler("yfinance")
        assert t.source_name == "yfinance"


# ─────────────────────────────────────────
#  退避策略计算
# ─────────────────────────────────────────

class TestBackoffStrategies:
    def test_none_strategy_no_throttle(self):
        t = RateLimitThrottler("test", strategy=BackoffStrategy.NONE)
        wait = t.on_rate_limit()
        assert wait == 0.0
        assert not t.should_throttle()

    def test_linear_strategy(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=2.0, jitter=False,
        )
        # 第1次: base + step*1 = 2 + 2 = 4
        w1 = t.on_rate_limit()
        assert w1 == 4.0

        # 第2次: base + step*2 = 2 + 4 = 6
        w2 = t.on_rate_limit()
        assert w2 == 6.0

        # 第3次: base + step*3 = 2 + 6 = 8
        w3 = t.on_rate_limit()
        assert w3 == 8.0

    def test_exponential_strategy(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.EXPONENTIAL,
            base_delay=2.0, jitter=False,
        )
        # 第1次: 2 * 2^1 = 4
        w1 = t.on_rate_limit()
        assert w1 == 4.0

        # 第2次: 2 * 2^2 = 8
        w2 = t.on_rate_limit()
        assert w2 == 8.0

        # 第3次: 2 * 2^3 = 16
        w3 = t.on_rate_limit()
        assert w3 == 16.0

    def test_exponential_caps_at_max_delay(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.EXPONENTIAL,
            base_delay=2.0, max_delay=10.0, jitter=False,
        )
        # 连续触发，最终应被 cap 在 max_delay
        for _ in range(10):
            wait = t.on_rate_limit()
        assert wait == 10.0

    def test_adaptive_strategy(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.ADAPTIVE,
            base_delay=2.0, jitter=False,
        )
        # 自适应策略：指数退避 + 动态调整
        w1 = t.on_rate_limit()
        assert w1 >= 2.0  # 至少是 base_delay

        w2 = t.on_rate_limit()
        assert w2 >= w1  # 递增

    def test_jitter_adds_randomness(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=2.0, jitter=True,
        )
        # 多次触发，收集退避时间
        waits = [t.on_rate_limit() for _ in range(5)]
        # 由于 jitter 的存在，每次的退避时间应该不完全相同
        # （概率极低全部相同，除非 random 恰好为 0）
        # 这里只验证 jitter 使得 wait > 基础值
        # linear: base + step*n = 2 + 2*1 = 4, 加 jitter 后 > 4
        assert waits[0] >= 4.0
        assert waits[0] <= 5.0  # 4 + max jitter 1.0


# ─────────────────────────────────────────
#  Retry-After 优先采纳
# ─────────────────────────────────────────

class TestRetryAfter:
    def test_retry_after_overrides_strategy(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.EXPONENTIAL,
            base_delay=2.0, jitter=False,
        )
        error = ErrorInfo.rate_limited(retry_after=30.0)
        wait = t.on_rate_limit(error)
        # 应采纳 retry_after=30 而非策略计算值
        assert wait == 30.0

    def test_retry_after_capped_by_max_delay(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=2.0, max_delay=20.0, jitter=False,
        )
        error = ErrorInfo.rate_limited(retry_after=60.0)
        wait = t.on_rate_limit(error)
        # retry_after=60 被 max_delay=20 截断
        assert wait == 20.0


# ─────────────────────────────────────────
#  退避期拦截
# ─────────────────────────────────────────

class TestThrottleBlocking:
    def test_should_throttle_after_rate_limit(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=10.0, jitter=False,
        )
        assert not t.should_throttle()

        t.on_rate_limit()
        assert t.should_throttle()
        assert t.remaining_throttle_seconds() > 0

    def test_should_not_throttle_with_none_strategy(self):
        t = RateLimitThrottler("test", strategy=BackoffStrategy.NONE)
        t.on_rate_limit()
        assert not t.should_throttle()
        assert t.remaining_throttle_seconds() == 0.0

    def test_throttle_expires(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=0.05, jitter=False,
        )
        t.on_rate_limit()
        assert t.should_throttle()

        # 等待退避过期 (linear: 0.05 + 0.05*1 = 0.1s)
        time.sleep(0.15)
        assert not t.should_throttle()

    def test_remaining_seconds_zero_when_not_throttled(self):
        t = RateLimitThrottler("test", strategy=BackoffStrategy.LINEAR)
        assert t.remaining_throttle_seconds() == 0.0


# ─────────────────────────────────────────
#  恢复机制
# ─────────────────────────────────────────

class TestRecovery:
    def test_adaptive_recovery_after_successes(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.ADAPTIVE,
            base_delay=2.0, jitter=False,
        )
        # 触发限流
        t.on_rate_limit()
        t.on_rate_limit()
        assert t._consecutive_limits == 2

        # 连续成功 10 次（ADAPTIVE_RECOVERY_THRESHOLD）
        for _ in range(10):
            t.on_success()

        # consecutive_limits 应减少
        assert t._consecutive_limits < 2

    def test_full_recovery_resets_state(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.ADAPTIVE,
            base_delay=2.0, jitter=False,
        )
        # 触发一次限流
        t.on_rate_limit()
        assert t._consecutive_limits == 1

        # 多轮成功恢复（需要足够多轮使 request_interval 降到 epsilon 以下）
        # 初始 request_interval ≈ 4.0, 每次 *0.8, 需要约 30 轮降到 <0.1
        for _ in range(30):
            for _ in range(10):
                t.on_success()

        # 应完全恢复
        assert t._consecutive_limits == 0
        assert t._request_interval < 0.1

    def test_success_does_not_affect_none_strategy(self):
        t = RateLimitThrottler("test", strategy=BackoffStrategy.NONE)
        t.on_success()
        assert t._request_interval == 0.0


# ─────────────────────────────────────────
#  状态查询
# ─────────────────────────────────────────

class TestStatus:
    def test_initial_status(self):
        t = RateLimitThrottler("test", strategy=BackoffStrategy.ADAPTIVE)
        status = t.get_status()
        assert isinstance(status, RateLimitStatus)
        assert not status.is_throttled
        assert status.consecutive_rate_limits == 0
        assert status.total_rate_limits_1h == 0
        assert status.backoff_strategy == "adaptive"

    def test_status_after_rate_limit(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=10.0, jitter=False,
        )
        t.on_rate_limit()
        status = t.get_status()
        assert status.is_throttled
        assert status.consecutive_rate_limits == 1
        assert status.total_rate_limits_1h == 1
        assert status.throttle_until is not None

    def test_status_estimated_rpm(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=2.0, jitter=False,
        )
        t.on_rate_limit()
        status = t.get_status()
        # wait = 2 + 2*1 = 4s → rpm = 60/4 = 15
        assert status.estimated_limit_rpm == 15

    def test_status_total_1h_counts_multiple_events(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=0.01, jitter=False,
        )
        for _ in range(5):
            t.on_rate_limit()
            time.sleep(0.02)  # 确保退避过期

        status = t.get_status()
        assert status.total_rate_limits_1h == 5


# ─────────────────────────────────────────
#  重置
# ─────────────────────────────────────────

class TestReset:
    def test_reset_clears_all_state(self):
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.LINEAR,
            base_delay=10.0, jitter=False,
        )
        t.on_rate_limit()
        t.on_rate_limit()
        assert t.should_throttle()

        t.reset()
        assert not t.should_throttle()
        assert t._consecutive_limits == 0
        assert t._request_interval == 0.0
        assert t.remaining_throttle_seconds() == 0.0


# ─────────────────────────────────────────
#  并发安全
# ─────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_rate_limits(self):
        """多线程并发触发限流不应导致异常"""
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.EXPONENTIAL,
            base_delay=1.0, jitter=False,
        )
        errors = []

        def trigger():
            try:
                for _ in range(100):
                    t.on_rate_limit()
                    t.should_throttle()
                    t.get_status()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=trigger) for _ in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors, f"并发异常: {errors}"

    def test_concurrent_mixed_operations(self):
        """并发混合操作（限流 + 成功 + 状态查询 + 重置）"""
        t = RateLimitThrottler(
            "test", strategy=BackoffStrategy.ADAPTIVE,
            base_delay=0.1, jitter=False,
        )
        errors = []

        def rate_limiter():
            try:
                for _ in range(50):
                    t.on_rate_limit()
            except Exception as e:
                errors.append(e)

        def success_reporter():
            try:
                for _ in range(50):
                    t.on_success()
            except Exception as e:
                errors.append(e)

        def status_reader():
            try:
                for _ in range(50):
                    t.get_status()
                    t.should_throttle()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=rate_limiter),
            threading.Thread(target=success_reporter),
            threading.Thread(target=status_reader),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors, f"并发异常: {errors}"


# ─────────────────────────────────────────
#  repr
# ─────────────────────────────────────────

class TestRepr:
    def test_repr_contains_source_name(self):
        t = RateLimitThrottler("yfinance", strategy=BackoffStrategy.LINEAR)
        r = repr(t)
        assert "yfinance" in r
        assert "linear" in r
