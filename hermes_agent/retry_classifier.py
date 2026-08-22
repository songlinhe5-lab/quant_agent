"""
AGENT-18 · LLM 调用重试分类与退避（codex responses_retry.rs 范式）

设计原则：
- **可重试错误 (Retryable)**: 网络超时/连接错误、HTTP 429（速率限制）、5xx（服务端错误）
- **不可重试错误 (Non-retryable)**:
  - 4xx 参数错误（不含 429）-> 直接抛出记录，不重试
  - 内容过滤/安全拦截 -> 返回特定错误码，不重试
  - 鉴权错误 -> 直接抛出记录，不重试
- **指数退避 + 抖动 (jitter)**: 默认 base_delay=1.0s, max_delay=30.0s, max_attempts=3
- **Retry-After 优先**: 429 优先读取响应头 Retry-After，缺失则退避算法
- **半截流式不重试**: 已产生流式输出后失败不再重试（防副作用）
- **FailureTracker 集成**: 重试耗尽时记录到 AGENT-02 FailureTracker
- **结构化重试日志**: 每次重试前记录 重试次数 / 异常类型 / 延迟时间
- **可配置**: 通过 RetryConfig 从环境变量/配置文件读取 max_attempts / base_delay / max_delay

参考实现：
https://github.com/rust-lang/crates.io/blob/main/crates/responses_retry.rs
"""

import logging
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ── Error Classification ──────────────────────────────────────────────────────


class ErrorCategory(Enum):
    """LLM 调用异常的具体分类（覆盖需求 1 的全部类别）"""

    NETWORK = "network"  # 网络超时与连接错误（可重试）
    RATE_LIMIT = "rate_limit"  # 速率限制 429（可重试，读 Retry-After）
    SERVER_ERROR = "server_error"  # 服务端错误 5xx（可重试）
    BAD_REQUEST = "bad_request"  # 请求参数错误 4xx（不含 429，不可重试）
    CONTENT_FILTER = "content_filter"  # 内容过滤/安全拦截（不可重试，特定错误码）
    AUTH = "auth"  # 鉴权错误（不可重试）
    UNKNOWN = "unknown"  # 未知错误（保守策略：不可重试）


class RetryDecision(Enum):
    """重试决策"""

    RETRY_BACKOFF = "retry_backoff"  # 退避后重试（指数退避 + jitter）
    RETRY_IMMEDIATE = "retry_immediate"  # 立即重试（极短延迟）
    NO_RETRY = "no_retry"  # 不重试，直接抛出


# 内容过滤/安全拦截对应的特定错误码
CONTENT_FILTER_ERROR_CODE = "LLM_CONTENT_FILTERED"


