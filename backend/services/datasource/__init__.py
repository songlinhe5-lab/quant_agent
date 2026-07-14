"""
数据源框架 — 统一数据模型
===========================

定义所有数据源共享的 Result / ErrorInfo / RateLimitInfo 结构，
以及错误分类体系（ErrorCategory）。

设计文档: docs/14. 分布式数据源服务架构.md §二、§十二
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ─────────────────────────────────────────
#  错误分类体系 (ErrorCategory)
# ─────────────────────────────────────────


class ErrorCategory(str, Enum):
    """
    数据源错误分类。

    限流类错误与普通错误有本质区别：
    - 普通错误 (normal) → 计入熔断器失败计数
    - 限流类错误 (rate_limit / quota_exhausted / ip_blocked) → 触发独立退避机制，不计入熔断器
    """

    NORMAL = "normal"
    """普通业务/网络错误：参数错误、连接超时、数据解析失败"""

    RATE_LIMIT = "rate_limit"
    """频率限流：HTTP 429、Yahoo Too Many Requests"""

    QUOTA_EXHAUSTED = "quota_exhausted"
    """配额耗尽：Finnhub 日调用上限、免费 tier 用完"""

    IP_BLOCKED = "ip_blocked"
    """IP 封禁：Yahoo 封 IP 段、反爬触发"""


# ─────────────────────────────────────────
#  限流详情 (RateLimitInfo)
# ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """
    限流详情，仅在 category != "normal" 时填充。

    字段说明:
    - retry_after_seconds: 服务端建议的重试等待秒数（来自 Retry-After header）
    - estimated_reset_seconds: 预估限流窗口重置时间
    - current_rpm: 当前推测的每分钟请求数
    - limit_rpm: 推测的限流阈值（每分钟请求数）
    - source_header: 原始限流响应头信息
    """

    retry_after_seconds: Optional[float] = None
    estimated_reset_seconds: Optional[float] = None
    current_rpm: Optional[int] = None
    limit_rpm: Optional[int] = None
    source_header: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_after_seconds": self.retry_after_seconds,
            "estimated_reset_seconds": self.estimated_reset_seconds,
            "current_rpm": self.current_rpm,
            "limit_rpm": self.limit_rpm,
            "source_header": self.source_header,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional[RateLimitInfo]:
        if data is None:
            return None
        return cls(
            retry_after_seconds=data.get("retry_after_seconds"),
            estimated_reset_seconds=data.get("estimated_reset_seconds"),
            current_rpm=data.get("current_rpm"),
            limit_rpm=data.get("limit_rpm"),
            source_header=data.get("source_header"),
        )


# ─────────────────────────────────────────
#  错误详情 (ErrorInfo)
# ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """
    数据源错误详情。

    category 字段区分限流类错误与普通错误：
    - normal: 计入熔断器失败计数
    - rate_limit / quota_exhausted / ip_blocked: 触发独立退避机制
    """

    code: str
    """错误码 (如 "FUTU_DISCONNECTED", "YFINANCE_429")"""

    message: str
    """人类可读的错误描述"""

    retryable: bool = False
    """是否可重试（限流/网络错误=可重试，参数错误=不可重试）"""

    category: ErrorCategory = ErrorCategory.NORMAL
    """错误分类：区分限流类错误与普通错误"""

    rate_limit_info: Optional[RateLimitInfo] = None
    """限流详情，仅在 category != "normal" 时填充"""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "category": self.category.value,
        }
        if self.rate_limit_info is not None:
            result["rate_limit_info"] = self.rate_limit_info.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional[ErrorInfo]:
        if data is None:
            return None
        return cls(
            code=data.get("code", "UNKNOWN"),
            message=data.get("message", ""),
            retryable=data.get("retryable", False),
            category=ErrorCategory(data.get("category", "normal")),
            rate_limit_info=RateLimitInfo.from_dict(data.get("rate_limit_info")),
        )

    @classmethod
    def normal(cls, code: str, message: str, retryable: bool = False) -> ErrorInfo:
        """快捷构造：普通错误"""
        return cls(code=code, message=message, retryable=retryable, category=ErrorCategory.NORMAL)

    @classmethod
    def rate_limited(
        cls,
        code: str = "RATE_LIMITED",
        message: str = "数据源频率限流",
        retry_after: Optional[float] = None,
        limit_rpm: Optional[int] = None,
        source_header: Optional[str] = None,
    ) -> ErrorInfo:
        """快捷构造：频率限流"""
        return cls(
            code=code,
            message=message,
            retryable=True,
            category=ErrorCategory.RATE_LIMIT,
            rate_limit_info=RateLimitInfo(
                retry_after_seconds=retry_after,
                limit_rpm=limit_rpm,
                source_header=source_header,
            ),
        )

    @classmethod
    def quota_exhausted(
        cls,
        code: str = "QUOTA_EXHAUSTED",
        message: str = "数据源配额已耗尽",
        estimated_reset: Optional[float] = None,
    ) -> ErrorInfo:
        """快捷构造：配额耗尽"""
        return cls(
            code=code,
            message=message,
            retryable=True,
            category=ErrorCategory.QUOTA_EXHAUSTED,
            rate_limit_info=RateLimitInfo(estimated_reset_seconds=estimated_reset),
        )

    @classmethod
    def ip_blocked(
        cls,
        code: str = "IP_BLOCKED",
        message: str = "数据源 IP 被封禁",
        estimated_reset: Optional[float] = None,
    ) -> ErrorInfo:
        """快捷构造：IP 封禁"""
        return cls(
            code=code,
            message=message,
            retryable=True,
            category=ErrorCategory.IP_BLOCKED,
            rate_limit_info=RateLimitInfo(estimated_reset_seconds=estimated_reset),
        )

    @property
    def is_rate_limit_type(self) -> bool:
        """是否为限流类错误（不计入熔断器失败计数）"""
        return self.category != ErrorCategory.NORMAL


# ─────────────────────────────────────────
#  统一返回结构 (Result)
# ─────────────────────────────────────────


class ResultStatus(str, Enum):
    """Result 状态枚举"""

    SUCCESS = "success"
    ERROR = "error"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"


@dataclass(slots=True)
class Result:
    """
    数据源统一返回结构。

    所有数据源的 fetch() 方法必须返回此结构。
    """

    status: ResultStatus
    data: Any = None
    source: str = ""
    latency_ms: float = 0.0
    cached: bool = False
    error: Optional[ErrorInfo] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "data": self.data,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 2),
            "cached": self.cached,
        }
        if self.error is not None:
            result["error"] = self.error.to_dict()
        return result

    @classmethod
    def make_success(cls, data: Any, source: str = "", latency_ms: float = 0.0, cached: bool = False) -> Result:
        """快捷构造：成功"""
        return cls(status=ResultStatus.SUCCESS, data=data, source=source, latency_ms=latency_ms, cached=cached)

    @classmethod
    def make_error(
        cls,
        error: ErrorInfo,
        source: str = "",
        latency_ms: float = 0.0,
    ) -> Result:
        """快捷构造：错误"""
        return cls(status=ResultStatus.ERROR, error=error, source=source, latency_ms=latency_ms)

    @classmethod
    def make_rate_limited(
        cls,
        error: ErrorInfo,
        source: str = "",
        latency_ms: float = 0.0,
    ) -> Result:
        """快捷构造：限流"""
        return cls(status=ResultStatus.RATE_LIMITED, error=error, source=source, latency_ms=latency_ms)

    @classmethod
    def make_degraded(
        cls,
        data: Any,
        source: str = "",
        latency_ms: float = 0.0,
    ) -> Result:
        """快捷构造：降级（返回过期数据）"""
        return cls(status=ResultStatus.DEGRADED, data=data, source=source, latency_ms=latency_ms, cached=True)

    @property
    def is_success(self) -> bool:
        return self.status == ResultStatus.SUCCESS

    @property
    def is_rate_limited(self) -> bool:
        return self.status == ResultStatus.RATE_LIMITED

    @property
    def is_error(self) -> bool:
        return self.status == ResultStatus.ERROR

    @property
    def is_degraded(self) -> bool:
        return self.status == ResultStatus.DEGRADED


# ─────────────────────────────────────────
#  限流状态感知 (RateLimitStatus)
# ─────────────────────────────────────────


@dataclass(slots=True)
class RateLimitStatus:
    """
    数据源限流状态，嵌入 HealthInfo.rate_limit_status。
    """

    is_throttled: bool = False
    throttle_until: Optional[float] = None
    estimated_rpm: Optional[int] = None
    estimated_limit_rpm: Optional[int] = None
    consecutive_rate_limits: int = 0
    total_rate_limits_1h: int = 0
    backoff_strategy: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_throttled": self.is_throttled,
            "throttle_until": self.throttle_until,
            "estimated_rpm": self.estimated_rpm,
            "estimated_limit_rpm": self.estimated_limit_rpm,
            "consecutive_rate_limits": self.consecutive_rate_limits,
            "total_rate_limit_1h": self.total_rate_limits_1h,
            "backoff_strategy": self.backoff_strategy,
        }


# ─────────────────────────────────────────
#  健康信息 (HealthInfo)
# ─────────────────────────────────────────


@dataclass(slots=True)
class HealthInfo:
    """
    数据源健康信息，统一返回结构。
    """

    healthy: bool = True
    mode: str = "internal"
    connected: bool = False
    uptime_seconds: float = 0.0
    last_error: Optional[str] = None
    stats: dict[str, Any] = field(default_factory=dict)
    rate_limit_status: RateLimitStatus = field(default_factory=RateLimitStatus)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "mode": self.mode,
            "connected": self.connected,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "last_error": self.last_error,
            "stats": self.stats,
            "rate_limit_status": self.rate_limit_status.to_dict(),
        }


# ─────────────────────────────────────────
#  错误分类工具函数
# ─────────────────────────────────────────


def classify_http_error(status_code: int, response_headers: Optional[dict] = None) -> ErrorCategory:
    """
    根据 HTTP 状态码和响应头推断错误分类。

    - 429 → rate_limit
    - 403 + 特定 header → ip_blocked
    - 402 / 429 + quota 相关 header → quota_exhausted
    - 其他 → normal
    """
    if status_code == 429:
        # 检查是否是配额耗尽（而非频率限流）
        if response_headers:
            remaining = response_headers.get("X-RateLimit-Remaining", "")
            reset = response_headers.get("X-RateLimit-Reset", "")
            if remaining == "0" and reset:
                # 如果 reset 时间很远（>1h），更可能是配额耗尽
                try:
                    reset_ts = float(reset)
                    if reset_ts - time.time() > 3600:
                        return ErrorCategory.QUOTA_EXHAUSTED
                except (ValueError, TypeError):
                    pass
        return ErrorCategory.RATE_LIMIT

    if status_code == 403:
        if response_headers:
            reason = response_headers.get("X-Block-Reason", "").lower()
            if "rate" in reason or "limit" in reason or "throttl" in reason:
                return ErrorCategory.IP_BLOCKED
        return ErrorCategory.NORMAL

    return ErrorCategory.NORMAL


def parse_retry_after(response_headers: Optional[dict]) -> Optional[float]:
    """从响应头解析 Retry-After 值（秒）"""
    if not response_headers:
        return None
    retry_after = response_headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────
#  退避引擎 / 频率分析器 / 双 Registry（BE-ARCH-04）
# ─────────────────────────────────────────
from .analyzer import RateLimitAnalysis, RateLimitAnalyzer  # noqa: E402
from .protocol import DataSourceInterface  # noqa: E402
from .registry import RateLimitRegistry, rate_limit_registry  # noqa: E402
from .source_registry import DataSourceRegistry, datasource_registry  # noqa: E402
from .throttler import BackoffStrategy, RateLimitThrottler  # noqa: E402

__all__ = [
    # 错误分类
    "ErrorCategory",
    "RateLimitInfo",
    "ErrorInfo",
    # 统一返回结构
    "ResultStatus",
    "Result",
    # 限流状态
    "RateLimitStatus",
    "HealthInfo",
    # 工具函数
    "classify_http_error",
    "parse_retry_after",
    # 退避引擎
    "BackoffStrategy",
    "RateLimitThrottler",
    # 频率分析器
    "RateLimitAnalysis",
    "RateLimitAnalyzer",
    # Protocol
    "DataSourceInterface",
    # 限流 Registry（Throttler + Analyzer）
    "RateLimitRegistry",
    "rate_limit_registry",
    # 源实例 Registry（DataSourceInterface）
    "DataSourceRegistry",
    "datasource_registry",
]
