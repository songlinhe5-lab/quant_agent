"""
RL-01: ErrorInfo / RateLimitInfo / Result 模型单测
==================================================

验证:
- ErrorInfo 的 category 字段正确填充
- RateLimitInfo 嵌套结构正确序列化/反序列化
- Result 统一返回结构的快捷构造
- classify_http_error 正确推断错误分类
- parse_retry_after 正确解析 Retry-After
- DataSourceRouter 集成：限流错误不计入熔断器
"""

import time
from unittest.mock import patch

import pytest

from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    HealthInfo,
    RateLimitInfo,
    RateLimitStatus,
    Result,
    classify_http_error,
    parse_retry_after,
)

# ─────────────────────────────────────────
#  ErrorCategory 枚举
# ─────────────────────────────────────────


class TestErrorCategory:
    def test_enum_values(self):
        assert ErrorCategory.NORMAL.value == "normal"
        assert ErrorCategory.RATE_LIMIT.value == "rate_limit"
        assert ErrorCategory.QUOTA_EXHAUSTED.value == "quota_exhausted"
        assert ErrorCategory.IP_BLOCKED.value == "ip_blocked"

    def test_enum_from_string(self):
        assert ErrorCategory("normal") == ErrorCategory.NORMAL
        assert ErrorCategory("rate_limit") == ErrorCategory.RATE_LIMIT
        assert ErrorCategory("quota_exhausted") == ErrorCategory.QUOTA_EXHAUSTED
        assert ErrorCategory("ip_blocked") == ErrorCategory.IP_BLOCKED

    def test_invalid_enum_raises(self):
        with pytest.raises(ValueError):
            ErrorCategory("invalid_category")


# ─────────────────────────────────────────
#  RateLimitInfo
# ─────────────────────────────────────────


class TestRateLimitInfo:
    def test_default_values(self):
        info = RateLimitInfo()
        assert info.retry_after_seconds is None
        assert info.estimated_reset_seconds is None
        assert info.current_rpm is None
        assert info.limit_rpm is None
        assert info.source_header is None

    def test_with_values(self):
        info = RateLimitInfo(
            retry_after_seconds=30.0,
            estimated_reset_seconds=60.0,
            current_rpm=25,
            limit_rpm=30,
            source_header="X-RateLimit-Remaining: 0",
        )
        assert info.retry_after_seconds == 30.0
        assert info.limit_rpm == 30

    def test_to_dict(self):
        info = RateLimitInfo(retry_after_seconds=15.0, limit_rpm=30)
        d = info.to_dict()
        assert d["retry_after_seconds"] == 15.0
        assert d["limit_rpm"] == 30
        assert d["estimated_reset_seconds"] is None

    def test_from_dict(self):
        data = {"retry_after_seconds": 20.0, "current_rpm": 10}
        info = RateLimitInfo.from_dict(data)
        assert info is not None
        assert info.retry_after_seconds == 20.0
        assert info.current_rpm == 10
        assert info.limit_rpm is None

    def test_from_dict_none(self):
        assert RateLimitInfo.from_dict(None) is None


# ─────────────────────────────────────────
#  ErrorInfo
# ─────────────────────────────────────────


class TestErrorInfo:
    def test_default_category_is_normal(self):
        err = ErrorInfo(code="TEST", message="test error")
        assert err.category == ErrorCategory.NORMAL
        assert err.retryable is False
        assert err.rate_limit_info is None

    def test_is_rate_limit_type(self):
        assert not ErrorInfo.normal("X", "x").is_rate_limit_type
        assert ErrorInfo.rate_limited().is_rate_limit_type
        assert ErrorInfo.quota_exhausted().is_rate_limit_type
        assert ErrorInfo.ip_blocked().is_rate_limit_type

    def test_normal_factory(self):
        err = ErrorInfo.normal("FUTU_DISCONNECTED", "OpenD 连接断开", retryable=True)
        assert err.code == "FUTU_DISCONNECTED"
        assert err.category == ErrorCategory.NORMAL
        assert err.retryable is True
        assert err.rate_limit_info is None
        assert not err.is_rate_limit_type

    def test_rate_limited_factory(self):
        err = ErrorInfo.rate_limited(
            code="YFINANCE_429",
            message="Yahoo 限流",
            retry_after=30.0,
            limit_rpm=30,
            source_header="X-RateLimit-Remaining: 0",
        )
        assert err.code == "YFINANCE_429"
        assert err.category == ErrorCategory.RATE_LIMIT
        assert err.retryable is True
        assert err.is_rate_limit_type
        assert err.rate_limit_info is not None
        assert err.rate_limit_info.retry_after_seconds == 30.0
        assert err.rate_limit_info.limit_rpm == 30

    def test_quota_exhausted_factory(self):
        err = ErrorInfo.quota_exhausted(
            code="FINNHUB_QUOTA",
            message="Finnhub 日配额耗尽",
            estimated_reset=86400.0,
        )
        assert err.category == ErrorCategory.QUOTA_EXHAUSTED
        assert err.is_rate_limit_type
        assert err.rate_limit_info.estimated_reset_seconds == 86400.0

    def test_ip_blocked_factory(self):
        err = ErrorInfo.ip_blocked(
            code="YAHOO_IP_BLOCK",
            message="Yahoo 封禁 IP 段",
            estimated_reset=3600.0,
        )
        assert err.category == ErrorCategory.IP_BLOCKED
        assert err.is_rate_limit_type
        assert err.rate_limit_info.estimated_reset_seconds == 3600.0

    def test_to_dict(self):
        err = ErrorInfo.rate_limited(retry_after=10.0, limit_rpm=25)
        d = err.to_dict()
        assert d["category"] == "rate_limit"
        assert d["retryable"] is True
        assert d["rate_limit_info"]["retry_after_seconds"] == 10.0
        assert d["rate_limit_info"]["limit_rpm"] == 25

    def test_to_dict_normal_no_rate_limit_info(self):
        err = ErrorInfo.normal("X", "x")
        d = err.to_dict()
        assert d["category"] == "normal"
        assert "rate_limit_info" not in d

    def test_from_dict_roundtrip(self):
        original = ErrorInfo.rate_limited(retry_after=15.0, limit_rpm=30)
        d = original.to_dict()
        restored = ErrorInfo.from_dict(d)
        assert restored is not None
        assert restored.category == ErrorCategory.RATE_LIMIT
        assert restored.rate_limit_info.retry_after_seconds == 15.0
        assert restored.rate_limit_info.limit_rpm == 30

    def test_from_dict_none(self):
        assert ErrorInfo.from_dict(None) is None


