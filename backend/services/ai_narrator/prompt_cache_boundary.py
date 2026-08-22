"""
==========================================================
Prompt 缓存边界管理 (AGENT-11)
==========================================================

将 LLM 请求的 messages 数组显式拆分为「稳定前缀」与「易变后缀」两部分，
便于 LLM 提供商的 Prompt Caching 特性命中（如 OpenAI 的 Prompt Caching、
DeepSeek 的 Context Caching），大幅降低重复 token 消耗。

拆分策略：
1. 稳定前缀（Cacheable Prefix）：
   - System prompt（通常不变或极少变化）
   - 工具 schema 列表（与 AGENT-03 协同：scope 子集稳定才谈得上命中）
   - 历史对话的前 N 轮（可选，取决于会话长度）

2. 易变后缀（Volatile Suffix）：
   - 当前轮用户输入
   - 最近 1-2 轮对话
   - 动态注入的上下文（如实时行情、新闻）

缓存边界标记：
- 在 messages 数组中插入特殊标记（如 {"role": "system", "content": "__CACHE_BOUNDARY__"}）
- 或在 API 调用时显式分离（取决于 LLM 提供商的 API 设计）

与 AGENT-03 的天然协同：
- AGENT-03 按 scope 过滤工具 schema → schema 子集稳定 → 缓存命中率高
- 同一会话内多次调用，system prompt + schema 不变 → 只计费 suffix

键空间（Redis）：
- 缓存命中统计: quant:metrics:llm:cache:hit:{session_id}:{date}
- 缓存命中率: quant:metrics:llm:cache:hit_rate:{date}

对齐 token_usage_store 的设计：Redis 不可用时静默降级。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
PROMPT_CACHE_ENABLED = os.getenv("PROMPT_CACHE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
CACHE_BOUNDARY_MARKER = "__CACHE_BOUNDARY__"

# Prometheus 指标（延迟初始化）
_CACHE_HIT_COUNTER: Any = None
_CACHE_HIT_RATE_GAUGE: Any = None

# Redis TTL
_CACHE_TTL = 7 * 86400  # 7 天


def _init_metrics():
    """延迟初始化 Prometheus 指标"""
    global _CACHE_HIT_COUNTER, _CACHE_HIT_RATE_GAUGE
    if _CACHE_HIT_COUNTER is not None:
        return
    try:
        from prometheus_client import Counter, Gauge

        _CACHE_HIT_COUNTER = Counter(
            "llm_prompt_cache_hit_total",
            "LLM Prompt 缓存命中次数",
            ["session_id"],
        )
        _CACHE_HIT_RATE_GAUGE = Gauge(
            "llm_prompt_cache_hit_rate",
            "LLM Prompt 缓存命中率（当日）",
            [],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[PromptCache] Prometheus 指标初始化失败: {e}")


@dataclass
class PromptCacheBoundary:
    """
    Prompt 缓存边界拆分结果

    - cacheable_prefix: 稳定前缀（可被 LLM 提供商缓存）
    - volatile_suffix: 易变后缀（每次调用都不同）
    - prefix_hash: 前缀的 SHA256 哈希（用于缓存键）
    """

    cacheable_prefix: List[Dict[str, Any]]
    volatile_suffix: List[Dict[str, Any]]
    prefix_hash: str


class PromptCacheManager:
    """
    Prompt 缓存边界管理器

    - split_messages(): 将 messages 数组拆分为稳定前缀 + 易变后缀
    - record_cache_hit(): 记录缓存命中
    - get_cache_hit_rate(): 查询缓存命中率
    - should_inject_boundary_marker(): 判断是否需要插入边界标记
    """

    def __init__(self, enabled: bool = PROMPT_CACHE_ENABLED) -> None:
        self._enabled = enabled
        # 内存降级统计
        self._cache_hits: Dict[str, int] = {}  # session_id -> hits
        self._cache_misses: Dict[str, int] = {}  # session_id -> misses

    @property
    def enabled(self) -> bool:
        return self._enabled

    def split_messages(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        tool_schemas: List[Dict[str, Any]],
    ) -> PromptCacheBoundary:
        """
        将 messages 数组拆分为稳定前缀 + 易变后缀

        策略：
        1. System prompt → 稳定前缀（通常不变）
        2. Tool schemas → 稳定前缀（与 AGENT-03 协同，scope 子集稳定）
        3. 历史对话（除最后 2 轮）→ 稳定前缀（可选）
        4. 最后 2 轮对话 + 当前用户输入 → 易变后缀

        Args:
            messages: 完整的 messages 数组
            system_prompt: System prompt 内容
            tool_schemas: 工具 schema 列表

        Returns:
            PromptCacheBoundary 对象
        """
        if not self._enabled:
            # 未启用时，全部视为易变后缀
            return PromptCacheBoundary(
                cacheable_prefix=[],
                volatile_suffix=messages,
                prefix_hash="",
            )

        # 1. 构建稳定前缀
        cacheable_prefix: List[Dict[str, Any]] = []

        # 1.1 System prompt
        if system_prompt:
            cacheable_prefix.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        # 1.2 Tool schemas（序列化为 system message）
        if tool_schemas:
            import json

            schemas_json = json.dumps(tool_schemas, ensure_ascii=False, indent=2)
            cacheable_prefix.append(
                {
                    "role": "system",
                    "content": f"[Tool Schemas]\n{schemas_json}",
                }
            )

        # 1.3 历史对话（除最后 2 轮）
        # 假设 messages 格式：[{"role": "user/assistant", "content": "..."}, ...]
        if len(messages) > 2:
            # 跳过 system message（已在 1.1 处理）
            history_start = 1 if messages[0]["role"] == "system" else 0
            history_end = len(messages) - 2  # 保留最后 2 轮作为易变后缀
            for msg in messages[history_start:history_end]:
                cacheable_prefix.append(msg)

        # 2. 构建易变后缀
        volatile_suffix = messages[-2:] if len(messages) >= 2 else messages

        # 3. 计算前缀哈希（用于缓存键）
        prefix_str = str(cacheable_prefix)
        prefix_hash = hashlib.sha256(prefix_str.encode()).hexdigest()[:16]

        return PromptCacheBoundary(
            cacheable_prefix=cacheable_prefix,
            volatile_suffix=volatile_suffix,
            prefix_hash=prefix_hash,
        )

    def should_inject_boundary_marker(self, messages: List[Dict[str, Any]]) -> bool:
        """
        判断是否需要在 messages 中插入缓存边界标记

        条件：
        - 启用了缓存
        - messages 长度 > 2（有历史对话）
        - 未包含边界标记（避免重复插入）
        """
        if not self._enabled:
            return False

        if len(messages) <= 2:
            return False

        # 检查是否已包含边界标记
        for msg in messages:
            if msg.get("content") == CACHE_BOUNDARY_MARKER:
                return False

        return True

    def inject_boundary_marker(
        self,
        messages: List[Dict[str, Any]],
        boundary_position: int = -2,
    ) -> List[Dict[str, Any]]:
        """
        在 messages 中插入缓存边界标记

        Args:
            messages: 原始 messages 数组
            boundary_position: 插入位置（负数表示从末尾倒数）

        Returns:
            插入标记后的新 messages 数组
        """
        if not self.should_inject_boundary_marker(messages):
            return messages

        # 插入边界标记
        new_messages = messages.copy()
        new_messages.insert(
            boundary_position,
            {
                "role": "system",
                "content": CACHE_BOUNDARY_MARKER,
            },
        )
        return new_messages

    async def record_cache_hit(self, session_id: str, is_hit: bool) -> None:
        """
        记录缓存命中/未命中

        异常安全：任何 Redis / 指标异常均被吞掉。
        """
        if not self._enabled:
            return

        # 内存降级统计
        if is_hit:
            self._cache_hits[session_id] = self._cache_hits.get(session_id, 0) + 1
        else:
            self._cache_misses[session_id] = self._cache_misses.get(session_id, 0) + 1

        # Prometheus 指标
        _init_metrics()
        if _CACHE_HIT_COUNTER is not None and is_hit:
            _CACHE_HIT_COUNTER.labels(session_id=session_id).inc(1)

        # Redis 持久化（best-effort）
        try:
            now = datetime.now()
            pipe = redis_client.pipeline()

            # 会话维度缓存命中统计
            hit_key = f"quant:metrics:llm:cache:hit:{session_id}:{now.date().isoformat()}"
            if is_hit:
                pipe.hincrby(hit_key, "hits", 1)
            else:
                pipe.hincrby(hit_key, "misses", 1)
            pipe.expire(hit_key, _CACHE_TTL)

            # 全局缓存命中率统计
            rate_key = f"quant:metrics:llm:cache:hit_rate:{now.date().isoformat()}"
            if is_hit:
                pipe.hincrby(rate_key, "hits", 1)
            else:
                pipe.hincrby(rate_key, "misses", 1)
            pipe.expire(rate_key, _CACHE_TTL)

            await pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[PromptCache] Redis 写入失败（已走内存降级）: {e}")

    async def get_cache_hit_rate(
        self,
        session_id: Optional[str] = None,
        d: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        查询缓存命中率

        Args:
            session_id: 指定会话 ID（可选，不传则查询全局）
            d: 指定日期（可选，默认今日）

        Returns:
            {"hits": int, "misses": int, "hit_rate": float, "metric_source": str}
        """
        d = d or date.today()

        if session_id:
            # 会话维度
            hit_key = f"quant:metrics:llm:cache:hit:{session_id}:{d.isoformat()}"
        else:
            # 全局维度
            hit_key = f"quant:metrics:llm:cache:hit_rate:{d.isoformat()}"

        try:
            raw = await redis_client.hgetall(hit_key)
            if raw:
                hits = int(raw.get("hits", 0))
                misses = int(raw.get("misses", 0))
                total = hits + misses
                hit_rate = (hits / total * 100) if total > 0 else 0.0
                return {
                    "session_id": session_id,
                    "date": d.isoformat(),
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": hit_rate,
                    "metric_source": "redis",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[PromptCache] Redis 读取失败: {e}")

        # 内存降级
        if session_id:
            hits = self._cache_hits.get(session_id, 0)
            misses = self._cache_misses.get(session_id, 0)
        else:
            hits = sum(self._cache_hits.values())
            misses = sum(self._cache_misses.values())

        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0.0

        return {
            "session_id": session_id,
            "date": d.isoformat(),
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
        }

    def reset(self) -> None:
        """重置内存降级统计（用于测试）"""
        self._cache_hits.clear()
        self._cache_misses.clear()


# 全局单例
prompt_cache_manager = PromptCacheManager()
