"""
==========================================================
LLM Token 计量存储 (SVC-05)
==========================================================

量化主脑的 AI 解说 / 盘前早报 / 研报摘要等重度依赖 LLM 调用，
OpenAI / DeepSeek 等按 token 计费，且多数套餐有每日/每月硬配额上限。

本模块提供 LLM token 消耗的「分日聚合计数器」（Redis 持久化，按自然日分桶），
供 QuotaCostMonitor 周期巡检预算逼近度、并暴露 Prometheus 指标供 Grafana 面板展示。

对齐 call_metrics_store 的设计：
- 键空间: quant:metrics:llm:tokens:{date}
- 字段: prompt_tokens / completion_tokens / total_tokens / calls
- {date} 为本地时区日期 YYYY-MM-DD，自然日 00:00 滚动
- Redis 不可用时静默降级（不阻断业务热路径）
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
TOKEN_METRICS_ENABLED = os.getenv("LLM_TOKEN_METRICS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Prometheus 指标（延迟初始化，避免 import 期副作用）
_LLM_TOKENS_TOTAL: Any = None
_LLM_TOKENS_GAUGE: Any = None


def _local_date_key() -> str:
    """本地时区日期 YYYY-MM-DD（对齐 call_metrics_store._local_date_key）"""
    from datetime import date

    return date.today().isoformat()


def _token_key(date: Optional[str] = None) -> str:
    """Token 计量 Redis 键"""
    return f"quant:metrics:llm:tokens:{date or _local_date_key()}"


def _init_metrics():
    """延迟初始化 Prometheus 指标（首次调用时注册，避免重复注册异常）。"""
    global _LLM_TOKENS_TOTAL, _LLM_TOKENS_GAUGE
    if _LLM_TOKENS_TOTAL is not None:
        return
    try:
        from prometheus_client import Counter, Gauge

        _LLM_TOKENS_TOTAL = Counter(
            "llm_token_usage_total",
            "LLM token 累计消耗",
            ["token_type"],  # prompt / completion / total
        )
        _LLM_TOKENS_GAUGE = Gauge(
            "llm_token_usage_today",
            "LLM 当日 token 消耗分桶",
            ["token_type"],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[TokenUsage] Prometheus 指标初始化失败: {e}")


class TokenUsageStore:
    """
    LLM token 消耗「今日聚合计数器」（Redis 持久化，按自然日分桶）。

    - record(): 一次 LLM 调用成功后累加 token 消耗（异常安全，不抛异常到业务层）
    - get_today(): 读取当日聚合计数（Redis 不可用时返回当日内存累计的降级值）
    """

    def __init__(self, enabled: bool = TOKEN_METRICS_ENABLED) -> None:
        self._enabled = enabled
        # Redis 不可用时的内存降级累计（仅当次进程生命周期内）
        self._mem: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def record(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """
        记录一次 LLM 调用的 token 消耗。

        异常安全：任何 Redis / 指标异常均被吞掉，绝不抛回业务热路径。
        """
        if not self._enabled:
            return
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        total_tokens = int(total_tokens or 0)

        # 内存降级累计
        self._mem["prompt_tokens"] += prompt_tokens
        self._mem["completion_tokens"] += completion_tokens
        self._mem["total_tokens"] += total_tokens
        self._mem["calls"] += 1

        # Prometheus 指标
        _init_metrics()
        if _LLM_TOKENS_TOTAL is not None:
            _LLM_TOKENS_TOTAL.labels(token_type="prompt").inc(prompt_tokens)
            _LLM_TOKENS_TOTAL.labels(token_type="completion").inc(completion_tokens)
            _LLM_TOKENS_TOTAL.labels(token_type="total").inc(total_tokens)

        # Redis 持久化（best-effort）
        try:
            key = _token_key()
            pipe = redis_client.pipeline()
            pipe.hincrby(key, "prompt_tokens", prompt_tokens)
            pipe.hincrby(key, "completion_tokens", completion_tokens)
            pipe.hincrby(key, "total_tokens", total_tokens)
            pipe.hincrby(key, "calls", 1)
            pipe.expire(key, 7 * 86400)  # 保留 7 天
            await pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[TokenUsage] Redis 写入失败（已走内存降级）: {e}")

    async def get_today(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        读取指定自然日（默认今日）的 token 聚合计数。

        Redis 可用时返回 Redis 值；不可用时返回内存降级累计。
        返回字段：date, metric_source, prompt_tokens, completion_tokens,
                 total_tokens, calls
        """
        date = date or _local_date_key()
        if not self._enabled:
            return {
                "date": date,
                "metric_source": "disabled",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
            }
        try:
            key = _token_key(date)
            raw = await redis_client.hgetall(key)
            if raw:
                prompt = _int(raw.get("prompt_tokens"))
                completion = _int(raw.get("completion_tokens"))
                total = _int(raw.get("total_tokens"))
                calls = _int(raw.get("calls"))
                return {
                    "date": date,
                    "metric_source": "redis",
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                    "calls": calls,
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[TokenUsage] Redis 读取失败（走内存降级）: {e}")

        # 降级：内存累计（仅当日进程内）
        return {
            "date": date,
            "metric_source": "memory_fallback",
            "prompt_tokens": self._mem["prompt_tokens"],
            "completion_tokens": self._mem["completion_tokens"],
            "total_tokens": self._mem["total_tokens"],
            "calls": self._mem["calls"],
        }

    def reset(self) -> None:
        """重置内存降级累计（用于测试）。"""
        self._mem = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }


def _int(v: Any) -> int:
    """Redis 返回 bytes/str/int 统一转 int。"""
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# 全局单例
token_usage_store = TokenUsageStore()
