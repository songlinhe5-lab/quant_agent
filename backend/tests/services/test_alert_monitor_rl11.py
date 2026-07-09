"""
RL-11: 限流告警监控器单测
==========================

验证:
- IP 封禁立即触发 critical 告警
- 配额耗尽触发 critical 告警
- 长时间退避 (>2min) 触发 warning 告警
- 限流频率飙升 (>10/5min) 触发 critical 告警
- 去重冷却: 同数据源+同类型 15 分钟内不重复告警
- 未达阈值不触发告警
- get_status / reset
- Throttler 集成: on_rate_limit 自动调用告警监控器
"""

import time
from unittest.mock import patch

import pytest

from backend.services.datasource.alert_monitor import (
    RateLimitAlertMonitor,
)


@pytest.fixture
def monitor():
    m = RateLimitAlertMonitor()
    m.reset()
    return m


# ─────────────────────────────────────────
# IP 封禁告警
# ─────────────────────────────────────────

class TestIPBlockedAlert:
    def test_ip_blocked_triggers_critical_alert(self, monitor):
        """IP 封禁立即触发 critical 告警"""
        alert = monitor.on_rate_limit_event(
            source="yahoo",
            category="ip_blocked",
            wait_seconds=300,
            consecutive_rate_limits=1,
        )
        assert alert is not None
        assert alert.severity == "critical"
        assert alert.category == "ip_blocked"
        assert "IP 被封禁" in alert.message

    def test_ip_blocked_cooldown(self, monitor):
        """IP 封禁冷却期内不重复告警"""
        alert1 = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 1)
        assert alert1 is not None

        alert2 = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 2)
        assert alert2 is None  # 冷却中


# ─────────────────────────────────────────
# 配额耗尽告警
# ─────────────────────────────────────────

class TestQuotaExhaustedAlert:
    def test_quota_exhausted_triggers_critical_alert(self, monitor):
        """配额耗尽触发 critical 告警"""
        alert = monitor.on_rate_limit_event(
            source="finnhub",
            category="quota_exhausted",
            wait_seconds=3600,
            consecutive_rate_limits=1,
        )
        assert alert is not None
        assert alert.severity == "critical"
        assert "配额已耗尽" in alert.message

    def test_different_source_not_cooldown(self, monitor):
        """不同数据源不受冷却影响"""
        alert1 = monitor.on_rate_limit_event("finnhub", "quota_exhausted", 3600, 1)
        assert alert1 is not None

        alert2 = monitor.on_rate_limit_event("yahoo", "quota_exhausted", 3600, 1)
        assert alert2 is not None  # 不同数据源，不受冷却


# ─────────────────────────────────────────
# 长时间退避告警
# ─────────────────────────────────────────

class TestLongBackoffAlert:
    def test_long_backoff_triggers_warning(self, monitor):
        """退避 >2min 触发 warning 告警"""
        alert = monitor.on_rate_limit_event(
            source="yfinance",
            category="rate_limit",
            wait_seconds=150,  # 2.5 min
            consecutive_rate_limits=3,
        )
        assert alert is not None
        assert alert.severity == "warning"
        assert "退避时间过长" in alert.message

    def test_short_backoff_no_alert(self, monitor):
        """退避 <2min 不触发长时间退避告警"""
        alert = monitor.on_rate_limit_event(
            source="yfinance",
            category="rate_limit",
            wait_seconds=30,  # 30s
            consecutive_rate_limits=1,
        )
        assert alert is None  # 不触发任何告警


# ─────────────────────────────────────────
# 限流频率飙升告警
# ─────────────────────────────────────────

