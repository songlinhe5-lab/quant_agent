"""
==========================================================
LLM Token 计量存储 (SVC-05)
==========================================================

量化主脑的 AI 解说 / 盘前早报 / 研报摘要 / Hermes Agent ReAct 等重度依赖
LLM 调用，OpenAI / DeepSeek 等按 token 计费，且多数套餐有每日/每月硬配额上限。

本模块提供 LLM token 消耗的「三维聚合计数器」（Redis 持久化，按自然日/小时/月分桶），
供 QuotaCostMonitor 周期巡检预算逼近度、并暴露 Prometheus 指标供 Grafana 面板展示，
同时支撑前端 APM「Token 消耗统计」页的每日 / 每小时 / 每月数值展示。

键空间（本地时区）：
- 日桶: quant:metrics:llm:tokens:{YYYY-MM-DD}        保留 7 天
- 时桶: quant:metrics:llm:tokens:{YYYY-MM-DD}:{HH}   保留 2 天（日内曲线）
- 月桶: quant:metrics:llm:tokens:{YYYY-MM}          保留 400 天（月趋势）
各桶字段: prompt_tokens / completion_tokens / total_tokens / calls

对齐 call_metrics_store 的设计：Redis 不可用时静默降级（不阻断业务热路径）。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
TOKEN_METRICS_ENABLED = os.getenv("LLM_TOKEN_METRICS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Prometheus 指标（延迟初始化，避免 import 期副作用）
_LLM_TOKENS_TOTAL: Any = None
_LLM_TOKENS_GAUGE: Any = None

# 各桶 TTL（秒）
_DAY_TTL = 7 * 86400
_HOUR_TTL = 2 * 86400
_MONTH_TTL = 400 * 86400


def _local_date() -> date:
    """本地时区日期（对齐 call_metrics_store）"""
    return date.today()


def _day_key(d: Optional[date] = None) -> str:
    return f"quant:metrics:llm:tokens:{(d or _local_date()).isoformat()}"


def _hour_key(d: Optional[date] = None, hour: Optional[int] = None) -> str:
    d = d or _local_date()
    hour = hour if hour is not None else datetime.now().hour
    return f"quant:metrics:llm:tokens:{d.isoformat()}:{hour:02d}"


def _month_key(d: Optional[date] = None) -> str:
    d = d or _local_date()
    return f"quant:metrics:llm:tokens:{d.strftime('%Y-%m')}"


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
    LLM token 消耗「三维聚合计数器」（Redis 持久化，按自然日/小时/月分桶）。

    - record(): 一次 LLM 调用成功后累加 token 消耗（异常安全，不抛异常到业务层）
    - get_today()/get_hourly()/get_monthly()/get_daily_range()/get_summary():
      读取各维度聚合计数（Redis 不可用时返回降级值）
    """

    def __init__(self, enabled: bool = TOKEN_METRICS_ENABLED) -> None:
        self._enabled = enabled
        # Redis 不可用时的内存降级累计（仅当次进程生命周期内，按日）
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
        同时写入 日 / 时 / 月 三个分桶。
        """
        if not self._enabled:
            return
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        total_tokens = int(total_tokens or 0)
        if prompt_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
            return

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

        # Redis 持久化（best-effort，日/时/月三桶）
        try:
            now = datetime.now()
            pipe = redis_client.pipeline()
            for key, ttl in (
                (_day_key(now), _DAY_TTL),
                (_hour_key(now, now.hour), _HOUR_TTL),
                (_month_key(now), _MONTH_TTL),
            ):
                pipe.hincrby(key, "prompt_tokens", prompt_tokens)
                pipe.hincrby(key, "completion_tokens", completion_tokens)
                pipe.hincrby(key, "total_tokens", total_tokens)
                pipe.hincrby(key, "calls", 1)
                pipe.expire(key, ttl)
            await pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[TokenUsage] Redis 写入失败（已走内存降级）: {e}")

    # ── 查询 ──────────────────────────────────────────
    @staticmethod
    async def _read_bucket(key: str) -> Optional[Dict[str, int]]:
        try:
            raw = await redis_client.hgetall(key)
            if raw:
                return {
                    "prompt_tokens": _int(raw.get("prompt_tokens")),
                    "completion_tokens": _int(raw.get("completion_tokens")),
                    "total_tokens": _int(raw.get("total_tokens")),
                    "calls": _int(raw.get("calls")),
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[TokenUsage] Redis 读取失败: {e}")
        return None

    async def get_today(self, d: Optional[date] = None) -> Dict[str, Any]:
        """读取指定自然日（默认今日）的 token 聚合计数。"""
        d = d or _local_date()
        bucket = await self._read_bucket(_day_key(d))
        if bucket is not None:
            return {"date": d.isoformat(), "metric_source": "redis", **bucket}
        return {
            "date": d.isoformat(),
            "metric_source": "memory_fallback" if self._enabled else "disabled",
            "prompt_tokens": self._mem["prompt_tokens"],
            "completion_tokens": self._mem["completion_tokens"],
            "total_tokens": self._mem["total_tokens"],
            "calls": self._mem["calls"],
        }

    async def get_hourly(self, d: Optional[date] = None) -> List[Dict[str, Any]]:
        """
        读取指定自然日（默认今日）的 24 个小时桶，返回按小时升序的列表。
        无数据的小时返回零值（保证前端折线/柱状图连续）。
        """
        d = d or _local_date()
        out: List[Dict[str, Any]] = []
        for hh in range(24):
            key = _hour_key(d, hh)
            bucket = await self._read_bucket(key)
            if bucket is None:
                bucket = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            out.append({"date": d.isoformat(), "hour": hh, **bucket})
        return out

    async def get_monthly(self, month: Optional[str] = None) -> Dict[str, Any]:
        """
        读取指定月份（默认本月，格式 YYYY-MM）的 token 聚合计数。
        """
        if month is None:
            month = _local_date().strftime("%Y-%m")
        bucket = await self._read_bucket(_month_key_str(month))
        if bucket is not None:
            return {"month": month, "metric_source": "redis", **bucket}
        return {
            "month": month,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
            "prompt_tokens": self._mem["prompt_tokens"],
            "completion_tokens": self._mem["completion_tokens"],
            "total_tokens": self._mem["total_tokens"],
            "calls": self._mem["calls"],
        }

    async def get_daily_range(self, start: date, end: date) -> List[Dict[str, Any]]:
        """读取 [start, end] 闭区间内的每日聚合（按日升序，缺数据补零）。"""
        out: List[Dict[str, Any]] = []
        cur = start
        one_day = __import__("datetime").timedelta(days=1)
        while cur <= end:
            bucket = await self._read_bucket(_day_key(cur))
            if bucket is None:
                bucket = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            out.append({"date": cur.isoformat(), **bucket})
            cur += one_day
        return out

    def reset(self) -> None:
        """重置内存降级累计（用于测试）。"""
        self._mem = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }


def _month_key_str(month: str) -> str:
    """由 YYYY-MM 字符串构造 Redis 月桶键。"""
    return f"quant:metrics:llm:tokens:{month}"


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
