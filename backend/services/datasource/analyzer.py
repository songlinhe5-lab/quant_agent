"""
RateLimitAnalyzer — 限流频率动态分析器
==========================================

基于过去 24h 的请求/限流事件时间序列，动态推测限流模式：
  - 推测限流阈值 RPM（成功请求 RPM 的 P75）
  - 推荐安全请求间隔（保留 20% 安全裕度）
  - 识别限流高峰时段（限流率 > 5% 的小时）
  - 平均恢复时间（限流事件 → 下一次成功请求的平均间隔）
  - 推测可信度（样本越多越可信）

设计文档: docs/14 §12.3
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  分析结果数据结构
# ─────────────────────────────────────────

@dataclass(slots=True)
class HourlyBucket:
    """
    单小时统计桶。

    - requests:     该小时总请求数
    - rate_limits:  该小时限流次数
    - limit_ratio:  限流率 (rate_limits / requests)
    """

    hour_label: str  # "09:00", "10:00" 等
    requests: int = 0
    rate_limits: int = 0

    @property
    def limit_ratio(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.rate_limits / self.requests


@dataclass(slots=True)
class RateLimitAnalysis:
    """
    限流频率分析结果。

    字段说明:
    - source:                   数据源名称
    - analysis_window:          分析窗口描述（如 "24h"）
    - estimated_limit_rpm:      推测的限流阈值 RPM（成功请求 RPM 的 P75）
    - current_effective_rpm:    当前有效 RPM（最近 1h 的实际请求速率）
    - total_rate_limits_window: 分析窗口内总限流次数
    - peak_hours:               限流高峰时段列表（如 ["09:00-11:00", "14:00-16:00"]）
    - avg_recovery_seconds:     平均恢复时间（限流 → 下一次成功的平均秒数）
    - recommended_interval_seconds: 推荐的安全请求间隔（秒）
    - confidence:               推测可信度 (0.0 ~ 1.0)
    - history:                  每小时统计明细列表
    """

    source: str
    analysis_window: str = "24h"
    estimated_limit_rpm: Optional[int] = None
    current_effective_rpm: Optional[int] = None
    total_rate_limits_window: int = 0
    peak_hours: list[str] = field(default_factory=list)
    avg_recovery_seconds: Optional[float] = None
    recommended_interval_seconds: Optional[float] = None
    confidence: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "analysis_window": self.analysis_window,
            "estimated_limit_rpm": self.estimated_limit_rpm,
            "current_effective_rpm": self.current_effective_rpm,
            "total_rate_limits_window": self.total_rate_limits_window,
            "peak_hours": self.peak_hours,
            "avg_recovery_seconds": (
                round(self.avg_recovery_seconds, 2)
                if self.avg_recovery_seconds is not None
                else None
            ),
            "recommended_interval_seconds": (
                round(self.recommended_interval_seconds, 2)
                if self.recommended_interval_seconds is not None
                else None
            ),
            "confidence": round(self.confidence, 3),
            "history": self.history,
        }


# ─────────────────────────────────────────
#  请求事件记录
# ─────────────────────────────────────────

@dataclass(slots=True)
class _RequestEvent:
    """单条请求事件记录（内部使用）"""
    timestamp: float  # time.time() 绝对时间戳
    is_rate_limit: bool  # True=限流, False=成功请求
    is_error: bool = False  # True=普通错误（不计入限流分析）


# ─────────────────────────────────────────
#  RateLimitAnalyzer
# ─────────────────────────────────────────

# 默认分析窗口 24h
_DEFAULT_WINDOW_SECONDS = 24 * 3600

# 最大存储事件数（控制内存：24h 内最多 10000 条事件 ≈ 约 200KB）
_DEFAULT_MAX_EVENTS = 10000

# 高峰时段阈值：限流率超过此比例视为高峰
_PEAK_HOUR_RATIO_THRESHOLD = 0.05

# 可信度样本阈值：达到此数量后 confidence=1.0
_CONFIDENCE_SAMPLE_SIZE = 100


class RateLimitAnalyzer:
    """
    限流频率动态分析器。

    每个数据源持有一个 Analyzer，记录请求/限流事件时间序列，
    基于滑动窗口统计推测限流模式。

    线程安全：所有状态变更均在 _lock 保护下完成。

    用法:
        analyzer = RateLimitAnalyzer("yfinance")

        # 每次请求后记录
        analyzer.record_request(is_rate_limit=False)   # 成功
        analyzer.record_request(is_rate_limit=True)    # 限流

        # 查询分析结果
        analysis = analyzer.analyze()
        print(analysis.estimated_limit_rpm)
        print(analysis.recommended_interval_seconds)
    """

    def __init__(
        self,
        source_name: str,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ):
        """
        Args:
            source_name:    数据源名称
            window_seconds: 分析窗口（秒），默认 24h
            max_events:     最大存储事件数，默认 10000（内存约 200KB）
        """
        self._source_name = source_name
        self._window_seconds = window_seconds
        self._max_events = max_events

        # ── 内部状态（均受 _lock 保护）──
        self._lock = threading.Lock()
        # 请求事件时间序列（按时间顺序，deque 自动淘汰旧事件）
        self._events: deque[_RequestEvent] = deque(maxlen=max_events)

    @property
    def source_name(self) -> str:
        return self._source_name

    # ─────────────────────────────────────
    #  事件记录 API
    # ─────────────────────────────────────

    def record_request(self, is_rate_limit: bool = False, is_error: bool = False) -> None:
        """
        记录一次请求事件。

        Args:
            is_rate_limit: 是否为限流事件
            is_error:      是否为普通错误（不计入限流分析，但记录用于统计）
        """
        event = _RequestEvent(
            timestamp=time.time(),
            is_rate_limit=is_rate_limit,
            is_error=is_error,
        )
        with self._lock:
            self._events.append(event)

    def record_success(self) -> None:
        """记录一次成功请求"""
        self.record_request(is_rate_limit=False, is_error=False)

    def record_rate_limit(self) -> None:
        """记录一次限流事件"""
        self.record_request(is_rate_limit=True, is_error=False)

    # ─────────────────────────────────────
    #  分析 API
    # ─────────────────────────────────────

    def analyze(self, window_seconds: Optional[float] = None) -> RateLimitAnalysis:
        """
        执行限流频率分析。

        Args:
            window_seconds: 可选，覆盖默认分析窗口（如传入 7*86400 分析 7 天）

        Returns:
            RateLimitAnalysis 分析结果
        """
        window = window_seconds if window_seconds is not None else self._window_seconds
        now = time.time()
        cutoff = now - window

        with self._lock:
            # 1. 过滤出窗口内的事件
            window_events = [e for e in self._events if e.timestamp >= cutoff]

        # 无数据时返回空结果
        if not window_events:
            return RateLimitAnalysis(source=self._source_name)

        # 2. 分类统计
        total_rate_limits = sum(1 for e in window_events if e.is_rate_limit)
        success_events = [e for e in window_events if not e.is_rate_limit and not e.is_error]
        rate_limit_events = [e for e in window_events if e.is_rate_limit]

        # 3. 推测限流 RPM（成功请求的每分钟速率 P75）
        estimated_limit_rpm = self._estimate_limit_rpm(success_events, window)

        # 4. 当前有效 RPM（最近 1h 的实际请求速率）
        current_effective_rpm = self._calculate_effective_rpm(window_events, now)

        # 5. 推荐安全间隔
        recommended_interval = self._calculate_recommended_interval(estimated_limit_rpm)

        # 6. 高峰时段识别
        peak_hours, history = self._identify_peak_hours(window_events, cutoff, now)

        # 7. 平均恢复时间
        avg_recovery = self._calculate_avg_recovery(rate_limit_events, success_events)

        # 8. 可信度
        sample_count = len(window_events)
        confidence = min(sample_count / _CONFIDENCE_SAMPLE_SIZE, 1.0)

        # 9. 窗口描述
        if window >= 86400:
            days = int(window / 86400)
            analysis_window = f"{days}d" if days > 1 else "24h"
        else:
            hours = int(window / 3600)
            analysis_window = f"{hours}h"

        return RateLimitAnalysis(
            source=self._source_name,
            analysis_window=analysis_window,
            estimated_limit_rpm=estimated_limit_rpm,
            current_effective_rpm=current_effective_rpm,
            total_rate_limits_window=total_rate_limits,
            peak_hours=peak_hours,
            avg_recovery_seconds=avg_recovery,
            recommended_interval_seconds=recommended_interval,
            confidence=confidence,
            history=history,
        )

    # ─────────────────────────────────────
    #  内部算法
    # ─────────────────────────────────────

    @staticmethod
    def _estimate_limit_rpm(
        success_events: list[_RequestEvent],
        window_seconds: float,
    ) -> Optional[int]:
        """
        推测限流阈值 RPM。

        算法：将窗口按分钟分桶，统计每分钟成功请求数，取 P75（第 75 百分位）。
        P75 排除偶发高峰，更接近真实限流阈值。
        """
        if not success_events:
            return None

        # 按分钟分桶
        minute_buckets: dict[int, int] = {}
        for e in success_events:
            minute_key = int(e.timestamp // 60)
            minute_buckets[minute_key] = minute_buckets.get(minute_key, 0) + 1

        if not minute_buckets:
            return None

        # 取所有分钟的请求数，计算 P75
        counts = sorted(minute_buckets.values())
        n = len(counts)
        p75_index = min(int(n * 0.75), n - 1)
        p75 = counts[p75_index]

        return max(p75, 1)  # 至少为 1

    @staticmethod
    def _calculate_effective_rpm(
        window_events: list[_RequestEvent],
        now: float,
    ) -> Optional[int]:
        """
        计算当前有效 RPM（最近 1h 的实际请求速率）。
        """
        one_hour_ago = now - 3600.0
        recent = [e for e in window_events if e.timestamp >= one_hour_ago]
        if not recent:
            return None
        # 实际经过的分钟数（至少 1 分钟）
        elapsed_minutes = max((now - recent[0].timestamp) / 60.0, 1.0)
        return int(len(recent) / elapsed_minutes)

    @staticmethod
    def _calculate_recommended_interval(estimated_limit_rpm: Optional[int]) -> Optional[float]:
        """
        计算推荐安全请求间隔。

        公式: 60 / (estimated_limit_rpm * 0.8)  # 保留 20% 安全裕度
        """
        if estimated_limit_rpm is None or estimated_limit_rpm <= 0:
            return None
        safe_rpm = estimated_limit_rpm * 0.8
        return 60.0 / safe_rpm

    @staticmethod
    def _identify_peak_hours(
        window_events: list[_RequestEvent],
        cutoff: float,
        now: float,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """
        识别限流高峰时段。

        按小时分桶，限流率 > 5% 的时段标记为高峰。
        返回 (peak_hours_list, history_detail)。
        """
        # 按小时分桶
        hour_buckets: dict[str, HourlyBucket] = {}
        for e in window_events:
            # 将时间戳转为小时标签（UTC 小时）
            hour_of_day = int((e.timestamp % 86400) // 3600)
            hour_label = f"{hour_of_day:02d}:00"

            if hour_label not in hour_buckets:
                hour_buckets[hour_label] = HourlyBucket(hour_label=hour_label)

            bucket = hour_buckets[hour_label]
            bucket.requests += 1
            if e.is_rate_limit:
                bucket.rate_limits += 1

        # 排序并识别高峰
        sorted_hours = sorted(hour_buckets.values(), key=lambda b: b.hour_label)
        peak_hours: list[str] = []
        history: list[dict[str, Any]] = []

        for bucket in sorted_hours:
            history.append({
                "hour": bucket.hour_label,
                "requests": bucket.requests,
                "rate_limits": bucket.rate_limits,
                "limit_ratio": round(bucket.limit_ratio, 4),
            })
            if bucket.limit_ratio > _PEAK_HOUR_RATIO_THRESHOLD:
                peak_hours.append(bucket.hour_label)

        # 合并相邻高峰时段为区间（如 "09:00", "10:00" → "09:00-11:00"）
        merged_peaks = RateLimitAnalyzer._merge_peak_hours(peak_hours)

        return merged_peaks, history

    @staticmethod
    def _merge_peak_hours(peak_hours: list[str]) -> list[str]:
        """
        合并相邻的高峰时段为区间。

        例如: ["09:00", "10:00"] → ["09:00-11:00"]
              ["14:00"] → ["14:00-15:00"]
        """
        if not peak_hours:
            return []

        # 提取小时数并排序
        hours_int = sorted(int(h.split(":")[0]) for h in peak_hours)
        ranges: list[tuple[int, int]] = []
        start = hours_int[0]
        end = hours_int[0]

        for h in hours_int[1:]:
            if h == end + 1:
                end = h
            else:
                ranges.append((start, end))
                start = h
                end = h
        ranges.append((start, end))

        # 格式化
        result = []
        for s, e in ranges:
            if s == e:
                result.append(f"{s:02d}:00-{(s + 1) % 24:02d}:00")
            else:
                result.append(f"{s:02d}:00-{(e + 1) % 24:02d}:00")
        return result

    @staticmethod
    def _calculate_avg_recovery(
        rate_limit_events: list[_RequestEvent],
        success_events: list[_RequestEvent],
    ) -> Optional[float]:
        """
        计算平均恢复时间。

        对每个限流事件，找到其后最近的成功请求，计算时间差。
        取所有恢复时间的平均值。
        """
        if not rate_limit_events or not success_events:
            return None

        # 成功事件按时间排序
        sorted_success = sorted(success_events, key=lambda e: e.timestamp)
        recovery_times: list[float] = []

        for rl_event in rate_limit_events:
            rl_ts = rl_event.timestamp
            # 二分查找限流后第一个成功请求
            recovery_ts = None
            for s in sorted_success:
                if s.timestamp > rl_ts:
                    recovery_ts = s.timestamp
                    break

            if recovery_ts is not None:
                recovery_times.append(recovery_ts - rl_ts)

        if not recovery_times:
            return None

        return sum(recovery_times) / len(recovery_times)

    # ─────────────────────────────────────
    #  清理 / 可观测性
    # ─────────────────────────────────────

    def cleanup(self) -> int:
        """
        清理过期事件，释放内存。

        Returns:
            清理的事件数量
        """
        cutoff = time.time() - self._window_seconds
        with self._lock:
            before = len(self._events)
            while self._events and self._events[0].timestamp < cutoff:
                self._events.popleft()
            removed = before - len(self._events)
            if removed > 0:
                logger.debug(
                    f"[Analyzer:{self._source_name}] 清理 {removed} 条过期事件"
                )
            return removed

    def get_event_count(self) -> int:
        """获取当前存储的事件总数（供监控使用）"""
        with self._lock:
            return len(self._events)

    def reset(self) -> None:
        """手动重置所有事件记录"""
        with self._lock:
            self._events.clear()
        logger.debug(f"[Analyzer:{self._source_name}] 已重置")

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"RateLimitAnalyzer("
                f"source={self._source_name!r}, "
                f"events={len(self._events)}, "
                f"window={self._window_seconds / 3600:.0f}h)"
            )
