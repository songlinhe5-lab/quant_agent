"""
RL-05b: RateLimitAnalyzer 深度单测（补齐分析算法分支覆盖）
=======================================================

覆盖 analyzer.py 中尚未被 test_analyzer.py 触达的分析算法分支:
- analyze() 完整路径（成功/限流/错误事件混合、窗口覆盖 days/hours）
- _calculate_effective_rpm（最近 1h 速率）
- _calculate_recommended_interval（None / 正常值）
- _identify_peak_hours（高峰阈值 / 非高峰）
- _merge_peak_hours（单点 / 区间 / 非相邻）
- _calculate_avg_recovery（限流→成功 / 无成功 / 无限流）
- cleanup() 过期淘汰
- 错误事件不计入限流分析
"""

import time

from backend.services.datasource.analyzer import (
    HourlyBucket,
    RateLimitAnalyzer,
    _RequestEvent,
)


def _ev(ts, is_rate_limit=False, is_error=False):
    return _RequestEvent(timestamp=ts, is_rate_limit=is_rate_limit, is_error=is_error)


class TestAnalyzeFullPath:
    def test_analyze_mixed_events(self):
        a = RateLimitAnalyzer("yf")
        now = time.time()
        evs = [
            _ev(now - 100, is_rate_limit=False),
            _ev(now - 90, is_rate_limit=True),
            _ev(now - 80, is_error=True),
            _ev(now - 70, is_rate_limit=False),
        ]
        a._events.extend(evs)
        res = a.analyze(window_seconds=3600)
        assert res.source == "yf"
        # 错误事件不计入限流总数
        assert res.total_rate_limits_window == 1
        # 成功事件 2 个 → RPM 推测非空
        assert res.estimated_limit_rpm is not None

    def test_analyze_window_days_label(self):
        a = RateLimitAnalyzer("yf")
        a._events.append(_ev(time.time()))
        res = a.analyze(window_seconds=2 * 86400)
        assert res.analysis_window == "2d"

    def test_analyze_window_hours_label(self):
        a = RateLimitAnalyzer("yf")
        a._events.append(_ev(time.time()))
        res = a.analyze(window_seconds=3600)
        assert res.analysis_window == "1h"

    def test_analyze_window_24h_label(self):
        a = RateLimitAnalyzer("yf")
        a._events.append(_ev(time.time()))
        res = a.analyze(window_seconds=86400)
        assert res.analysis_window == "24h"


class TestEffectiveRpm:
    def test_effective_rpm_recent(self):
        now = time.time()
        evs = [_ev(now - i * 10, is_rate_limit=False) for i in range(10)]
        rpm = RateLimitAnalyzer._calculate_effective_rpm(evs, now)
        assert rpm is not None
        assert rpm > 0

    def test_effective_rpm_no_recent(self):
        now = time.time()
        evs = [_ev(now - 7200, is_rate_limit=False)]
        assert RateLimitAnalyzer._calculate_effective_rpm(evs, now) is None


class TestRecommendedInterval:
    def test_none_when_no_rpm(self):
        assert RateLimitAnalyzer._calculate_recommended_interval(None) is None
        assert RateLimitAnalyzer._calculate_recommended_interval(0) is None
        assert RateLimitAnalyzer._calculate_recommended_interval(-1) is None

    def test_interval_with_20pct_margin(self):
        # 60 / (rpm * 0.8)
        assert RateLimitAnalyzer._calculate_recommended_interval(60) == 60.0 / 48.0


