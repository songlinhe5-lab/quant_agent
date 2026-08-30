"""
RL-14 · 冷却信号识别（熔断 / 限流退避）

问题背景:
    上游熔断或限流退避期间，工具调用必然失败。若工具层不识别，会表现为：
      1. 同一工具被反复调用（LLM 看到报错就换姿势重试），加重上游负担、延长恢复；
      2. 本地 FailureTracker 把「上游冷却」计为「工具失败」，连续 3 次后本地再熔断一次，
         形成二次放大：上游已恢复，本地还需额外成功调用才解锁。

协议（后端 RL-14 起保证）:
    冷却期响应带顶层 ``error_category``（circuit_open / rate_limit / quota_exhausted /
    ip_blocked）与 ``retry_after``（秒）。调用方据此快速失败，不重试。

识别优先级:
    1. 顶层结构化字段（新协议，最可靠）
    2. error 子对象（Result.to_dict 结构）
    3. 关键词兜底（未升级结构化字段的旧响应 / 纯文本错误）

对齐 ``backend/services/expert_team/data_collector.py`` 的 _NON_RETRYABLE_KEYWORDS 策略，
但由关键词匹配升级为结构化优先。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# 冷却类错误类别（与 backend ErrorCategory 取值对齐）
COOLDOWN_CATEGORIES = frozenset(
    {
        "circuit_open",
        "rate_limit",
        "quota_exhausted",
        "ip_blocked",
    }
)

# 关键词兜底：与 data_collector._NON_RETRYABLE_KEYWORDS 同源
_COOLDOWN_KEYWORDS = (
    "熔断",
    "circuit",
    "限流",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "cooldown",
    "429",
)


@dataclass(frozen=True)
class CooldownSignal:
    """冷却信号：调用方应快速失败，并在 retry_after 秒后再试。"""

    category: str
    """冷却类别：circuit_open / rate_limit / ..."""

    retry_after: Optional[float]
    """建议等待秒数；None 表示后端未给出"""

    message: str
    """面向 LLM 的提示文案（已含等待建议）"""

    @property
    def hint(self) -> str:
        """注入工具结果的提示，避免 LLM 换姿势重试。"""
        if self.retry_after:
            return f"⚠️ 上游{_zh(self.category)}中，约 {int(self.retry_after)}s 后自动恢复，请勿重试或换参数重复调用。"
        return f"⚠️ 上游{_zh(self.category)}中，请稍后再试，请勿重试或换参数重复调用。"


def _zh(category: str) -> str:
    return {
        "circuit_open": "熔断",
        "rate_limit": "限流退避",
        "quota_exhausted": "配额耗尽",
        "ip_blocked": "IP 封禁",
    }.get(category, "冷却")


def _coerce_retry_after(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_cooldown(result: Any) -> Optional[CooldownSignal]:
    """从工具结果中识别冷却信号；非冷却结果返回 None。"""
    if not isinstance(result, dict):
        return None

    # 1. 顶层结构化字段（Result.to_dict / 新协议）
    category = str(result.get("error_category") or "").strip().lower()
    retry_after = _coerce_retry_after(result.get("retry_after"))

    # 2. error 子对象
    if not category:
        err = result.get("error")
        if isinstance(err, dict):
            category = str(err.get("category") or "").strip().lower()
            retry_after = retry_after or _coerce_retry_after(err.get("retry_after"))
            if not retry_after:
                info = err.get("rate_limit_info")
                if isinstance(info, dict):
                    retry_after = _coerce_retry_after(info.get("retry_after_seconds"))

    # 状态位兜底：ResultStatus.RATE_LIMITED
    if not category and str(result.get("status", "")).lower() == "rate_limited":
        category = "rate_limit"

    if category in COOLDOWN_CATEGORIES:
        return CooldownSignal(
            category=category,
            retry_after=retry_after,
            message=result.get("message") or "",
        )

    # 3. 关键词兜底（旧响应 / 纯文本错误）
    text = f"{result.get('message') or ''} {result.get('error') or ''}".lower()
    if any(k in text for k in _COOLDOWN_KEYWORDS):
        return CooldownSignal(
            category=category or "unknown",
            retry_after=retry_after,
            message=result.get("message") or "",
        )

    return None
