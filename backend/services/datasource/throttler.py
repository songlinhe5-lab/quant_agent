"""
RateLimitThrottler — 退避引擎
==============================

每个数据源实例持有一个 Throttler，在 fetch() 调用前检查是否处于退避期。
退避期内直接返回 STALE 缓存，不发起真实请求。

退避策略:
  - none:        不降速
  - linear:      wait = base_delay + step * consecutive_count
  - exponential: wait = base_delay * 2^consecutive_count (上限 max_delay)
  - adaptive:    根据历史限流频率动态调整（默认）

设计文档: docs/14 §十二
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections import deque
from enum import Enum
from typing import Optional

from . import ErrorInfo, RateLimitStatus

logger = logging.getLogger(__name__)

# Prometheus 指标（延迟导入避免循环依赖）
_DS_RATE_LIMIT_TOTAL = None
_DS_RATE_LIMIT_THROTTLED = None
_DS_RATE_LIMIT_ESTIMATED_RPM = None
_DS_RATE_LIMIT_EFFECTIVE_RPM = None
_DS_BACKOFF_STATE = None


def _init_metrics():
    """懒加载 Prometheus 指标（首次调用时导入）"""
    global _DS_RATE_LIMIT_TOTAL, _DS_RATE_LIMIT_THROTTLED
    global _DS_RATE_LIMIT_ESTIMATED_RPM, _DS_RATE_LIMIT_EFFECTIVE_RPM, _DS_BACKOFF_STATE
    if _DS_RATE_LIMIT_TOTAL is not None:
        return
    try:
        from backend.core.metrics import (
            DS_BACKOFF_STATE,
            DS_RATE_LIMIT_EFFECTIVE_RPM,
            DS_RATE_LIMIT_ESTIMATED_RPM,
            DS_RATE_LIMIT_THROTTLED_SECONDS,
            DS_RATE_LIMIT_TOTAL,
        )

        _DS_RATE_LIMIT_TOTAL = DS_RATE_LIMIT_TOTAL
        _DS_RATE_LIMIT_THROTTLED = DS_RATE_LIMIT_THROTTLED_SECONDS
        _DS_RATE_LIMIT_ESTIMATED_RPM = DS_RATE_LIMIT_ESTIMATED_RPM
        _DS_RATE_LIMIT_EFFECTIVE_RPM = DS_RATE_LIMIT_EFFECTIVE_RPM
        _DS_BACKOFF_STATE = DS_BACKOFF_STATE
    except ImportError:
        pass


# 退避策略 → Prometheus 数值映射
_BACKOFF_STATE_MAP = {
    "none": 0,
    "linear": 1,
    "exponential": 2,
    "adaptive": 3,
}


# ─────────────────────────────────────────
#  退避策略枚举
# ─────────────────────────────────────────


class BackoffStrategy(str, Enum):
    """退避策略"""

    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    ADAPTIVE = "adaptive"


# ─────────────────────────────────────────
#  配置解析
# ─────────────────────────────────────────


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return default


def _env_strategy(name: str, default: BackoffStrategy) -> BackoffStrategy:
    val = os.getenv(name)
    if val is not None:
        try:
            return BackoffStrategy(val.lower())
        except ValueError:
            pass
    return default


# ─────────────────────────────────────────
#  RateLimitThrottler
# ─────────────────────────────────────────


class RateLimitThrottler:
    """
    退避引擎。

    线程安全：所有状态变更均在 _lock 保护下完成。
    可在多线程环境（如 Futu SDK 回调线程 + asyncio 事件循环线程）中安全使用。

    用法:
        throttler = RateLimitThrottler("yfinance")

        # fetch() 前检查
        if throttler.should_throttle():
            return Result.make_degraded(stale_cache, source="yfinance")

        # 发起真实请求...
        result = await do_fetch()

        if result.is_rate_limited:
            throttler.on_rate_limit(result.error)
        else:
            throttler.on_success()
    """

    # 自适应恢复阈值：连续成功 N 次后开始降速
    _ADAPTIVE_RECOVERY_THRESHOLD = 10
    # 自适应恢复衰减系数
    _ADAPTIVE_DECAY_FACTOR = 0.8
    # 退避归零阈值
    _THROTTLE_EPSILON = 0.1

    def __init__(
        self,
        source_name: str,
        strategy: Optional[BackoffStrategy] = None,
        base_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        jitter: Optional[bool] = None,
    ):
        """
        Args:
            source_name: 数据源名称（用于环境变量查找 DATASOURCE_{NAME}_*）
            strategy: 退避策略，默认从环境变量读取，fallback=adaptive
            base_delay: 基础退避延迟（秒），默认 2.0
            max_delay: 最大退避延迟（秒），默认 300.0
            jitter: 是否添加随机抖动，默认 true
        """
        prefix = f"DATASOURCE_{source_name.upper()}"

        self._source_name = source_name
        self._strategy = (
            strategy if strategy is not None else _env_strategy(f"{prefix}_BACKOFF_STRATEGY", BackoffStrategy.ADAPTIVE)
        )
        self._base_delay = base_delay if base_delay is not None else _env_float(f"{prefix}_BACKOFF_BASE_DELAY", 2.0)
        self._max_delay = max_delay if max_delay is not None else _env_float(f"{prefix}_BACKOFF_MAX_DELAY", 300.0)
        self._jitter = jitter if jitter is not None else _env_bool(f"{prefix}_BACKOFF_JITTER", True)

        # ── 内部状态（均受 _lock 保护）──
        self._lock = threading.Lock()
        self._consecutive_limits: int = 0
        self._success_streak: int = 0
        self._request_interval: float = 0.0  # 当前请求间隔（秒）
        self._throttle_until: float = 0.0  # 退避截止时间戳
        self._estimated_limit_rpm: Optional[int] = None

        # ── 限流事件历史（用于统计 1h 内限流次数）──
        self._rate_limit_events: deque[float] = deque(maxlen=1000)

    # ─────────────────────────────────────
    #  核心 API
    # ─────────────────────────────────────

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def strategy(self) -> BackoffStrategy:
        return self._strategy

    def should_throttle(self) -> bool:
        """
        检查当前是否处于退避期。

        退避期内 fetch() 应直接返回 STALE 缓存，不发起真实请求。
        """
        with self._lock:
            if self._strategy == BackoffStrategy.NONE:
                return False
            return time.monotonic() < self._throttle_until

    def remaining_throttle_seconds(self) -> float:
        """返回剩余退避秒数。如果不在退避期，返回 0.0"""
        with self._lock:
            remaining = self._throttle_until - time.monotonic()
            return max(0.0, remaining)

    def on_rate_limit(self, error: Optional[ErrorInfo] = None) -> float:
        """
        限流触发时调用。计算退避时间并进入退避状态。

        Args:
            error: 触发限流的 ErrorInfo（可选，用于提取 retry_after）

        Returns:
            计算的退避秒数
        """
        with self._lock:
            self._consecutive_limits += 1
            self._success_streak = 0

            # 记录限流事件
            now = time.monotonic()
            self._rate_limit_events.append(now)

            # Prometheus: 限流计数 +1
            _init_metrics()
            if _DS_RATE_LIMIT_TOTAL is not None:
                category = "rate_limit"
                if error and error.category:
                    category = error.category.value
                _DS_RATE_LIMIT_TOTAL.labels(source=self._source_name, category=category).inc()

            # 计算退避时间
            wait_seconds = self._calculate_wait(error)

            # 进入退避状态
            self._throttle_until = now + wait_seconds

            # 推测限流 RPM
            if wait_seconds > 0:
                self._estimated_limit_rpm = int(60.0 / wait_seconds)
            else:
                self._estimated_limit_rpm = None

            # 更新 Prometheus 退避指标
            _init_metrics()
            if _DS_RATE_LIMIT_THROTTLED is not None:
                _DS_RATE_LIMIT_THROTTLED.labels(source=self._source_name).set(wait_seconds)
            if _DS_RATE_LIMIT_ESTIMATED_RPM is not None and self._estimated_limit_rpm:
                _DS_RATE_LIMIT_ESTIMATED_RPM.labels(source=self._source_name).set(self._estimated_limit_rpm)
            if _DS_BACKOFF_STATE is not None:
                _DS_BACKOFF_STATE.labels(source=self._source_name).set(_BACKOFF_STATE_MAP.get(self._strategy.value, 0))

            logger.info(
                f"[Throttler:{self._source_name}] 限流触发，进入退避: "
                f"strategy={self._strategy.value}, wait={wait_seconds:.1f}s, "
                f"consecutive={self._consecutive_limits}"
            )

            # RL-11: 通知告警监控器
            try:
                from backend.services.datasource.alert_monitor import rate_limit_alert_monitor

                error_category = error.category.value if error and error.category else "rate_limit"
                rate_limit_alert_monitor.on_rate_limit_event(
                    source=self._source_name,
                    category=error_category,
                    wait_seconds=wait_seconds,
                    consecutive_rate_limits=self._consecutive_limits,
                )
            except Exception as e:
                logger.debug(f"[RL-11] 告警监控器调用失败: {e}")

            return wait_seconds

    def on_success(self) -> None:
        """
        请求成功时调用。
        连续成功达到阈值后，逐步降低退避间隔（恢复机制）。
        """
        with self._lock:
            if self._strategy == BackoffStrategy.NONE:
                return

            self._success_streak += 1

            # 自适应策略：连续成功 N 次后逐步降速
            if self._success_streak >= self._ADAPTIVE_RECOVERY_THRESHOLD:
                self._request_interval = max(
                    self._request_interval * self._ADAPTIVE_DECAY_FACTOR,
                    0.0,
                )
                self._consecutive_limits = max(self._consecutive_limits - 1, 0)
                self._success_streak = 0  # 重置，等待下一轮

                # 退避间隔低于阈值则归零
                if self._request_interval < self._THROTTLE_EPSILON:
                    self._request_interval = 0.0
                    self._consecutive_limits = 0
                    self._estimated_limit_rpm = None
                    logger.debug(f"[Throttler:{self._source_name}] 退避归零，恢复正常速率")

    def reset(self) -> None:
        """手动重置所有状态"""
        with self._lock:
            self._consecutive_limits = 0
            self._success_streak = 0
            self._request_interval = 0.0
            self._throttle_until = 0.0
            self._estimated_limit_rpm = None
            self._rate_limit_events.clear()

    def get_status(self) -> RateLimitStatus:
        """获取当前限流状态快照"""
        with self._lock:
            now = time.monotonic()
            is_throttled = self._strategy != BackoffStrategy.NONE and now < self._throttle_until

            # 统计过去 1 小时内的限流次数
            one_hour_ago = now - 3600.0
            total_1h = sum(1 for t in self._rate_limit_events if t >= one_hour_ago)

            # 计算有效 RPM
            effective_rpm = None
            if self._request_interval > 0:
                effective_rpm = int(60.0 / self._request_interval)

            status = RateLimitStatus(
                is_throttled=is_throttled,
                throttle_until=(time.time() + (self._throttle_until - now) if is_throttled else None),
                estimated_rpm=effective_rpm,
                estimated_limit_rpm=self._estimated_limit_rpm,
                consecutive_rate_limits=self._consecutive_limits,
                total_rate_limits_1h=total_1h,
                backoff_strategy=self._strategy.value,
            )

            # 更新 Prometheus gauge 指标
            _init_metrics()
            if _DS_RATE_LIMIT_THROTTLED is not None:
                remaining = max(0.0, self._throttle_until - now) if is_throttled else 0.0
                _DS_RATE_LIMIT_THROTTLED.labels(source=self._source_name).set(remaining)
            if _DS_RATE_LIMIT_EFFECTIVE_RPM is not None:
                _DS_RATE_LIMIT_EFFECTIVE_RPM.labels(source=self._source_name).set(effective_rpm if effective_rpm else 0)

            return status

    # ─────────────────────────────────────
    #  内部算法
    # ─────────────────────────────────────

    def _calculate_wait(self, error: Optional[ErrorInfo] = None) -> float:
        """
        计算退避等待秒数（在 _lock 内调用）。

        优先级:
        1. 服务端 Retry-After header → 直接采纳
        2. 策略计算值
        """
        # 1. 服务端明确告知等待时间
        if error and error.rate_limit_info and error.rate_limit_info.retry_after_seconds:
            retry_after = error.rate_limit_info.retry_after_seconds
            # 即使采纳服务端建议，也不超过 max_delay
            return min(retry_after, self._max_delay)

        # 2. 按策略计算
        n = self._consecutive_limits

        if self._strategy == BackoffStrategy.NONE:
            return 0.0

        elif self._strategy == BackoffStrategy.LINEAR:
            # wait = base_delay + step * consecutive_count
            wait = self._base_delay + self._base_delay * n

        elif self._strategy == BackoffStrategy.EXPONENTIAL:
            # wait = base_delay * 2^consecutive_count
            wait = self._base_delay * (2**n)

        elif self._strategy == BackoffStrategy.ADAPTIVE:
            # 自适应：指数退避 + 动态调整
            wait = self._base_delay * (2**n)
            # 如果有历史 request_interval，作为下限参考
            if self._request_interval > 0:
                wait = max(wait, self._request_interval)

        else:
            wait = self._base_delay

        # 应用上限
        wait = min(wait, self._max_delay)

        # 添加抖动（防雷群效应）
        if self._jitter:
            wait += random.uniform(0, 1.0)

        # 更新 request_interval（自适应策略用）
        if self._strategy == BackoffStrategy.ADAPTIVE:
            self._request_interval = wait

        return wait

    # ─────────────────────────────────────
    #  调试 / 可观测性
    # ─────────────────────────────────────

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"RateLimitThrottler("
                f"source={self._source_name!r}, "
                f"strategy={self._strategy.value}, "
                f"throttled={time.monotonic() < self._throttle_until}, "
                f"consecutive_limits={self._consecutive_limits})"
            )
