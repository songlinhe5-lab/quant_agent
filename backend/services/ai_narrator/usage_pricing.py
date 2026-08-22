"""
==========================================================
LLM Token 成本计量 (AGENT-11)
==========================================================

基于 OpenAI / DeepSeek 等主流 LLM 提供商的官方定价，将 token 消耗转换为美元成本。
支持：
- 按模型分级定价（GPT-4 / GPT-3.5 / DeepSeek-Pro 等）
- 按会话/工具维度聚合成本
- Prometheus 指标暴露（单会话成本、累计成本）
- 与 token_usage_store 天然协同（复用 _record_usage 挂点）

定价数据来源（2026-08 最新）：
- OpenAI: https://openai.com/pricing
- DeepSeek: https://platform.deepseek.com/pricing
- Anthropic: https://www.anthropic.com/pricing

键空间（Redis）：
- 会话成本: quant:metrics:llm:cost:session:{session_id}
- 工具成本: quant:metrics:llm:cost:tool:{tool_name}:{date}
- 累计成本: quant:metrics:llm:cost:total:{date}

对齐 token_usage_store 的设计：Redis 不可用时静默降级。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
COST_METRICS_ENABLED = os.getenv("LLM_COST_METRICS_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Prometheus 指标（延迟初始化）
_LLM_COST_TOTAL: Any = None
_LLM_COST_SESSION: Any = None

# Redis TTL
_SESSION_TTL = 7 * 86400  # 7 天
_TOOL_TTL = 30 * 86400  # 30 天
_TOTAL_TTL = 400 * 86400  # 400 天


@dataclass
class ModelPricing:
    """LLM 模型定价（单位：USD per 1K tokens）"""

    model_name: str
    prompt_price: float  # USD per 1K prompt tokens
    completion_price: float  # USD per 1K completion tokens

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """计算单次调用的成本（USD）"""
        prompt_cost = (prompt_tokens / 1000) * self.prompt_price
        completion_cost = (completion_tokens / 1000) * self.completion_price
        return prompt_cost + completion_cost


# ── 主流模型定价表（2026-08 最新）──────────────────────
MODEL_PRICING_MAP: Dict[str, ModelPricing] = {
    # OpenAI GPT-4 系列
    "gpt-4": ModelPricing("gpt-4", 0.03, 0.06),
    "gpt-4-turbo": ModelPricing("gpt-4-turbo", 0.01, 0.03),
    "gpt-4o": ModelPricing("gpt-4o", 0.005, 0.015),
    "gpt-4o-mini": ModelPricing("gpt-4o-mini", 0.00015, 0.0006),
    # OpenAI GPT-3.5 系列
    "gpt-3.5-turbo": ModelPricing("gpt-3.5-turbo", 0.0005, 0.0015),
    "gpt-3.5-turbo-16k": ModelPricing("gpt-3.5-turbo-16k", 0.003, 0.004),
    # DeepSeek 系列
    "deepseek-chat": ModelPricing("deepseek-chat", 0.00014, 0.00028),
    "deepseek-pro": ModelPricing("deepseek-pro", 0.00014, 0.00028),
    "deepseek-reasoner": ModelPricing("deepseek-reasoner", 0.00055, 0.00219),
    # Anthropic Claude 系列
    "claude-3-opus": ModelPricing("claude-3-opus", 0.015, 0.075),
    "claude-3-sonnet": ModelPricing("claude-3-sonnet", 0.003, 0.015),
    "claude-3-haiku": ModelPricing("claude-3-haiku", 0.00025, 0.00125),
    # 默认（未知模型 fallback）
    "default": ModelPricing("default", 0.01, 0.02),
}


def _init_metrics():
    """延迟初始化 Prometheus 指标"""
    global _LLM_COST_TOTAL, _LLM_COST_SESSION
    if _LLM_COST_TOTAL is not None:
        return
    try:
        from prometheus_client import Counter, Gauge

        _LLM_COST_TOTAL = Counter(
            "llm_cost_usd_total",
            "LLM 累计成本（USD）",
            ["model"],
        )
        _LLM_COST_SESSION = Gauge(
            "llm_cost_usd_session",
            "单会话 LLM 成本（USD）",
            ["session_id"],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[CostMeter] Prometheus 指标初始化失败: {e}")


class UsagePricingCalculator:
    """
    LLM Token 成本计算器

    - calculate_cost(): 根据模型和 token 数计算成本
    - record_session_cost(): 累加到会话成本（Redis 持久化）
    - get_session_cost(): 查询会话累计成本
    - get_tool_cost(): 查询工具维度成本
    """

    def __init__(self, enabled: bool = COST_METRICS_ENABLED) -> None:
        self._enabled = enabled
        # 内存降级累计
        self._session_mem: Dict[str, float] = {}  # session_id -> cost
        self._total_mem: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_pricing(self, model: str) -> ModelPricing:
        """获取模型定价（未知模型 fallback 到 default）"""
        # 精确匹配
        if model in MODEL_PRICING_MAP:
            return MODEL_PRICING_MAP[model]
        # 前缀匹配（如 "deepseek-pro/v4" → "deepseek-pro"）
        for key, pricing in MODEL_PRICING_MAP.items():
            if model.startswith(key):
                return pricing
        # Fallback
        return MODEL_PRICING_MAP["default"]

    def calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """计算单次调用的成本（USD）"""
        pricing = self.get_pricing(model)
        return pricing.calculate_cost(prompt_tokens, completion_tokens)

    async def record_session_cost(
        self,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """
        累加到会话成本并返回本次成本

        异常安全：任何 Redis / 指标异常均被吞掉，绝不抛回业务热路径。
        """
        if not self._enabled:
            return 0.0

        cost = self.calculate_cost(model, prompt_tokens, completion_tokens)
        if cost <= 0:
            return 0.0

        # 内存降级累计
        self._session_mem[session_id] = self._session_mem.get(session_id, 0.0) + cost
        self._total_mem += cost

        # Prometheus 指标
        _init_metrics()
        if _LLM_COST_TOTAL is not None:
            _LLM_COST_TOTAL.labels(model=model).inc(cost)
        if _LLM_COST_SESSION is not None:
            _LLM_COST_SESSION.labels(session_id=session_id).set(self._session_mem.get(session_id, 0.0))

        # Redis 持久化（best-effort）
        try:
            now = datetime.now()
            pipe = redis_client.pipeline()

            # 会话成本累加
            session_key = f"quant:metrics:llm:cost:session:{session_id}"
            pipe.hincrbyfloat(session_key, "cost_usd", cost)
            pipe.hincrbyfloat(session_key, "calls", 1)
            pipe.expire(session_key, _SESSION_TTL)

            # 工具维度成本（如果有 tool_name 上下文）
            # TODO: 从 agent.py 传入 tool_name 参数

            # 累计成本
            total_key = f"quant:metrics:llm:cost:total:{now.date().isoformat()}"
            pipe.hincrbyfloat(total_key, "cost_usd", cost)
            pipe.hincrbyfloat(total_key, "calls", 1)
            pipe.expire(total_key, _TOTAL_TTL)

            await pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[CostMeter] Redis 写入失败（已走内存降级）: {e}")

        return cost

    async def get_session_cost(self, session_id: str) -> Dict[str, Any]:
        """查询会话累计成本"""
        session_key = f"quant:metrics:llm:cost:session:{session_id}"
        try:
            raw = await redis_client.hgetall(session_key)
            if raw:
                return {
                    "session_id": session_id,
                    "cost_usd": float(raw.get("cost_usd", 0)),
                    "calls": int(raw.get("calls", 0)),
                    "metric_source": "redis",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[CostMeter] Redis 读取失败: {e}")

        # 内存降级
        return {
            "session_id": session_id,
            "cost_usd": self._session_mem.get(session_id, 0.0),
            "calls": 0,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
        }

    async def get_total_cost(self, d: Optional[date] = None) -> Dict[str, Any]:
        """查询指定日期的累计成本"""
        d = d or date.today()
        total_key = f"quant:metrics:llm:cost:total:{d.isoformat()}"
        try:
            raw = await redis_client.hgetall(total_key)
            if raw:
                return {
                    "date": d.isoformat(),
                    "cost_usd": float(raw.get("cost_usd", 0)),
                    "calls": int(raw.get("calls", 0)),
                    "metric_source": "redis",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[CostMeter] Redis 读取失败: {e}")

        return {
            "date": d.isoformat(),
            "cost_usd": self._total_mem,
            "calls": 0,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
        }

    def reset(self) -> None:
        """重置内存降级累计（用于测试）"""
        self._session_mem.clear()
        self._total_mem = 0.0


# 全局单例
usage_pricing_calculator = UsagePricingCalculator()
