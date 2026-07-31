"""
CallMetricsStore — 今日调用聚合计数持久化 (Redis 分桶)
======================================================

解决 analyzer.get_health_metrics() 用内存 deque 计算「今日」的两个硬伤：
  1. 受 _DEFAULT_MAX_EVENTS=10000 上限约束，高频源会被截断；
  2. 进程重启即清零，看板上的「今日调用」是假的。

本模块只做聚合计数（HINCRBY），不落逐条事件，因此不受 1 万上限约束；
计数写入 Redis，重启不丢。

Redis 键空间（与 docs/09 保持一致，挂在 quant:metrics 下）：
    quant:metrics:{source}:calls:{date}
  - 哈希字段（业务 vs 探针分字段，避免手动探针污染业务指标）：
      calls              业务 fetch 尝试总次数（仅真实 fetch，不含退避/熔断拦截）
      success            业务成功次数
      errors             业务普通错误次数（category=normal）
      rl_rate_limit      业务限流(429)次数
      rl_quota_exhausted 业务配额耗尽(402)次数
      rl_ip_blocked      业务 IP 封禁(403)次数
      probe_calls        test-link 探针调用次数
      probe_success      探针成功次数
      probe_errors       探针失败次数
  - {date} 为本地时区日期 YYYY-MM-DD，自然日 00:00 滚动（见 _local_date_key）

口径一致性（BE-ARCH 约定）：
  - 退避拦截（throttler.should_throttle 早退）与熔断拦截（CircuitBreakerOpenError 早退）
    不触发 fetch，因此「都不计」，与 analyzer 现有逻辑完全对齐，不混口径。
  - 仅在 source_registry.fetch 的三条真实 fetch 结果分支里调用 record_business。

TTL：每个桶在写入时刷新为 CALL_METRICS_TTL_DAYS（默认 35 天），旧桶自动过期。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# Redis 不可用时静默降级（绝不拖累业务链路）
CALL_METRICS_ENABLED = os.getenv("CALL_METRICS_ENABLED", "1") != "0"
# 桶保留天数：默认 35 天，足以覆盖「当日 / 近 24h / 近期历史」
CALL_METRICS_TTL_DAYS = int(os.getenv("CALL_METRICS_TTL_DAYS", "35"))

# 业务调用字段（真实 fetch 结果分支才累加）
_BUSINESS_FIELDS = ("calls", "success", "errors", "rl_rate_limit", "rl_quota_exhausted", "rl_ip_blocked")
# 探针字段（test-link 探针单独累加）
_PROBE_FIELDS = ("probe_calls", "probe_success", "probe_errors")


def _local_date_key() -> str:
    """本地时区自然日 YYYY-MM-DD（00:00 滚动）"""
    lt = time.localtime()
    return f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"


def _bucket_key(source: str, date: Optional[str] = None) -> str:
    return f"quant:metrics:{source}:calls:{date or _local_date_key()}"


class CallMetricsStore:
    """数据源「今日调用」聚合计数器（Redis 持久化，按自然日分桶）"""

    def __init__(self, enabled: bool = CALL_METRICS_ENABLED) -> None:
        self._enabled = enabled

    # ── 写入 ──────────────────────────────────────────────
    async def _incr(self, source: str, field: str, amount: int = 1) -> None:
        if not self._enabled:
            return
        try:
            key = _bucket_key(source)
            await redis_client.hincrby(key, field, amount)
            # 每次写入刷新 TTL，确保旧桶最终过期，不无限堆积
            await redis_client.expire(key, CALL_METRICS_TTL_DAYS * 86400)
        except Exception as exc:  # Redis 抖动/不可用时静默降级
            logger.debug("[CallMetrics] Redis 写入失败(忽略，业务不受影响): %s", exc)

    async def record_business(
        self,
        source: str,
        outcome: str,
        category: Optional[str] = None,
    ) -> None:
        """
        记录一次业务 fetch。

        outcome: "success" | "error" | "rate_limited"
        category: result.error.category.value（rate_limit/quota_exhausted/ip_blocked/normal）
                  仅当 outcome="rate_limited" 时用于拆分 rl_* 字段；
                  403/402 落到 rl_ip_blocked/rl_quota_exhausted，不计入 rl_rate_limit（退避口径）。
        """
        if not self._enabled:
            return
        await self._incr(source, "calls")
        if outcome == "success":
            await self._incr(source, "success")
        elif outcome == "rate_limited":
            # 细分到具体类别字段，便于「按 category 区分」展示
            if category == "quota_exhausted":
                await self._incr(source, "rl_quota_exhausted")
            elif category == "ip_blocked":
                await self._incr(source, "rl_ip_blocked")
            else:
                # rate_limit（含 429）或其它未知限流类
                await self._incr(source, "rl_rate_limit")
        else:  # error
            await self._incr(source, "errors")

    async def record_probe(self, source: str, success: bool) -> None:
        """记录一次 test-link 主动探测（与业务调用分字段，避免污染今日业务指标）"""
        if not self._enabled:
            return
        await self._incr(source, "probe_calls")
        await self._incr(source, "probe_success" if success else "probe_errors")

    # ── 读取 ──────────────────────────────────────────────
    async def get_today(self, source: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        读取指定自然日（默认今日）的聚合计数。

        Redis 不可用时返回 None，调用方应回退到 analyzer 内存口径。
        返回字段：
          source, date, metric_source("redis"),
          calls, success, errors, rate_limit_count, rl_breakdown, success_rate,
          probe_calls, probe_success, probe_errors
        """
        if not self._enabled:
            return None
        date = date or _local_date_key()
        try:
            raw = await redis_client.hgetall(_bucket_key(source, date))
        except Exception as exc:
            logger.debug("[CallMetrics] Redis 读取失败(回退内存口径): %s", exc)
            return None
        if not raw:
            return None

        def _int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        calls = _int(raw.get("calls"))
        success = _int(raw.get("success"))
        errors = _int(raw.get("errors"))
        rl_rate_limit = _int(raw.get("rl_rate_limit"))
        rl_quota_exhausted = _int(raw.get("rl_quota_exhausted"))
        rl_ip_blocked = _int(raw.get("rl_ip_blocked"))
        rate_limit_count = rl_rate_limit + rl_quota_exhausted + rl_ip_blocked
        rl_breakdown = {
            "rate_limit": rl_rate_limit,
            "quota_exhausted": rl_quota_exhausted,
            "ip_blocked": rl_ip_blocked,
        }
        success_rate = round(success / calls, 4) if calls else None
        return {
            "source": source,
            "date": date,
            "metric_source": "redis",
            "calls": calls,
            "success": success,
            "errors": errors,
            "rate_limit_count": rate_limit_count,
            "rl_breakdown": rl_breakdown,
            "success_rate": success_rate,
            "probe_calls": _int(raw.get("probe_calls")),
            "probe_success": _int(raw.get("probe_success")),
            "probe_errors": _int(raw.get("probe_errors")),
        }

    async def get_history(self, source: str, days: int = 7) -> list[Dict[str, Any]]:
        """读取最近 N 个自然日的聚合计数（用于趋势/历史展示）"""
        if not self._enabled:
            return []
        out: list[Dict[str, Any]] = []
        now = time.localtime()
        for offset in range(days - 1, -1, -1):
            # 由今日回溯 offset 天，计算 YYYY-MM-DD
            ts = time.mktime((now.tm_year, now.tm_mon, now.tm_mday - offset, 0, 0, 0, 0, 0, -1))
            d = time.strftime("%Y-%m-%d", time.localtime(ts))
            snap = await self.get_today(source, d)
            if snap is not None:
                out.append(snap)
        return out


# 全局单例
call_metrics = CallMetricsStore()