class TestRateLimitSpikeAlert:
    def test_spike_triggers_critical_alert(self, monitor):
        """5 分钟内 >10 次限流触发 critical 告警"""
        # 前 10 次不触发 (阈值 = 10)
        for i in range(10):
            alert = monitor.on_rate_limit_event("yahoo", "rate_limit", 10, i + 1)
            assert alert is None, f"第 {i+1} 次不应触发告警"

        # 第 11 次触发
        alert = monitor.on_rate_limit_event("yahoo", "rate_limit", 10, 11)
        assert alert is not None
        assert alert.severity == "critical"
        assert "限流频率飙升" in alert.message

    def test_spike_window_expiry(self, monitor):
        """窗口过期后限流计数清零"""
        # 添加 10 个事件
        for i in range(10):
            monitor.on_rate_limit_event("yahoo", "rate_limit", 10, i + 1)

        # 模拟时间流逝 (手动修改 _rate_counts 中的时间戳)
        old_time = time.time() - 400  # 超过 5 分钟窗口
        monitor._rate_counts["yahoo"] = [old_time] * 10

        # 新事件: 旧事件已过期，只有 1 个有效
        alert = monitor.on_rate_limit_event("yahoo", "rate_limit", 10, 1)
        assert alert is None  # 只有 1 个有效事件，不触发


# ─────────────────────────────────────────
# 去重冷却机制
# ─────────────────────────────────────────

class TestCooldown:
    def test_same_source_same_type_cooldown(self, monitor):
        """同数据源+同类型在冷却期内不重复"""
        # 触发 IP 封禁
        alert1 = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 1)
        assert alert1 is not None

        # 再次触发同类型
        alert2 = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 2)
        assert alert2 is None

    def test_same_source_different_type_no_cooldown(self, monitor):
        """同数据源不同类型不受冷却影响"""
        # 触发 IP 封禁
        alert1 = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 1)
        assert alert1 is not None

        # 触发配额耗尽 (不同类型)
        alert2 = monitor.on_rate_limit_event("yahoo", "quota_exhausted", 3600, 2)
        assert alert2 is not None

    def test_cooldown_expires(self, monitor):
        """冷却期过后可以再次告警"""
        monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 1)

        # 手动让冷却过期
        monitor._last_alert[("yahoo", "ip_blocked")] = time.time() - 1000

        alert = monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 2)
        assert alert is not None


# ─────────────────────────────────────────
# get_status / reset
# ─────────────────────────────────────────

class TestMonitorStatus:
    def test_get_status_empty(self, monitor):
        """空状态"""
        status = monitor.get_status()
        assert status["active_spike_sources"] == []
        assert status["recent_rate_counts"] == {}

    def test_get_status_with_events(self, monitor):
        """有事件后的状态"""
        for i in range(5):
            monitor.on_rate_limit_event("yahoo", "rate_limit", 10, i + 1)

        status = monitor.get_status()
        assert "yahoo" in status["recent_rate_counts"]
        assert status["recent_rate_counts"]["yahoo"] == 5

    def test_reset_clears_all(self, monitor):
        """reset 清空所有状态"""
        monitor.on_rate_limit_event("yahoo", "ip_blocked", 300, 1)
        monitor.reset()

        status = monitor.get_status()
        assert status["active_spike_sources"] == []
        assert status["recent_rate_counts"] == {}
        assert status["cooldown_keys"] == []


# ─────────────────────────────────────────
# Throttler 集成
# ─────────────────────────────────────────

class TestThrottlerIntegration:
    def test_throttler_calls_alert_monitor(self):
        """Throttler.on_rate_limit 自动调用告警监控器"""
        from backend.services.datasource import ErrorInfo
        from backend.services.datasource.throttler import BackoffStrategy, RateLimitThrottler

        throttler = RateLimitThrottler(
            source_name="test_source",
            strategy=BackoffStrategy.LINEAR,
            base_delay=10,
        )

        with patch(
            "backend.services.datasource.alert_monitor.rate_limit_alert_monitor"
        ) as mock_monitor:
            error = ErrorInfo.rate_limited()
            throttler.on_rate_limit(error)
            mock_monitor.on_rate_limit_event.assert_called_once()
            call_kwargs = mock_monitor.on_rate_limit_event.call_args.kwargs
            assert call_kwargs["source"] == "test_source"
            assert call_kwargs["category"] == "rate_limit"