# ─────────────────────────────────────────
#  Result
# ─────────────────────────────────────────


class TestResult:
    def test_success_factory(self):
        r = Result.make_success(data={"price": 100.0}, source="futu-local", latency_ms=12.5)
        assert r.is_success
        assert not r.is_error
        assert not r.is_rate_limited
        assert not r.is_degraded
        assert r.data["price"] == 100.0
        assert r.source == "futu-local"
        assert r.latency_ms == 12.5

    def test_error_factory(self):
        err = ErrorInfo.normal("TIMEOUT", "连接超时", retryable=True)
        r = Result.make_error(error=err, source="yf-node-01")
        assert r.is_error
        assert r.error.code == "TIMEOUT"
        assert r.error.category == ErrorCategory.NORMAL

    def test_rate_limited_factory(self):
        err = ErrorInfo.rate_limited(retry_after=30.0)
        r = Result.make_rate_limited(error=err, source="yf-node-01")
        assert r.is_rate_limited
        assert r.error.category == ErrorCategory.RATE_LIMIT

    def test_degraded_factory(self):
        r = Result.make_degraded(data={"price": 99.0}, source="stale-cache")
        assert r.is_degraded
        assert r.cached is True

    def test_to_dict_success(self):
        r = Result.make_success(data={"price": 100.0}, source="futu", latency_ms=5.555)
        d = r.to_dict()
        assert d["status"] == "success"
        assert d["latency_ms"] == 5.55  # Python round(5.555, 2) = 5.55 due to float representation
        assert "error" not in d

    def test_to_dict_error(self):
        err = ErrorInfo.rate_limited(retry_after=10.0)
        r = Result.make_rate_limited(error=err)
        d = r.to_dict()
        assert d["status"] == "rate_limited"
        assert d["error"]["category"] == "rate_limit"
        assert d["error"]["rate_limit_info"]["retry_after_seconds"] == 10.0


# ─────────────────────────────────────────
#  classify_http_error
# ─────────────────────────────────────────


class TestClassifyHttpError:
    def test_429_is_rate_limit(self):
        assert classify_http_error(429) == ErrorCategory.RATE_LIMIT

    def test_429_with_quota_reset_is_quota_exhausted(self):
        # Reset 时间 > 1h → 配额耗尽
        future_reset = time.time() + 7200  # 2h later
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(future_reset)}
        assert classify_http_error(429, headers) == ErrorCategory.QUOTA_EXHAUSTED

    def test_429_with_near_reset_is_rate_limit(self):
        # Reset 时间 < 1h → 普通限流
        near_reset = time.time() + 60  # 1min later
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(near_reset)}
        assert classify_http_error(429, headers) == ErrorCategory.RATE_LIMIT

    def test_403_with_rate_limit_reason_is_ip_blocked(self):
        headers = {"X-Block-Reason": "Rate limit exceeded"}
        assert classify_http_error(403, headers) == ErrorCategory.IP_BLOCKED

    def test_403_without_reason_is_normal(self):
        assert classify_http_error(403) == ErrorCategory.NORMAL

    def test_500_is_normal(self):
        assert classify_http_error(500) == ErrorCategory.NORMAL

    def test_404_is_normal(self):
        assert classify_http_error(404) == ErrorCategory.NORMAL