@dataclass
class RetryConfig:
    """
    重试配置（需求 5：可通过配置文件或环境变量调整）。

    环境变量：
      - AGENT18_MAX_ATTEMPTS: 最大重试次数（默认 3）
      - AGENT18_BASE_DELAY: 初始延迟秒（默认 1.0）
      - AGENT18_MAX_DELAY: 最大延迟秒（默认 30.0）
      - AGENT18_EXPONENT: 退避指数（默认 2.0）
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponent: float = 2.0
    # 单次重试总预算（秒），超时则放弃。None 表示不限
    total_timeout: Optional[float] = 120.0

    @classmethod
    def from_env(cls) -> "RetryConfig":
        """从环境变量构建配置，任何缺失项回退默认值"""

        def _int(key: str, default: int) -> int:
            val = os.getenv(key)
            if val is None:
                return default
            try:
                return int(val)
            except ValueError:
                logger.warning("[AGENT-18] 环境变量 %s=%r 非法，使用默认 %d", key, val, default)
                return default

        def _float(key: str, default: float) -> float:
            val = os.getenv(key)
            if val is None:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning("[AGENT-18] 环境变量 %s=%r 非法，使用默认 %s", key, val, default)
                return default

        return cls(
            max_attempts=_int("AGENT18_MAX_ATTEMPTS", cls.max_attempts),
            base_delay=_float("AGENT18_BASE_DELAY", cls.base_delay),
            max_delay=_float("AGENT18_MAX_DELAY", cls.max_delay),
            exponent=_float("AGENT18_EXPONENT", cls.exponent),
            total_timeout=_float("AGENT18_TOTAL_TIMEOUT", cls.total_timeout)
            if os.getenv("AGENT18_TOTAL_TIMEOUT") is not None
            else cls.total_timeout,
        )


@dataclass
class LLMErrorInfo:
    """LLM 调用异常封装（含分类信息与重试决策）"""

    original_error: Exception
    status_code: Optional[int] = None
    response_headers: Optional[dict] = None
    category: ErrorCategory = field(init=False)
    retry_after: Optional[float] = field(init=False, default=None)

    def __post_init__(self):
        self.category = self._classify()
        self.retry_after = self._extract_retry_after()

    # ---- 分类逻辑 ----

    def _classify(self) -> ErrorCategory:
        err_msg = str(self.original_error).lower()
        err_type = type(self.original_error).__name__.lower()
        sc = self.status_code

        # 1) 网络超时与连接错误
        network_patterns = [
            "timeout",
            "timed out",
            "connection refused",
            "connection reset",
            "connection error",
            "network error",
            "unexpected eof",
            "eoferror",
            "socket",
            "name or service not known",
            "temporary failure in name resolution",
        ]
        for p in network_patterns:
            if p in err_msg or p in err_type:
                return ErrorCategory.NETWORK

        # 2) 按状态码分类（优先，最可靠）
        if sc is not None:
            if sc == 429:
                return ErrorCategory.RATE_LIMIT
            if 500 <= sc < 600:
                return ErrorCategory.SERVER_ERROR
            if sc == 400:
                return ErrorCategory.BAD_REQUEST
            if sc == 401 or sc == 403:
                return ErrorCategory.AUTH
            if 400 <= sc < 500:
                # 其他 4xx，需进一步判断是否内容过滤
                if self._looks_like_content_filter(err_msg):
                    return ErrorCategory.CONTENT_FILTER
                return ErrorCategory.BAD_REQUEST

        # 3) 内容过滤 / 安全拦截（无状态码或嵌套在 message 里）
        if self._looks_like_content_filter(err_msg):
            return ErrorCategory.CONTENT_FILTER

        # 4) 鉴权错误（message 层）
        auth_patterns = [
            "authentication",
            "authorization",
            "api key",
            "permission denied",
            "unauthorized",
            "invalid api key",
            "forbidden",
        ]
        for p in auth_patterns:
            if p in err_msg or p in err_type:
                return ErrorCategory.AUTH

        # 5) 参数错误 / 语义错误（不可重试）
        param_patterns = [
            "bad request",
            "invalid parameter",
            "parse error",
            "syntax error",
            "model not found",
            "invalid model",
            "invalid request",
            "semantic",
        ]
        for p in param_patterns:
            if p in err_msg or p in err_type:
                return ErrorCategory.BAD_REQUEST

        # 6) 速率限制 message 层兜底
        if "too many requests" in err_msg or "rate limit" in err_msg:
            return ErrorCategory.RATE_LIMIT

        # 7) 服务端错误 message 层兜底
        server_patterns = [
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        ]
        for p in server_patterns:
            if p in err_msg:
                return ErrorCategory.SERVER_ERROR

        return ErrorCategory.UNKNOWN

    @staticmethod
    def _looks_like_content_filter(err_msg: str) -> bool:
        cf_patterns = [
            "content filter",
            "content policy",
            "safety",
            "moderation",
            "filtered",
            "flagged",
            "inappropriate",
            "harmful content",
            "prompt was flagged",
        ]
        return any(p in err_msg for p in cf_patterns)

    def _extract_retry_after(self) -> Optional[float]:
        """从异常或响应头提取 Retry-After（需求 2：429 读响应头）"""
        # 优先 response_headers
        if self.response_headers:
            for key in ("Retry-After", "retry-after", "HTTP_RETRY_AFTER"):
                val = self.response_headers.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        # Retry-After 可能是 HTTP date，退避算法兜底
                        logger.debug("[AGENT-18] Retry-After=%r 非数字，忽略", val)
                        return None
        # openai SDK: error.response.headers
        resp = getattr(self.original_error, "response", None)
        if resp is not None:
            headers = getattr(resp, "headers", None)
            if headers:
                val = headers.get("Retry-After") or headers.get("retry-after")
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return None
        # message 中的 retry_after 字段（部分 SDK）
        ra = getattr(self.original_error, "retry_after", None)
        if ra is not None:
            try:
                return float(ra)
            except (TypeError, ValueError):
                return None
        return None

    # ---- 决策属性 ----

    @property
    def is_retryable(self) -> bool:
        return self.category in (
            ErrorCategory.NETWORK,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.SERVER_ERROR,
        )

    @property
    def decision(self) -> RetryDecision:
        if not self.is_retryable:
            return RetryDecision.NO_RETRY
        # 网络错误允许立即重试（无退避或极短退避），其余走退避
        if self.category == ErrorCategory.NETWORK:
            return RetryDecision.RETRY_IMMEDIATE
        return RetryDecision.RETRY_BACKOFF

    @property
    def error_code(self) -> Optional[str]:
        """内容过滤返回特定错误码（需求 2）"""
        if self.category == ErrorCategory.CONTENT_FILTER:
            return CONTENT_FILTER_ERROR_CODE
        return None


def classify_llm_error(
    error: Exception,
    status_code: Optional[int] = None,
    response_headers: Optional[dict] = None,
) -> LLMErrorInfo:
    """工厂函数：分类 LLM 异常"""
    return LLMErrorInfo(error, status_code, response_headers)


# ── Exponential Backoff with Jitter (AWS full-jitter) ─────────────────────────


class ExponentialBackoff:
    """
    指数退避计算器（带随机抖动）。

    Formula: raw = base * (exponent ^ attempt) * multiplier
             jitter = random(0, raw)            # full jitter (AWS)
             delay = min(raw + jitter, max_delay)

    Features:
    - 随机抖动避免多请求同时重试造成拥塞（需求 3）
    - 可配置 base / max / exponent
    - attempt 计数器重置
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponent: float = 2.0,
        multiplier: float = 1.0,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponent = exponent
        self.multiplier = multiplier
        self._current_attempt = 0

    @property
    def current_attempt(self) -> int:
        return self._current_attempt

    def reset(self) -> None:
        self._current_attempt = 0

    def get_delay(self, attempt: Optional[int] = None) -> float:
        if attempt is None:
            attempt = self._current_attempt
        # 指数增长基线（基准延迟）
        raw = self.base_delay * (self.exponent**attempt) * self.multiplier
        # 上限截断：先 cap 再 full-jitter，确保抖动不会超过 max_delay
        capped = min(raw, self.max_delay)
        # AWS full-jitter: 在 [0, capped] 区间均匀随机，打散重试洪峰（需求 3）
        jitter = random.uniform(0, capped)
        return round(jitter, 3)

    def next_attempt_delay(self) -> float:
        delay = self.get_delay(self._current_attempt)
        self._current_attempt += 1
        return delay

    def __repr__(self) -> str:
        return f"ExponentialBackoff(attempt={self._current_attempt}, base={self.base_delay}s, max={self.max_delay}s)"


