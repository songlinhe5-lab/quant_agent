"""
RL-05: RateLimitAnalyzer 频率分析器单测
========================================

验证:
- 事件记录与存储
- 推测限流 RPM（P75 算法）
- 推荐安全间隔计算
- 高峰时段识别与合并
- 平均恢复时间计算
- 可信度计算
- 滑动窗口过期清理
- 内存控制（maxlen 淘汰）
- 线程安全性
- 空数据 / 边界情况
"""

import threading
import time
from unittest.mock import patch

import pytest

from backend.services.datasource import RateLimitAnalysis, RateLimitAnalyzer
from backend.services.datasource.analyzer import (
    HourlyBucket,
    _RequestEvent,
    _PEAK_HOUR_RATIO_THRESHOLD,
)


# ─────────────────────────────────────────
#  HourlyBucket
# ─────────────────────────────────────────

class TestHourlyBucket:
    def test_limit_ratio_zero_requests(self):
        bucket = HourlyBucket(hour_label="09:00", requests=0, rate_limits=0)
        assert bucket.limit_ratio == 0.0

    def test_limit_ratio_normal(self):
        bucket = HourlyBucket(hour_label="09:00", requests=100, rate_limits=5)
        assert bucket.limit_ratio == 0.05

    def test_limit_ratio_all_limits(self):
        bucket = HourlyBucket(hour_label="09:00", requests=10, rate_limits=10)
        assert bucket.limit_ratio == 1.0


# ─────────────────────────────────────────
#  RateLimitAnalysis
# ─────────────────────────────────────────

class TestRateLimitAnalysis:
    def test_to_dict_basic(self):
        analysis = RateLimitAnalysis(
            source="yfinance",
            estimated_limit_rpm=30,
            current_effective_rpm=25,
            total_rate_limits_window=47,
            peak_hours=["09:00-11:00"],
            avg_recovery_seconds=62.5,
            recommended_interval_seconds=2.5,
            confidence=0.85,
        )
        d = analysis.to_dict()
        assert d["source"] == "yfinance"
        assert d["estimated_limit_rpm"] == 30
        assert d["current_effective_rpm"] == 25
        assert d["total_rate_limits_window"] == 47
        assert d["peak_hours"] == ["09:00-11:00"]
        assert d["avg_recovery_seconds"] == 62.5
        assert d["recommended_interval_seconds"] == 2.5
        assert d["confidence"] == 0.85
        assert d["history"] == []

    def test_to_dict_none_values(self):
        analysis = RateLimitAnalysis(source="test")
        d = analysis.to_dict()
        assert d["estimated_limit_rpm"] is None
        assert d["current_effective_rpm"] is None
        assert d["avg_recovery_seconds"] is None
        assert d["recommended_interval_seconds"] is None
        assert d["confidence"] == 0.0

    def test_analysis_window_default(self):
        analysis = RateLimitAnalysis(source="test")
        assert analysis.analysis_window == "24h"


# ─────────────────────────────────────────
#  RateLimitAnalyzer 基础功能
# ─────────────────────────────────────────

class TestAnalyzerBasic:
    def test_init_defaults(self):
        analyzer = RateLimitAnalyzer("yfinance")
        assert analyzer.source_name == "yfinance"
        assert analyzer.get_event_count() == 0

    def test_record_success(self):
        analyzer = RateLimitAnalyzer("test")
        analyzer.record_success()
        assert analyzer.get_event_count() == 1

    def test_record_rate_limit(self):
        analyzer = RateLimitAnalyzer("test")
        analyzer.record_rate_limit()
        assert analyzer.get_event_count() == 1

    def test_record_request_mixed(self):
        analyzer = RateLimitAnalyzer("test")
        analyzer.record_success()
        analyzer.record_success()
        analyzer.record_rate_limit()
        assert analyzer.get_event_count() == 3

    def test_reset_clears_events(self):
        analyzer = RateLimitAnalyzer("test")
        analyzer.record_success()
        analyzer.record_rate_limit()
        assert analyzer.get_event_count() == 2
        analyzer.reset()
        assert analyzer.get_event_count() == 0

    def test_repr(self):
        analyzer = RateLimitAnalyzer("yfinance")
        r = repr(analyzer)
        assert "yfinance" in r
        assert "events=0" in r