# ─────────────────────────────────────────
#  parse_retry_after
# ─────────────────────────────────────────


class TestParseRetryAfter:
    def test_numeric_value(self):
        assert parse_retry_after({"Retry-After": "30"}) == 30.0

    def test_float_value(self):
        assert parse_retry_after({"Retry-After": "2.5"}) == 2.5

    def test_missing_header(self):
        assert parse_retry_after({}) is None

    def test_none_headers(self):
        assert parse_retry_after(None) is None

    def test_invalid_value(self):
        assert parse_retry_after({"Retry-After": "invalid"}) is None


# ─────────────────────────────────────────
#  RateLimitStatus / HealthInfo
# ─────────────────────────────────────────


class TestRateLimitStatus:
    def test_default_values(self):
        s = RateLimitStatus()
        assert s.is_throttled is False
        assert s.backoff_strategy == "none"
        assert s.consecutive_rate_limits == 0

    def test_to_dict(self):
        s = RateLimitStatus(is_throttled=True, estimated_limit_rpm=30, backoff_strategy="adaptive")
        d = s.to_dict()
        assert d["is_throttled"] is True
        assert d["estimated_limit_rpm"] == 30
        assert d["backoff_strategy"] == "adaptive"


class TestHealthInfo:
    def test_includes_rate_limit_status(self):
        h = HealthInfo()
        d = h.to_dict()
        assert "rate_limit_status" in d
        assert d["rate_limit_status"]["is_throttled"] is False
        assert d["rate_limit_status"]["backoff_strategy"] == "none"

    def test_with_rate_limit_data(self):
        h = HealthInfo(
            healthy=True,
            rate_limit_status=RateLimitStatus(
                is_throttled=True,
                estimated_rpm=25,
                estimated_limit_rpm=30,
                consecutive_rate_limits=3,
                backoff_strategy="exponential",
            ),
        )
        d = h.to_dict()
        assert d["rate_limit_status"]["is_throttled"] is True
        assert d["rate_limit_status"]["consecutive_rate_limits"] == 3


# ─────────────────────────────────────────
#  DataSourceRouter 集成测试
# ─────────────────────────────────────────


class TestDataSourceRouterIntegration:
    """验证 DataSourceRouter 中限流错误不计入熔断器"""

    @pytest.fixture
    def router(self):
        with patch.dict(
            "os.environ",
            {
                "DATA_SOURCE_ROUTER_ENABLED": "true",
                "YF_PRIMARY_NODE_URL": "http://test-node:8000",
            },
        ):
            from backend.services.data_source_router import DataSourceRouter

            return DataSourceRouter()

    @pytest.mark.asyncio
    async def test_rate_limit_error_does_not_trigger_circuit_breaker(self, router):
        """限流错误连续 5 次不应触发节点熔断"""
        node_name = "yf_primary"

        # 模拟 5 次限流错误（超过熔断阈值 3）
        for _ in range(5):
            await router._update_node_status(
                node_name,
                success=False,
                error="rate_limit",
                error_category=ErrorCategory.RATE_LIMIT,
            )

        node = router._nodes[node_name]
        # 节点应保持 healthy 状态，error_count 不应增加
        assert node.status == "healthy"
        assert node.error_count == 0

    @pytest.mark.asyncio
    async def test_normal_error_triggers_circuit_breaker(self, router):
        """普通错误连续 3 次应触发节点熔断"""
        node_name = "yf_primary"

        for _ in range(3):
            await router._update_node_status(
                node_name,
                success=False,
                error="timeout",
                error_category=ErrorCategory.NORMAL,
            )

        node = router._nodes[node_name]
        assert node.status == "unhealthy"
        assert node.error_count == 3
        assert node.circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_mixed_errors_only_normal_counts(self, router):
        """混合错误场景：只有普通错误计入熔断器"""
        node_name = "yf_primary"

        # 2 次限流 + 2 次普通错误
        await router._update_node_status(node_name, False, "rate_limit", ErrorCategory.RATE_LIMIT)
        await router._update_node_status(node_name, False, "quota", ErrorCategory.QUOTA_EXHAUSTED)
        await router._update_node_status(node_name, False, "timeout", ErrorCategory.NORMAL)
        await router._update_node_status(node_name, False, "timeout", ErrorCategory.NORMAL)

        node = router._nodes[node_name]
        # 只有 2 次普通错误，不应触发熔断（阈值 3）
        assert node.status == "healthy"
        assert node.error_count == 2

    @pytest.mark.asyncio
    async def test_success_resets_error_count(self, router):
        """成功后 error_count 重置为 0"""
        node_name = "yf_primary"

        await router._update_node_status(node_name, False, "timeout", ErrorCategory.NORMAL)
        await router._update_node_status(node_name, False, "timeout", ErrorCategory.NORMAL)
        await router._update_node_status(node_name, success=True)

        node = router._nodes[node_name]
        assert node.error_count == 0
        assert node.status == "healthy"