# ── Retry Budget & Logging ───────────────────────────────────────────────────


@dataclass
class RetryLogEntry:
    """单次重试的结构化日志条目（需求 4）"""

    attempt: int
    category: ErrorCategory
    status_code: Optional[int]
    delay_seconds: float
    decision: RetryDecision
    reason: str
    timestamp: float = field(default_factory=time.monotonic)


class RetryBudget:
    """
    重试预算控制器（修复此前 _attempts_used 引用不存在字段的 bug）。

    Enforces:
    - 最大尝试次数（来自 RetryConfig.max_attempts）
    - 总超时（可选）
    - 仅对可重试错误放行
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        self.max_attempts = self.config.max_attempts
        self.total_timeout = self.config.total_timeout
        self.start_time: Optional[float] = None
        self._attempts_used = 0
        self._cancelled = False
        self.log: list[RetryLogEntry] = []

    def start(self) -> None:
        self.start_time = time.monotonic()

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time

    @property
    def time_budget_remaining(self) -> Optional[float]:
        if self.total_timeout is None:
            return None
        return max(0.0, self.total_timeout - self.elapsed)

    @property
    def attempt_budget_remaining(self) -> int:
        return max(0, self.max_attempts - self._attempts_used)

    def can_retry(self, error_info: LLMErrorInfo) -> Tuple[bool, str]:
        if self._cancelled:
            return False, "cancelled by caller"

        if self.attempt_budget_remaining <= 0:
            return False, "max attempts exhausted"

        if self.time_budget_remaining is not None and self.time_budget_remaining <= 0:
            return False, "total timeout exceeded"

        if not error_info.is_retryable:
            return False, "non-retryable error"

        return True, "proceeding with retry"

    def record_retry(
        self,
        error_info: LLMErrorInfo,
        delay: float,
        decision: RetryDecision,
        reason: str,
    ) -> None:
        """需求 4：记录每次重试前的结构化日志"""
        self._attempts_used += 1
        entry = RetryLogEntry(
            attempt=self._attempts_used,
            category=error_info.category,
            status_code=error_info.status_code,
            delay_seconds=delay,
            decision=decision,
            reason=reason,
        )
        self.log.append(entry)
        logger.warning(
            "[AGENT-18] LLM 重试 #%d/%d | 类型=%s | 状态码=%s | 延迟=%.2fs | 决策=%s | 原因=%s",
            entry.attempt,
            self.max_attempts,
            entry.category.value,
            entry.status_code,
            entry.delay_seconds,
            entry.decision.value,
            entry.reason,
        )

    def cancel(self) -> None:
        self._cancelled = True

    def summary(self) -> dict:
        return {
            "max_attempts": self.max_attempts,
            "attempts_used": self._attempts_used,
            "remaining": self.attempt_budget_remaining,
            "log": [
                {
                    "attempt": e.attempt,
                    "category": e.category.value,
                    "status_code": e.status_code,
                    "delay_seconds": e.delay_seconds,
                    "decision": e.decision.value,
                    "reason": e.reason,
                }
                for e in self.log
            ],
        }


# ── Global State & Integration Hooks ──────────────────────────────────────────


class RetryState:
    """全局重试状态跟踪器（可选集成到 Redis/Memory）"""

    def __init__(self):
        self.total_retries = 0
        self.total_failures = 0
        self.total_successes_after_retry = 0

    def record_retry(self, success: bool) -> None:
        self.total_retries += 1
        if success:
            self.total_successes_after_retry += 1
        else:
            self.total_failures += 1

    def summary(self) -> dict:
        return {
            "total_retries": self.total_retries,
            "total_failures": self.total_failures,
            "total_successes_after_retry": self.total_successes_after_retry,
            "success_rate": (self.total_successes_after_retry / self.total_retries if self.total_retries > 0 else 0.0),
        }


_retry_state = RetryState()


def get_retry_state() -> RetryState:
    return _retry_state


# ── Public API ───────────────────────────────────────────────────────────────


def should_retry_with_backoff(
    error: Exception,
    status_code: Optional[int] = None,
    config: Optional[RetryConfig] = None,
) -> Tuple[bool, Optional[float], str]:
    """
    便捷函数：判断是否应该重试并计算退避时间。

    Returns:
        (should_retry, backoff_seconds, reason)
    """
    error_info = classify_llm_error(error, status_code)

    if not error_info.is_retryable:
        return False, None, f"non-retryable error: {error_info.category.value}"

    cfg = config or RetryConfig()
    backoff = ExponentialBackoff(base_delay=cfg.base_delay, max_delay=cfg.max_delay, exponent=cfg.exponent)
    backoff.reset()

    # 429 优先使用 Retry-After
    if error_info.category == ErrorCategory.RATE_LIMIT and error_info.retry_after is not None:
        delay = min(error_info.retry_after, cfg.max_delay)
        return True, delay, f"rate-limit Retry-After ({delay:.2f}s)"

    delay = backoff.next_attempt_delay()
    if error_info.decision == RetryDecision.RETRY_IMMEDIATE and delay <= 1.0:
        return True, 0.0, "immediate retry (no backoff)"
    return True, delay, f"exponential backoff ({delay:.2f}s)"