# ─────────────────────────────────────────
#  空数据分析
# ─────────────────────────────────────────

class TestAnalyzerEmpty:
    def test_analyze_empty(self):
        analyzer = RateLimitAnalyzer("test")
        result = analyzer.analyze()
        assert result.source == "test"
        assert result.estimated_limit_rpm is None
        assert result.current_effective_rpm is None
        assert result.total_rate_limits_window == 0
        assert result.peak_hours == []
        assert result.avg_recovery_seconds is None
        assert result.recommended_interval_seconds is None
        assert result.confidence == 0.0
        assert result.history == []


# ─────────────────────────────────────────
#  推测限流 RPM（P75 算法）
# ─────────────────────────────────────────

class TestEstimateLimitRPM:
    def test_estimate_rpm_with_uniform_traffic(self):
        """均匀流量：每分钟约 5 次成功请求"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 模拟 10 分钟，每分钟 5 次成功请求
        for minute in range(10):
            for _ in range(5):
                analyzer._events.append(_RequestEvent(
                    timestamp=now - (10 - minute) * 60 + 1,
                    is_rate_limit=False,
                ))
        result = analyzer.analyze()
        # P75 应该接近 5
        assert result.estimated_limit_rpm is not None
        assert 4 <= result.estimated_limit_rpm <= 6

    def test_estimate_rpm_with_burst(self):
        """突发流量：大部分分钟低流量，少数分钟高峰"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 20 分钟：15 分钟每分钟 2 次，5 分钟每分钟 20 次
        for minute in range(15):
            for _ in range(2):
                analyzer._events.append(_RequestEvent(
                    timestamp=now - (20 - minute) * 60 + 1,
                    is_rate_limit=False,
                ))
        for minute in range(15, 20):
            for _ in range(20):
                analyzer._events.append(_RequestEvent(
                    timestamp=now - (20 - minute) * 60 + 1,
                    is_rate_limit=False,
                ))
        result = analyzer.analyze()
        # P75 应该更接近低流量（因为 75% 的分钟是低流量）
        assert result.estimated_limit_rpm is not None
        assert result.estimated_limit_rpm <= 20

    def test_estimate_rpm_only_rate_limits(self):
        """仅有限流事件，无成功请求"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        for _ in range(10):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 60,
                is_rate_limit=True,
            ))
        result = analyzer.analyze()
        assert result.estimated_limit_rpm is None


# ─────────────────────────────────────────
#  推荐安全间隔
# ─────────────────────────────────────────

class TestRecommendedInterval:
    def test_recommended_interval_calculation(self):
        """推荐间隔 = 60 / (RPM * 0.8)"""
        analyzer = RateLimitAnalyzer("test")
        # 直接测试静态方法
        interval = RateLimitAnalyzer._calculate_recommended_interval(30)
        # 60 / (30 * 0.8) = 60 / 24 = 2.5
        assert interval == 2.5

    def test_recommended_interval_none_rpm(self):
        interval = RateLimitAnalyzer._calculate_recommended_interval(None)
        assert interval is None

    def test_recommended_interval_zero_rpm(self):
        interval = RateLimitAnalyzer._calculate_recommended_interval(0)
        assert interval is None

    def test_recommended_interval_one_rpm(self):
        interval = RateLimitAnalyzer._calculate_recommended_interval(1)
        # 60 / (1 * 0.8) = 75
        assert interval == 75.0


# ─────────────────────────────────────────
#  高峰时段识别
# ─────────────────────────────────────────

class TestPeakHours:
    def test_identify_peak_hours_with_high_ratio(self):
        """限流率 > 5% 的小时标记为高峰"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 构造两个小时的请求：
        # 小时 A (当前小时): 100 请求，10 限流 (10% > 5%) → 高峰
        # 小时 B (上一小时): 100 请求，2 限流 (2% < 5%) → 非高峰
        current_hour_ts = now
        prev_hour_ts = now - 3600

        for i in range(90):
            analyzer._events.append(_RequestEvent(
                timestamp=current_hour_ts - i,
                is_rate_limit=False,
            ))
        for i in range(10):
            analyzer._events.append(_RequestEvent(
                timestamp=current_hour_ts - i,
                is_rate_limit=True,
            ))
        for i in range(98):
            analyzer._events.append(_RequestEvent(
                timestamp=prev_hour_ts - i,
                is_rate_limit=False,
            ))
        for i in range(2):
            analyzer._events.append(_RequestEvent(
                timestamp=prev_hour_ts - i,
                is_rate_limit=True,
            ))

        result = analyzer.analyze()
        assert len(result.peak_hours) >= 1
        assert result.total_rate_limits_window == 12

    def test_no_peak_hours_when_low_ratio(self):
        """所有限流率 < 5% 时无高峰"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 100 请求，2 限流 (2% < 5%)
        for i in range(98):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=False,
            ))
        for i in range(2):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=True,
            ))
        result = analyzer.analyze()
        assert result.peak_hours == []

    def test_merge_adjacent_peak_hours(self):
        """合并相邻高峰时段"""
        merged = RateLimitAnalyzer._merge_peak_hours(["09:00", "10:00"])
        assert merged == ["09:00-11:00"]

    def test_merge_non_adjacent_peak_hours(self):
        """不相邻高峰不合并"""
        merged = RateLimitAnalyzer._merge_peak_hours(["09:00", "14:00"])
        assert merged == ["09:00-10:00", "14:00-15:00"]

    def test_merge_single_peak_hour(self):
        merged = RateLimitAnalyzer._merge_peak_hours(["14:00"])
        assert merged == ["14:00-15:00"]

    def test_merge_empty_peak_hours(self):
        merged = RateLimitAnalyzer._merge_peak_hours([])
        assert merged == []

    def test_merge_three_adjacent_hours(self):
        merged = RateLimitAnalyzer._merge_peak_hours(["09:00", "10:00", "11:00"])
        assert merged == ["09:00-12:00"]


# ─────────────────────────────────────────
#  平均恢复时间
# ─────────────────────────────────────────

class TestAvgRecovery:
    def test_avg_recovery_basic(self):
        """限流后 30s 恢复"""
        now = time.time()
        rl_events = [_RequestEvent(timestamp=now - 100, is_rate_limit=True)]
        success_events = [_RequestEvent(timestamp=now - 70, is_rate_limit=False)]
        avg = RateLimitAnalyzer._calculate_avg_recovery(rl_events, success_events)
        assert avg is not None
        assert abs(avg - 30.0) < 0.1

    def test_avg_recovery_multiple_events(self):
        """多次限流取平均恢复时间"""
        now = time.time()
        rl_events = [
            _RequestEvent(timestamp=now - 200, is_rate_limit=True),
            _RequestEvent(timestamp=now - 100, is_rate_limit=True),
        ]
        success_events = [
            _RequestEvent(timestamp=now - 170, is_rate_limit=False),  # 恢复 30s
            _RequestEvent(timestamp=now - 60, is_rate_limit=False),   # 恢复 40s
        ]
        avg = RateLimitAnalyzer._calculate_avg_recovery(rl_events, success_events)
        assert avg is not None
        assert abs(avg - 35.0) < 0.1  # (30 + 40) / 2 = 35

    def test_avg_recovery_no_success_after(self):
        """限流后无成功请求"""
        now = time.time()
        rl_events = [_RequestEvent(timestamp=now, is_rate_limit=True)]
        success_events = [_RequestEvent(timestamp=now - 100, is_rate_limit=False)]
        avg = RateLimitAnalyzer._calculate_avg_recovery(rl_events, success_events)
        assert avg is None

    def test_avg_recovery_no_rate_limits(self):
        """无限流事件"""
        success_events = [_RequestEvent(timestamp=time.time(), is_rate_limit=False)]
        avg = RateLimitAnalyzer._calculate_avg_recovery([], success_events)
        assert avg is None

    def test_avg_recovery_empty(self):
        avg = RateLimitAnalyzer._calculate_avg_recovery([], [])
        assert avg is None


# ─────────────────────────────────────────
#  可信度计算
# ─────────────────────────────────────────

class TestConfidence:
    def test_confidence_zero_events(self):
        analyzer = RateLimitAnalyzer("test")
        result = analyzer.analyze()
        assert result.confidence == 0.0

    def test_confidence_partial(self):
        """50 个样本 → confidence = 0.5"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        for i in range(50):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=False,
            ))
        result = analyzer.analyze()
        assert abs(result.confidence - 0.5) < 0.01

    def test_confidence_full(self):
        """100+ 样本 → confidence = 1.0"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        for i in range(150):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=False,
            ))
        result = analyzer.analyze()
        assert result.confidence == 1.0


# ─────────────────────────────────────────
#  滑动窗口与过期清理
# ─────────────────────────────────────────

class TestSlidingWindow:
    def test_events_outside_window_excluded(self):
        """窗口外的事件不参与分析"""
        analyzer = RateLimitAnalyzer("test", window_seconds=3600)  # 1h 窗口
        now = time.time()
        # 窗口内：50 个成功
        for i in range(50):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=False,
            ))
        # 窗口外：100 个限流
        for i in range(100):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 7200 - i,  # 2h 前
                is_rate_limit=True,
            ))
        result = analyzer.analyze()
        assert result.total_rate_limits_window == 0  # 窗口内无限流
        assert result.confidence == 0.5  # 50 个样本

    def test_cleanup_removes_expired(self):
        """cleanup 清理过期事件"""
        analyzer = RateLimitAnalyzer("test", window_seconds=3600)
        now = time.time()
        # 窗口内
        for i in range(10):
            analyzer.record_request(is_rate_limit=False)  # 使用 API 记录
        # 手动添加过期事件（在锁内操作）
        with analyzer._lock:
            for i in range(20):
                analyzer._events.appendleft(_RequestEvent(
                    timestamp=now - 7200 - i,
                    is_rate_limit=True,
                ))

        assert analyzer.get_event_count() == 30
        removed = analyzer.cleanup()
        assert removed == 20
        assert analyzer.get_event_count() == 10

    def test_maxlen_eviction(self):
        """deque maxlen 自动淘汰旧事件"""
        analyzer = RateLimitAnalyzer("test", max_events=10)
        now = time.time()
        for i in range(20):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i,
                is_rate_limit=False,
            ))
        assert analyzer.get_event_count() == 10


# ─────────────────────────────────────────
#  当前有效 RPM
# ─────────────────────────────────────────

class TestEffectiveRPM:
    def test_effective_rpm_recent_traffic(self):
        """最近 1h 有流量"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 最近 30 分钟 60 个请求 → 2 RPM
        for i in range(60):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i * 30,  # 每 30s 一个
                is_rate_limit=False,
            ))
        result = analyzer.analyze()
        assert result.current_effective_rpm is not None
        assert result.current_effective_rpm >= 1

    def test_effective_rpm_no_recent(self):
        """最近 1h 无流量"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        # 2h 前的请求
        for i in range(10):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 7200 - i,
                is_rate_limit=False,
            ))
        result = analyzer.analyze()
        assert result.current_effective_rpm is None


# ─────────────────────────────────────────
#  自定义分析窗口
# ─────────────────────────────────────────

class TestCustomWindow:
    def test_analyze_with_7d_window(self):
        """传入 7 天窗口"""
        analyzer = RateLimitAnalyzer("test", window_seconds=7 * 86400)
        now = time.time()
        for i in range(100):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i * 3600,  # 每小时一个
                is_rate_limit=False,
            ))
        result = analyzer.analyze(window_seconds=7 * 86400)
        assert result.analysis_window == "7d"

    def test_analyze_with_short_window(self):
        """传入 2h 窗口"""
        analyzer = RateLimitAnalyzer("test")
        now = time.time()
        for i in range(50):
            analyzer._events.append(_RequestEvent(
                timestamp=now - i * 60,
                is_rate_limit=False,
            ))
        result = analyzer.analyze(window_seconds=7200)
        assert result.analysis_window == "2h"


# ─────────────────────────────────────────
#  线程安全性
# ─────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_record_and_analyze(self):
        """并发记录和分析"""
        analyzer = RateLimitAnalyzer("test")
        errors = []

        def record_worker():
            try:
                for _ in range(100):
                    analyzer.record_success()
                    analyzer.record_rate_limit()
            except Exception as e:
                errors.append(e)

        def analyze_worker():
            try:
                for _ in range(50):
                    analyzer.analyze()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_worker),
            threading.Thread(target=record_worker),
            threading.Thread(target=analyze_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"并发错误: {errors}"
        assert analyzer.get_event_count() > 0

    def test_concurrent_cleanup(self):
        """并发清理"""
        analyzer = RateLimitAnalyzer("test", window_seconds=1)
        now = time.time()
        for i in range(100):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 10 - i,  # 已过期
                is_rate_limit=False,
            ))

        errors = []

        def cleanup_worker():
            try:
                for _ in range(20):
                    analyzer.cleanup()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cleanup_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []


# ─────────────────────────────────────────
#  完整集成场景
# ─────────────────────────────────────────

class TestIntegrationScenario:
    def test_realistic_scenario(self):
        """模拟真实场景：正常流量 → 限流 → 恢复 → 再限流"""
        analyzer = RateLimitAnalyzer("yfinance", window_seconds=7200)
        now = time.time()

        # 阶段 1: 正常流量 (1h 前, 每分钟 5 次)
        for minute in range(30):
            for _ in range(5):
                analyzer._events.append(_RequestEvent(
                    timestamp=now - 3600 - (30 - minute) * 60,
                    is_rate_limit=False,
                ))

        # 阶段 2: 触发限流 (40min 前)
        analyzer._events.append(_RequestEvent(
            timestamp=now - 2400,
            is_rate_limit=True,
        ))
        analyzer._events.append(_RequestEvent(
            timestamp=now - 2370,
            is_rate_limit=True,
        ))

        # 阶段 3: 恢复 (30min 前)
        for _ in range(10):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 1800 + 1,
                is_rate_limit=False,
            ))

        # 阶段 4: 再次限流 (10min 前)
        analyzer._events.append(_RequestEvent(
            timestamp=now - 600,
            is_rate_limit=True,
        ))

        # 阶段 5: 再次恢复 (5min 前)
        for _ in range(20):
            analyzer._events.append(_RequestEvent(
                timestamp=now - 300,
                is_rate_limit=False,
            ))

        result = analyzer.analyze()

        # 验证基本字段填充
        assert result.source == "yfinance"
        assert result.total_rate_limits_window == 3
        assert result.estimated_limit_rpm is not None
        assert result.confidence > 0
        assert result.history is not None
        assert len(result.history) > 0

        # 验证推荐间隔合理
        if result.recommended_interval_seconds is not None:
            assert result.recommended_interval_seconds > 0

        # 验证 to_dict 可序列化
        d = result.to_dict()
        assert d["source"] == "yfinance"
        assert isinstance(d["history"], list)
