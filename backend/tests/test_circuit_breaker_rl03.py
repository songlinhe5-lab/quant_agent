"""
RL-03: 熔断器与限流退避解耦 单测
==================================

验证:
- is_rate_limit_error 过滤钩子正确识别限流类异常
- error_classifier 回调动态判定
- 限流类错误不计入失败计数（async / sync）
- record_failure(is_rate_limit=True) 不增加失败计数
- record_failure(is_rate_limit=False) 正常增加
- record_success 重置失败计数
- 混合场景：限流 + 普通错误交替出现
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.circuit_breaker import CircuitBreaker, CircuitState
from backend.services.datasource import ErrorCategory

# ─────────────────────────────────────────
#  辅助工具
# ─────────────────────────────────────────

class RateLimitError(Exception):
    """模拟限流异常（携带 _error_category 属性）"""
    def __init__(self, msg="rate limited"):
        super().__init__(msg)
        self._error_category = ErrorCategory.RATE_LIMIT


class NormalError(Exception):
    """模拟普通错误（携带 _error_category 属性）"""
    def __init__(self, msg="normal error"):
        super().__init__(msg)
        self._error_category = ErrorCategory.NORMAL


class PlainError(Exception):
    """模拟无 category 标记的普通异常"""
    pass


# ─────────────────────────────────────────
#  is_rate_limit_error 钩子
# ─────────────────────────────────────────

class TestIsRateLimitError:
    def test_rate_limit_category_returns_true(self):
        cb = CircuitBreaker()
        exc = RateLimitError()
        assert cb.is_rate_limit_error(exc) is True

    def test_normal_category_returns_false(self):
        cb = CircuitBreaker()
        exc = NormalError()
        assert cb.is_rate_limit_error(exc) is False

    def test_plain_exception_returns_false(self):
        cb = CircuitBreaker()
        exc = PlainError("no category")
        assert cb.is_rate_limit_error(exc) is False

    def test_string_category_rate_limit(self):
        cb = CircuitBreaker()
        exc = Exception("429")
        exc._error_category = "rate_limit"
        assert cb.is_rate_limit_error(exc) is True

    def test_string_category_normal(self):
        cb = CircuitBreaker()
        exc = Exception("timeout")
        exc._error_category = "normal"
        assert cb.is_rate_limit_error(exc) is False


# ─────────────────────────────────────────
#  error_classifier 回调
# ─────────────────────────────────────────

class TestErrorClassifier:
    def test_classifier_overrides_default(self):
        """error_classifier 回调优先于 is_rate_limit_error"""
        cb = CircuitBreaker()
        exc = PlainError("custom")

        # 默认不识别
        assert cb.is_rate_limit_error(exc) is False

        # 通过 classifier 识别
        def classifier(e):
            return "custom" in str(e)
        assert cb._should_skip_failure(exc, classifier) is True

    def test_classifier_returning_false_counts_normally(self):
        cb = CircuitBreaker()
        exc = RateLimitError()  # 默认是限流

        # classifier 强制返回 False → 计入失败
        def classifier(e):
            return False
        assert cb._should_skip_failure(exc, classifier) is False


# ─────────────────────────────────────────
#  async call() 限流不计入
# ─────────────────────────────────────────

class TestAsyncCallRateLimitDecoupling:
    @pytest.mark.asyncio
    async def test_rate_limit_errors_do_not_increment_failures(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")
        func = AsyncMock(side_effect=RateLimitError("429"))

        # 连续 5 次限流错误
        for _ in range(5):
            with pytest.raises(RateLimitError):
                await cb.call("svc", func)

        # 失败计数应为 0（限流不计入）
        assert entry.failures == 0
        # 状态应为 CLOSED（不应触发熔断）
        assert entry.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_normal_errors_still_count_after_rate_limits(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        # 先触发限流
        func_rl = AsyncMock(side_effect=RateLimitError())
        with pytest.raises(RateLimitError):
            await cb.call("svc", func_rl)
        assert entry.failures == 0

        # 再触发普通错误
        func_normal = AsyncMock(side_effect=NormalError())
        with pytest.raises(NormalError):
            await cb.call("svc", func_normal)
        assert entry.failures == 1

        # 又一次普通错误 → 触发熔断
        func_normal2 = AsyncMock(side_effect=NormalError())
        with pytest.raises(NormalError):
            await cb.call("svc", func_normal2)
        assert entry.failures == 2
        assert entry.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_error_classifier_in_async_call(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        # 使用 classifier 将 PlainError 标记为限流
        func = AsyncMock(side_effect=PlainError("custom 429"))

        def classifier(e):
            return "429" in str(e)

        for _ in range(5):
            with pytest.raises(PlainError):
                await cb.call("svc", func, error_classifier=classifier)

        assert entry.failures == 0
        assert entry.state == CircuitState.CLOSED


# ─────────────────────────────────────────
#  sync call_sync() 限流不计入
# ─────────────────────────────────────────

class TestSyncCallRateLimitDecoupling:
    def test_rate_limit_errors_do_not_increment_failures_sync(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        def boom():
            raise RateLimitError("429")

        for _ in range(5):
            with pytest.raises(RateLimitError):
                cb.call_sync("svc", boom)

        assert entry.failures == 0
        assert entry.state == CircuitState.CLOSED

    def test_error_classifier_in_sync_call(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        def boom():
            raise PlainError("throttled")

        def classifier(e):
            return "throttled" in str(e)

        for _ in range(5):
            with pytest.raises(PlainError):
                cb.call_sync("svc", boom, error_classifier=classifier)

        assert entry.failures == 0


# ─────────────────────────────────────────
#  record_failure / record_success
# ─────────────────────────────────────────

class TestRecordMethods:
    def test_record_failure_increments_count(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        cb.record_failure("svc", is_rate_limit=False)
        assert entry.failures == 1

        cb.record_failure("svc", is_rate_limit=False)
        assert entry.failures == 2

    def test_record_failure_rate_limit_skips_count(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        cb.record_failure("svc", is_rate_limit=True)
        assert entry.failures == 0

        cb.record_failure("svc", is_rate_limit=True)
        assert entry.failures == 0

    def test_record_failure_triggers_open(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        with (
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"),
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"),
        ):
            cb.record_failure("svc")
            cb.record_failure("svc")

        assert entry.failures == 2
        assert entry.state == CircuitState.OPEN

    def test_record_failure_rate_limit_never_triggers_open(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")

        for _ in range(100):
            cb.record_failure("svc", is_rate_limit=True)

        assert entry.failures == 0
        assert entry.state == CircuitState.CLOSED

    def test_record_success_resets_count(self):
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        cb.record_failure("svc")
        cb.record_failure("svc")
        assert entry.failures == 2

        with (
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"),
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"),
        ):
            cb.record_success("svc")

        assert entry.failures == 0
        assert entry.state == CircuitState.CLOSED

    def test_record_success_from_half_open(self):
        cb = CircuitBreaker(max_failures=2)
        entry = cb._get_entry("svc")
        entry.state = CircuitState.HALF_OPEN

        with (
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"),
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"),
        ):
            cb.record_success("svc")

        assert entry.state == CircuitState.CLOSED
        assert entry.failures == 0


# ─────────────────────────────────────────
#  混合场景
# ─────────────────────────────────────────

class TestMixedScenarios:
    @pytest.mark.asyncio
    async def test_interleaved_rate_limit_and_normal_errors(self):
        """限流 + 普通错误交替：只有普通错误计入熔断"""
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        # 模式: 限流 → 普通 → 限流 → 普通 → 限流 → 普通(触发)
        funcs = [
            (AsyncMock(side_effect=RateLimitError()), True),   # 限流
            (AsyncMock(side_effect=NormalError()), False),     # 普通 #1
            (AsyncMock(side_effect=RateLimitError()), True),   # 限流
            (AsyncMock(side_effect=NormalError()), False),     # 普通 #2
            (AsyncMock(side_effect=RateLimitError()), True),   # 限流
            (AsyncMock(side_effect=NormalError()), False),     # 普通 #3 → 触发
        ]

        with (
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"),
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"),
        ):
            for func, is_rl in funcs:
                exc_type = RateLimitError if is_rl else NormalError
                with pytest.raises(exc_type):
                    await cb.call("svc", func)

        # 只有 3 次普通错误计入
        assert entry.failures == 3
        assert entry.state == CircuitState.OPEN

    def test_mixed_record_methods(self):
        """record_failure + record_success 混合使用"""
        cb = CircuitBreaker(max_failures=3)
        entry = cb._get_entry("svc")

        # 限流 × 5（不计入）
        for _ in range(5):
            cb.record_failure("svc", is_rate_limit=True)
        assert entry.failures == 0

        # 普通 × 2
        cb.record_failure("svc")
        cb.record_failure("svc")
        assert entry.failures == 2

        # 成功 → 重置
        with (
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_STATE"),
            patch("backend.core.circuit_breaker.CIRCUIT_BREAKER_TRANSITIONS"),
        ):
            cb.record_success("svc")
        assert entry.failures == 0

        # 再来限流（仍不计入）
        cb.record_failure("svc", is_rate_limit=True)
        assert entry.failures == 0
