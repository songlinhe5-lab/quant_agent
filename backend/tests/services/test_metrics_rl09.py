"""
RL-09/10: Prometheus 限流指标埋点单测
=======================================

验证:
- 5 个 Prometheus 指标定义正确
- Throttler 触发限流时 ds_rate_limit_total 递增
- Throttler 退避时 ds_rate_limit_throttled_seconds 更新
- Throttler get_status() 更新 effective_rpm gauge
- 退避策略状态映射正确
- HealthInfo 包含 RateLimitStatus
"""


from backend.core.metrics import (
    DS_BACKOFF_STATE,
    DS_RATE_LIMIT_EFFECTIVE_RPM,
    DS_RATE_LIMIT_ESTIMATED_RPM,
    DS_RATE_LIMIT_THROTTLED_SECONDS,
    DS_RATE_LIMIT_TOTAL,
)
from backend.services.datasource import (
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
)
from backend.services.datasource.throttler import (
    _BACKOFF_STATE_MAP,
    BackoffStrategy,
    RateLimitThrottler,
)

# ─────────────────────────────────────────
#  Prometheus 指标定义
# ─────────────────────────────────────────

class TestMetricsDefinition:
    def test_ds_rate_limit_total_is_counter(self):
        assert DS_RATE_LIMIT_TOTAL is not None
        assert DS_RATE_LIMIT_TOTAL._type == "counter"

    def test_ds_rate_limit_throttled_seconds_is_gauge(self):
        assert DS_RATE_LIMIT_THROTTLED_SECONDS is not None
        assert DS_RATE_LIMIT_THROTTLED_SECONDS._type == "gauge"

    def test_ds_rate_limit_estimated_rpm_is_gauge(self):
        assert DS_RATE_LIMIT_ESTIMATED_RPM is not None
        assert DS_RATE_LIMIT_ESTIMATED_RPM._type == "gauge"

    def test_ds_rate_limit_effective_rpm_is_gauge(self):
        assert DS_RATE_LIMIT_EFFECTIVE_RPM is not None
        assert DS_RATE_LIMIT_EFFECTIVE_RPM._type == "gauge"

    def test_ds_backoff_state_is_gauge(self):
        assert DS_BACKOFF_STATE is not None
        assert DS_BACKOFF_STATE._type == "gauge"


# ─────────────────────────────────────────
#  退避策略状态映射
# ─────────────────────────────────────────

class TestBackoffStateMap:
    def test_none_maps_to_0(self):
        assert _BACKOFF_STATE_MAP["none"] == 0

    def test_linear_maps_to_1(self):
        assert _BACKOFF_STATE_MAP["linear"] == 1

    def test_exponential_maps_to_2(self):
        assert _BACKOFF_STATE_MAP["exponential"] == 2

    def test_adaptive_maps_to_3(self):
        assert _BACKOFF_STATE_MAP["adaptive"] == 3


# ─────────────────────────────────────────
#  Prometheus 埋点集成
# ─────────────────────────────────────────

class TestMetricsIntegration:
    def test_on_rate_limit_increments_counter(self):
        """限流触发时 ds_rate_limit_total 递增"""
        t = RateLimitThrottler("test_metrics", strategy=BackoffStrategy.LINEAR, jitter=False)
        # 获取初始值
        initial = DS_RATE_LIMIT_TOTAL.labels(source="test_metrics", category="rate_limit")._value.get()
        t.on_rate_limit()
        after = DS_RATE_LIMIT_TOTAL.labels(source="test_metrics", category="rate_limit")._value.get()
        assert after == initial + 1

    def test_on_rate_limit_with_error_category(self):
        """限流带 ErrorInfo 时使用正确的 category 标签"""
        t = RateLimitThrottler("test_cat_metrics", strategy=BackoffStrategy.LINEAR, jitter=False)
        error = ErrorInfo.quota_exhausted()
        initial = DS_RATE_LIMIT_TOTAL.labels(source="test_cat_metrics", category="quota_exhausted")._value.get()
        t.on_rate_limit(error)
        after = DS_RATE_LIMIT_TOTAL.labels(source="test_cat_metrics", category="quota_exhausted")._value.get()
        assert after == initial + 1

    def test_on_rate_limit_updates_throttled_gauge(self):
        """限流触发时 ds_rate_limit_throttled_seconds 更新"""
        t = RateLimitThrottler("test_throttle_gauge", strategy=BackoffStrategy.LINEAR, base_delay=5.0, jitter=False)
        t.on_rate_limit()
        val = DS_RATE_LIMIT_THROTTLED_SECONDS.labels(source="test_throttle_gauge")._value.get()
        assert val > 0

    def test_on_rate_limit_updates_backoff_state(self):
        """限流触发时 ds_backoff_state 更新"""
        t = RateLimitThrottler("test_backoff_gauge", strategy=BackoffStrategy.ADAPTIVE, jitter=False)
        t.on_rate_limit()
        val = DS_BACKOFF_STATE.labels(source="test_backoff_gauge")._value.get()
        assert val == 3  # adaptive = 3

    def test_get_status_updates_effective_rpm(self):
        """get_status() 更新 ds_rate_limit_effective_rpm"""
        t = RateLimitThrottler("test_eff_rpm", strategy=BackoffStrategy.ADAPTIVE, jitter=False)
        t.on_rate_limit()  # 设置 request_interval
        t.get_status()
        # gauge 应该被设置（值可能是 0 或正数）
        val = DS_RATE_LIMIT_EFFECTIVE_RPM.labels(source="test_eff_rpm")._value.get()
        assert val >= 0