class TestIdentifyPeakHours:
    def test_peak_detected_above_threshold(self):
        evs = []
        base = 9 * 3600 + 5  # hour 09
        for _ in range(100):
            evs.append(_ev(base, is_rate_limit=False))
        for _ in range(10):  # 10% 限流率 → 高峰
            evs.append(_ev(base, is_rate_limit=True))
        peaks, history = RateLimitAnalyzer._identify_peak_hours(evs, cutoff=0, now=base + 1)
        assert "09:00-10:00" in peaks
        assert any(h["hour"] == "09:00" for h in history)

    def test_no_peak_below_threshold(self):
        evs = []
        base = 10 * 3600 + 5
        for _ in range(100):
            evs.append(_ev(base, is_rate_limit=False))
        for _ in range(2):  # 2% 限流率 → 非高峰
            evs.append(_ev(base, is_rate_limit=True))
        peaks, _ = RateLimitAnalyzer._identify_peak_hours(evs, cutoff=0, now=base + 1)
        assert "10:00-11:00" not in peaks

    def test_history_records_all_buckets(self):
        evs = [_ev(9 * 3600 + 5, is_rate_limit=False), _ev(14 * 3600 + 5, is_rate_limit=False)]
        _, history = RateLimitAnalyzer._identify_peak_hours(evs, cutoff=0, now=15 * 3600)
        hours = {h["hour"] for h in history}
        assert "09:00" in hours and "14:00" in hours


class TestMergePeakHours:
    def test_single_peak(self):
        assert RateLimitAnalyzer._merge_peak_hours(["09:00"]) == ["09:00-10:00"]

    def test_adjacent_range(self):
        assert RateLimitAnalyzer._merge_peak_hours(["09:00", "10:00", "11:00"]) == ["09:00-12:00"]

    def test_non_adjacent(self):
        assert RateLimitAnalyzer._merge_peak_hours(["09:00", "14:00"]) == [
            "09:00-10:00",
            "14:00-15:00",
        ]

    def test_empty(self):
        assert RateLimitAnalyzer._merge_peak_hours([]) == []


class TestAvgRecovery:
    def test_recovery_between_rate_limit_and_success(self):
        rl = _ev(1000.0, is_rate_limit=True)
        succ = _ev(1062.5, is_rate_limit=False)
        val = RateLimitAnalyzer._calculate_avg_recovery([rl], [succ])
        assert val == 62.5

    def test_no_success_returns_none(self):
        rl = _ev(1000.0, is_rate_limit=True)
        assert RateLimitAnalyzer._calculate_avg_recovery([rl], []) is None

    def test_no_rate_limit_returns_none(self):
        succ = _ev(1000.0, is_rate_limit=False)
        assert RateLimitAnalyzer._calculate_avg_recovery([], [succ]) is None

    def test_recovery_takes_first_success_after(self):
        rl = _ev(1000.0, is_rate_limit=True)
        before = _ev(900.0, is_rate_limit=False)
        after = _ev(1010.0, is_rate_limit=False)
        val = RateLimitAnalyzer._calculate_avg_recovery([rl], [before, after])
        assert val == 10.0


class TestCleanupAndErrors:
    def test_cleanup_removes_expired(self):
        a = RateLimitAnalyzer("yf", window_seconds=100)
        a._events.append(_ev(time.time() - 10000, is_rate_limit=False))  # 远超窗口
        a._events.append(_ev(time.time(), is_rate_limit=False))  # 在窗口内
        removed = a.cleanup()
        assert removed == 1
        assert a.get_event_count() == 1

    def test_cleanup_no_expired(self):
        a = RateLimitAnalyzer("yf", window_seconds=100000)
        a._events.append(_ev(time.time()))
        assert a.cleanup() == 0

    def test_error_events_excluded_from_success_and_limits(self):
        a = RateLimitAnalyzer("yf")
        now = time.time()
        a._events.extend(
            [
                _ev(now - 10, is_error=True),
                _ev(now - 9, is_error=True),
            ]
        )
        res = a.analyze(window_seconds=3600)
        # 仅错误事件：无限流、无成功 → RPM 推测/推荐间隔/恢复均为 None
        assert res.total_rate_limits_window == 0
        assert res.estimated_limit_rpm is None
        assert res.recommended_interval_seconds is None
        assert res.avg_recovery_seconds is None


class TestHourlyBucketEdge:
    def test_limit_ratio_zero(self):
        b = HourlyBucket(hour_label="00:00")
        assert b.limit_ratio == 0.0
