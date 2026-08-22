"""
==========================================================
DeepSeek reasoning_content 隔离器 (AGENT-11)
==========================================================

DeepSeek-Reasoner / OpenAI o1 等推理模型会在 response 中返回 `reasoning_content` 字段，
记录模型的"思考过程"（Chain-of-Thought）。这部分内容：
1. 不应混入可见上下文（避免污染用户可见的对话历史）
2. 应单独归口统计（用于分析推理模型的"思考 token"消耗）
3. 可选择性地暴露给前端（如"查看 AI 推理过程"功能）

本模块提供：
- ThinkScrubber: 从 LLM response 中提取并隔离 reasoning_content
- ReasoningSummary: 推理过程摘要生成（可选，用于前端展示）
- Prometheus 指标：reasoning_tokens 单独统计

与 token_usage_store 的协同：
- token_usage_store 统计 prompt_tokens / completion_tokens / total_tokens
- think_scrubber 额外统计 reasoning_tokens（如果模型返回）
- 二者天然互补，不冲突

键空间（Redis）：
- 推理 token 统计: quant:metrics:llm:reasoning:{date}
- 推理摘要: quant:metrics:llm:reasoning:summary:{session_id}:{turn_id}

对齐 token_usage_store 的设计：Redis 不可用时静默降级。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
REASONING_SCRUBBER_ENABLED = os.getenv("REASONING_SCRUBBER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
REASONING_SUMMARY_ENABLED = os.getenv("REASONING_SUMMARY_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Prometheus 指标（延迟初始化）
_REASONING_TOKENS_COUNTER: Any = None

# Redis TTL
_REASONING_TTL = 30 * 86400  # 30 天


def _init_metrics():
    """延迟初始化 Prometheus 指标"""
    global _REASONING_TOKENS_COUNTER
    if _REASONING_TOKENS_COUNTER is not None:
        return
    try:
        from prometheus_client import Counter

        _REASONING_TOKENS_COUNTER = Counter(
            "llm_reasoning_tokens_total",
            "LLM 推理过程 token 累计（reasoning_content）",
            ["model"],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[ThinkScrubber] Prometheus 指标初始化失败: {e}")


@dataclass
class ScrubbedResponse:
    """
    清洗后的 LLM Response

    - content: 可见内容（去除 reasoning_content 后的最终输出）
    - reasoning_content: 推理过程（可选，用于前端展示）
    - reasoning_tokens: 推理 token 数（如果模型返回）
    - tool_calls: 工具调用列表（如果有）
    - usage: Token 使用量（prompt_tokens / completion_tokens / total_tokens）
    """

    content: Optional[str]
    reasoning_content: Optional[str]
    reasoning_tokens: int
    tool_calls: Optional[List[Dict[str, Any]]]
    usage: Any


class ThinkScrubber:
    """
    DeepSeek reasoning_content 隔离器

    - scrub(): 从 LLM response 中提取 reasoning_content，返回清洗后的 response
    - record_reasoning_tokens(): 记录推理 token 消耗
    - get_reasoning_summary(): 查询推理 token 统计
    - generate_summary(): 生成推理过程摘要（可选，用于前端展示）
    """

    def __init__(
        self,
        enabled: bool = REASONING_SCRUBBER_ENABLED,
        summary_enabled: bool = REASONING_SUMMARY_ENABLED,
    ) -> None:
        self._enabled = enabled
        self._summary_enabled = summary_enabled
        # 内存降级统计
        self._reasoning_mem: Dict[str, int] = {}  # date -> tokens

    @property
    def enabled(self) -> bool:
        return self._enabled

    def scrub(self, response: Any, model: str = "unknown") -> ScrubbedResponse:
        """
        从 LLM response 中提取 reasoning_content，返回清洗后的 response

        支持：
        - OpenAI ChatCompletion response 对象
        - DeepSeek API response 对象
        - 自定义 response 对象（需包含 reasoning_content 字段）

        Args:
            response: LLM response 对象
            model: 模型名称（用于统计）

        Returns:
            ScrubbedResponse 对象
        """
        if not self._enabled:
            # 未启用时，直接透传
            return ScrubbedResponse(
                content=getattr(response, "content", None),
                reasoning_content=None,
                reasoning_tokens=0,
                tool_calls=getattr(response, "tool_calls", None),
                usage=getattr(response, "usage", None),
            )

        # 提取 reasoning_content
        reasoning_content = getattr(response, "reasoning_content", None)

        # 估算 reasoning_tokens（如果模型未返回）
        reasoning_tokens = 0
        if reasoning_content:
            # 简单估算：1 token ≈ 4 字符（英文）或 1.5 字符（中文）
            # 更精确的方式是调用 tokenizer，但这里为了性能做粗略估算
            char_count = len(reasoning_content)
            # 假设 70% 中文 + 30% 英文
            reasoning_tokens = int(char_count / 2)

        # 记录推理 token 消耗
        if reasoning_tokens > 0:
            self._record_reasoning_tokens(model, reasoning_tokens)

        # 返回清洗后的 response
        return ScrubbedResponse(
            content=getattr(response, "content", None),
            reasoning_content=reasoning_content,
            reasoning_tokens=reasoning_tokens,
            tool_calls=getattr(response, "tool_calls", None),
            usage=getattr(response, "usage", None),
        )

    def _record_reasoning_tokens(self, model: str, tokens: int) -> None:
        """
        记录推理 token 消耗

        异常安全：任何 Redis / 指标异常均被吞掉。
        """
        if not self._enabled or tokens <= 0:
            return

        # 内存降级统计
        today = date.today().isoformat()
        self._reasoning_mem[today] = self._reasoning_mem.get(today, 0) + tokens

        # Prometheus 指标
        _init_metrics()
        if _REASONING_TOKENS_COUNTER is not None:
            _REASONING_TOKENS_COUNTER.labels(model=model).inc(tokens)

        # Redis 持久化（best-effort）
        try:
            now = datetime.now()
            key = f"quant:metrics:llm:reasoning:{now.date().isoformat()}"
            pipe = redis_client.pipeline()
            pipe.hincrby(key, "reasoning_tokens", tokens)
            pipe.hincrby(key, "calls", 1)
            pipe.expire(key, _REASONING_TTL)
            # 同步执行（避免阻塞）
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在异步上下文中，使用 ensure_future
                    asyncio.ensure_future(pipe.execute())
                else:
                    # 在同步上下文中，直接执行
                    loop.run_until_complete(pipe.execute())
            except RuntimeError:
                # 无 event loop，跳过 Redis 写入
                pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ThinkScrubber] Redis 写入失败（已走内存降级）: {e}")

    async def get_reasoning_summary(self, d: Optional[date] = None) -> Dict[str, Any]:
        """
        查询推理 token 统计

        Args:
            d: 指定日期（可选，默认今日）

        Returns:
            {"date": str, "reasoning_tokens": int, "calls": int, "metric_source": str}
        """
        d = d or date.today()
        key = f"quant:metrics:llm:reasoning:{d.isoformat()}"

        try:
            raw = await redis_client.hgetall(key)
            if raw:
                return {
                    "date": d.isoformat(),
                    "reasoning_tokens": int(raw.get("reasoning_tokens", 0)),
                    "calls": int(raw.get("calls", 0)),
                    "metric_source": "redis",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ThinkScrubber] Redis 读取失败: {e}")

        # 内存降级
        return {
            "date": d.isoformat(),
            "reasoning_tokens": self._reasoning_mem.get(d.isoformat(), 0),
            "calls": 0,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
        }

    def generate_summary(
        self,
        reasoning_content: str,
        max_length: int = 200,
    ) -> str:
        """
        生成推理过程摘要（用于前端展示）

        Args:
            reasoning_content: 完整的推理过程文本
            max_length: 摘要最大长度（字符数）

        Returns:
            摘要文本
        """
        if not self._summary_enabled or not reasoning_content:
            return ""

        # 简单摘要策略：取前 N 个字符 + "..."
        if len(reasoning_content) <= max_length:
            return reasoning_content

        # 尝试在句子边界截断
        truncated = reasoning_content[:max_length]
        last_period = truncated.rfind(".")
        if last_period > max_length * 0.8:
            return truncated[: last_period + 1]

        return truncated + "..."

    def reset(self) -> None:
        """重置内存降级统计（用于测试）"""
        self._reasoning_mem.clear()


# 全局单例
think_scrubber = ThinkScrubber()