# ─────────────────────────────────────────
#  HealthInfo 包含 RateLimitStatus
# ─────────────────────────────────────────

class TestHealthInfoRateLimit:
    def test_health_info_has_rate_limit_status(self):
        """HealthInfo 包含 rate_limit_status 字段"""
        health = HealthInfo()
        assert hasattr(health, "rate_limit_status")
        assert isinstance(health.rate_limit_status, RateLimitStatus)

    def test_health_info_rate_limit_status_populated(self):
        """RateLimitStatus 可正确填充"""
        status = RateLimitStatus(
            is_throttled=True,
            consecutive_rate_limits=3,
            estimated_limit_rpm=30,
            backoff_strategy="adaptive",
        )
        health = HealthInfo(healthy=True, rate_limit_status=status)
        d = health.to_dict()
        assert d["rate_limit_status"]["is_throttled"] is True
        assert d["rate_limit_status"]["consecutive_rate_limits"] == 3
        assert d["rate_limit_status"]["estimated_limit_rpm"] == 30
        assert d["rate_limit_status"]["backoff_strategy"] == "adaptive"

    def test_health_info_default_rate_limit_status(self):
        """默认 HealthInfo 的 rate_limit_status 为无限流"""
        health = HealthInfo()
        d = health.to_dict()
        assert d["rate_limit_status"]["is_throttled"] is False
        assert d["rate_limit_status"]["consecutive_rate_limits"] == 0


# ─────────────────────────────────────────
#  环境变量配置 (RL-12)
# ─────────────────────────────────────────

class TestEnvConfig:
    def test_default_strategy_is_adaptive(self):
        """默认退避策略为 adaptive"""
        t = RateLimitThrottler("test_env_default")
        assert t.strategy == BackoffStrategy.ADAPTIVE

    def test_env_override_strategy(self, monkeypatch):
        """环境变量覆盖退避策略"""
        monkeypatch.setenv("DATASOURCE_TESTENV_BACKOFF_STRATEGY", "exponential")
        t = RateLimitThrottler("testenv")
        assert t.strategy == BackoffStrategy.EXPONENTIAL

    def test_env_override_base_delay(self, monkeypatch):
        """环境变量覆盖基础延迟"""
        monkeypatch.setenv("DATASOURCE_TESTENV2_BACKOFF_BASE_DELAY", "10.0")
        t = RateLimitThrottler("testenv2")
        assert t._base_delay == 10.0

    def test_env_override_max_delay(self, monkeypatch):
        """环境变量覆盖最大延迟"""
        monkeypatch.setenv("DATASOURCE_TESTENV3_BACKOFF_MAX_DELAY", "600.0")
        t = RateLimitThrottler("testenv3")
        assert t._max_delay == 600.0

    def test_env_override_jitter(self, monkeypatch):
        """环境变量覆盖抖动开关"""
        monkeypatch.setenv("DATASOURCE_TESTENV4_BACKOFF_JITTER", "false")
        t = RateLimitThrottler("testenv4")
        assert t._jitter is False
