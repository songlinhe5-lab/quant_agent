"""
重试逻辑单元测试（tenacity + httpx）

覆盖：
- is_retryable_http_error() 各种异常路径
- log_retry_attempt() 重试钩子
"""

import httpx

from backend.core.retry_utils import is_retryable_http_error, log_retry_attempt


class TestIsRetryableHttpError:
    """is_retryable_http_error() 重试判定"""

    # ─── 限流与封禁关键词 ──────────────────────────────────────────────

    def test_rate_limit_keywords(self):
        """包含 rate limit 关键词的异常应重试"""
        assert is_retryable_http_error(Exception("rate limit exceeded")) is True
        assert is_retryable_http_error(Exception("Rate Limit reached")) is True

    def test_too_many_requests_keywords(self):
        assert is_retryable_http_error(Exception("too many requests")) is True
        assert is_retryable_http_error(Exception("Too Many Requests")) is True

    def test_429_keyword(self):
        assert is_retryable_http_error(Exception("error 429")) is True

    def test_403_keyword(self):
        assert is_retryable_http_error(Exception("error 403")) is True
        assert is_retryable_http_error(Exception("403 Forbidden")) is True

    def test_forbidden_keyword(self):
        assert is_retryable_http_error(Exception("access forbidden")) is True

    def test_finnhub_keyword(self):
        assert is_retryable_http_error(Exception("finnhub rate limit")) is True

    # ─── Futu 特定异常 ─────────────────────────────────────────────────

    def test_futu_frequency_keyword(self):
        assert is_retryable_http_error(Exception("请求频繁")) is True
        assert is_retryable_http_error(Exception("frequency limit")) is True

    def test_futu_error_code_10041(self):
        assert is_retryable_http_error(Exception("err 10041")) is True

    def test_futu_timeout_keyword(self):
        assert is_retryable_http_error(Exception("request timeout")) is True
        assert is_retryable_http_error(Exception("TimeoutError")) is True

    # ─── httpx 网络异常 ────────────────────────────────────────────────

    def test_httpx_request_error(self):
        """httpx.RequestError 子类应重试"""
        assert is_retryable_http_error(httpx.ConnectError("connection failed")) is True
        assert is_retryable_http_error(httpx.TimeoutException("timeout")) is True
        assert is_retryable_http_error(httpx.ReadTimeout("read timeout")) is True

    def test_httpx_http_status_error_retryable(self):
        """可重试的 HTTP 状态码（403, 429, 500, 502, 503, 504）"""
        for status in (403, 429, 500, 502, 503, 504):
            response = httpx.Response(status)
            exc = httpx.HTTPStatusError("error", request=None, response=response)
            assert is_retryable_http_error(exc) is True, f"status {status} should be retryable"

    def test_httpx_http_status_error_non_retryable(self):
        """不可重试的 HTTP 状态码（200, 400, 401, 404, 422）"""
        for status in (200, 400, 401, 404, 422):
            response = httpx.Response(status)
            exc = httpx.HTTPStatusError("error", request=None, response=response)
            assert is_retryable_http_error(exc) is False, f"status {status} should not be retryable"

    # ─── 不可重试的异常 ─────────────────────────────────────────────────

    def test_generic_exception_not_retryable(self):
        """不含关键词的普通异常不应重试"""
        assert is_retryable_http_error(Exception("something went wrong")) is False
        assert is_retryable_http_error(Exception("validation error")) is False
        assert is_retryable_http_error(ValueError("invalid input")) is False

    def test_httpx_http_status_error_418(self):
        """418 不应重试"""
        response = httpx.Response(418)
        exc = httpx.HTTPStatusError("error", request=None, response=response)
        assert is_retryable_http_error(exc) is False


class TestLogRetryAttempt:
    """log_retry_attempt() 重试钩子（仅验证不抛异常）"""

    def test_log_retry_attempt_no_exception(self):
        """正常调用不应抛异常"""

        class FakeOutcome:
            def exception(self):
                return ValueError("test error")

        class FakeRetryState:
            def __init__(self):
                self.outcome = FakeOutcome()
                self.attempt_number = 1

        log_retry_attempt(FakeRetryState())

    def test_log_retry_attempt_with_exception(self):
        """携带异常的调用不应抛异常"""

        class FakeOutcome:
            def exception(self):
                return TimeoutError("timeout")

        class FakeRetryState:
            def __init__(self):
                self.outcome = FakeOutcome()
                self.attempt_number = 2

        log_retry_attempt(FakeRetryState())
