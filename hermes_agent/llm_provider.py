"""
==========================================================
AGENT-06 · LLM Provider 适配缝
==========================================================

对标 dsh `llm/llm` 的 `ctx.llm` 适配缝 + hermes `transports/` 多 transport 并存。

核心思想：
  主推理模型（deepseek-v4-flash）保持不变，但当主 provider 故障时自动降级到备用 provider。
  降级过程对上层（agent.py）透明，通过 SSE 事件通知前端标注降级态。

设计约束（不可妥协）：
  1. 默认路由不变：AGENTS.md §A.3.3 主推理仍为 deepseek-v4-flash
  2. 只做故障降级，不改默认路由
  3. 前端按 §2.4 STALE 规范标注降级态

与现有架构的协同：
  - AGENT-04: _call_llm() 统一 LLM 调用入口，在此处接入 provider router
  - AGENT-01: provider 切换事件记入会话事件日志
  - AGENT-11: 不同 provider 的定价可能不同，需传递 provider name 给 usage_pricing

使用示例：
    router = LLMProviderRouter.from_env()
    router.add_fallback(LLMProvider("openai-backup", openai_client, "gpt-4o-mini"))

    # 非流式调用（自动 failover）
    response = await router.execute_with_failover(
        create_func=lambda client, model: client.chat.completions.create(
            model=model, messages=messages, ...
        )
    )

    # 获取当前活跃 provider（用于 SSE 降级通知）
    active = router.get_active_provider()
    if active.name != router.primary_provider.name:
        yield {"type": "provider_degraded", "provider": active.name, ...}
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ========================================================================
# 数据结构
# ========================================================================


class ProviderStatus(str, Enum):
    """Provider 健康状态"""

    HEALTHY = "healthy"  # 正常
    DEGRADED = "degraded"  # 降级中（部分功能受限）
    FAILED = "failed"  # 故障（已切换到备用）
    RECOVERING = "recovering"  # 恢复中（探测是否可恢复）


@dataclass
class LLMProvider:
    """
    单个 LLM Provider 封装。

    Attributes:
        name: Provider 名称（用于日志和 SSE 通知）
        client: AsyncOpenAI 客户端实例
        model: 模型名称
        priority: 优先级（0 = 最高，数字越大优先级越低）
        status: 当前健康状态
        consecutive_failures: 连续失败次数（达到阈值触发切换）
        last_success_time: 上次成功时间戳
        last_failure_time: 上次失败时间戳
    """

    name: str
    client: AsyncOpenAI
    model: str
    priority: int = 0
    status: ProviderStatus = ProviderStatus.HEALTHY
    consecutive_failures: int = 0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0

    def mark_success(self) -> None:
        """标记成功 — 重置失败计数"""
        self.consecutive_failures = 0
        self.last_success_time = time.monotonic()
        if self.status != ProviderStatus.HEALTHY:
            self.status = ProviderStatus.HEALTHY
            print(f"✅ [LLMProvider] {self.name} 恢复正常")

    def mark_failure(self) -> None:
        """标记失败 — 累加失败计数"""
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()


@dataclass
class FailoverEvent:
    """
    故障切换事件 — 用于 SSE 通知前端。

    Attributes:
        from_provider: 原 provider 名称
        to_provider: 新 provider 名称
        reason: 切换原因
        timestamp: 事件时间戳
    """

    from_provider: str
    to_provider: str
    reason: str
    timestamp: float = field(default_factory=time.monotonic)

    def to_sse_dict(self) -> Dict[str, Any]:
        """转为 SSE 事件 dict"""
        return {
            "type": "provider_degraded",
            "from_provider": self.from_provider,
            "to_provider": self.to_provider,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ========================================================================
# 故障切换阈值
# ========================================================================

# 连续失败多少次触发切换（LLM API 调用失败成本高，1 次即切换）
FAILOVER_THRESHOLD: int = 1

# 恢复探测间隔（秒）— 失败 provider 多久后尝试恢复
RECOVERY_PROBE_INTERVAL: float = 60.0

# 最大 fallback 数量（防止配置错误导致无限链）
MAX_FALLBACKS: int = 3


# ========================================================================
# LLM Provider Router
# ========================================================================


class LLMProviderRouter:
    """
    LLM Provider 路由器 — 管理主备 provider 链。

    核心能力：
    1. 主备链管理：primary + fallback[0..N]
    2. 自动故障切换：连续失败达阈值后自动切到下一个 provider
    3. 自动恢复探测：定期探测失败 provider 是否恢复
    4. 透明 failover：上层调用 execute_with_failover 时无需关心切换逻辑
    5. SSE 事件通知：切换时生成 FailoverEvent，由上层 yield 给前端
    6. **AGENT-18: Retry Logic** - 针对可重试错误（429/timeout/5xx）指数退避 + jitter 最多 3 次
       - 不可重试错误（auth/param）直接报错，不消耗 provider 切换预算

    使用示例：
        router = LLMProviderRouter.from_env()
        router.add_fallback(LLMProvider("openai-backup", client, "gpt-4o-mini"))

        response = await router.execute_with_failover(
            create_func=lambda c, m: c.chat.completions.create(model=m, ...)
        )
    """

    def __init__(self, primary: LLMProvider):
        self._primary = primary
        self._fallbacks: List[LLMProvider] = []
        self._active_index: int = 0  # 0 = primary, 1+ = fallback
        self._failover_events: List[FailoverEvent] = []
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> LLMProviderRouter:
        """
        从环境变量构建 Router。

        环境变量：
          - LLM_API_KEY: 主 provider API key
          - LLM_BASE_URL: 主 provider base URL
          - LLM_MODEL: 主 provider 模型名称
          - LLM_FALLBACK_API_KEY: 备用 provider API key（可选）
          - LLM_FALLBACK_BASE_URL: 备用 provider base URL（可选）
          - LLM_FALLBACK_MODEL: 备用 provider 模型名称（可选）
        """
        # 主 provider
        primary_api_key = os.getenv("LLM_API_KEY")
        primary_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        primary_model = os.getenv("LLM_MODEL", "deepseek-v4-flash")

        primary_client = AsyncOpenAI(api_key=primary_api_key, base_url=primary_base_url)
        primary = LLMProvider(
            name=f"primary-{primary_model}",
            client=primary_client,
            model=primary_model,
            priority=0,
        )

        router = cls(primary)

        # 备用 provider（可选）
        fallback_api_key = os.getenv("LLM_FALLBACK_API_KEY")
        if fallback_api_key:
            fallback_base_url = os.getenv("LLM_FALLBACK_BASE_URL", "https://api.openai.com/v1")
            fallback_model = os.getenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")

            fallback_client = AsyncOpenAI(api_key=fallback_api_key, base_url=fallback_base_url)
            fallback = LLMProvider(
                name=f"fallback-{fallback_model}",
                client=fallback_client,
                model=fallback_model,
                priority=1,
            )
            router.add_fallback(fallback)

        return router

    @property
    def primary_provider(self) -> LLMProvider:
        """获取主 provider"""
        return self._primary

    @property
    def all_providers(self) -> List[LLMProvider]:
        """获取所有 provider（主 + 备）"""
        return [self._primary] + self._fallbacks

    def get_active_provider(self) -> LLMProvider:
        """获取当前活跃的 provider"""
        if self._active_index == 0:
            return self._primary
        return self._fallbacks[self._active_index - 1]

    def get_active_client(self) -> AsyncOpenAI:
        """获取当前活跃 provider 的 client"""
        return self.get_active_provider().client

    def get_active_model(self) -> str:
        """获取当前活跃 provider 的 model"""
        return self.get_active_provider().model

    def is_degraded(self) -> bool:
        """是否处于降级状态"""
        return self._active_index > 0

    def add_fallback(self, provider: LLMProvider) -> None:
        """
        添加备用 provider。

        Args:
            provider: 备用 provider（priority 必须 > 0）
        """
        if len(self._fallbacks) >= MAX_FALLBACKS:
            print(f"⚠️ [LLMProvider] 已达最大 fallback 数量 ({MAX_FALLBACKS})，忽略 {provider.name}")
            return

        if provider.priority <= 0:
            provider.priority = len(self._fallbacks) + 1

        self._fallbacks.append(provider)
        print(f"✅ [LLMProvider] 添加备用 provider: {provider.name} (model={provider.model})")

    async def report_success(self, provider: Optional[LLMProvider] = None) -> None:
        """
        报告调用成功 — 重置失败计数，可能触发恢复。

        Args:
            provider: 成功的 provider（默认当前活跃 provider）
        """
        async with self._lock:
            p = provider or self.get_active_provider()
            p.mark_success()

    async def report_failure(self, provider: Optional[LLMProvider] = None) -> Optional[FailoverEvent]:
        """
        报告调用失败 — 累加失败计数，可能触发切换。

        Args:
            provider: 失败的 provider（默认当前活跃 provider）

        Returns:
            FailoverEvent 如果发生了切换，否则 None
        """
        async with self._lock:
            p = provider or self.get_active_provider()
            p.mark_failure()

            # 检查是否达到切换阈值
            if p.consecutive_failures >= FAILOVER_THRESHOLD:
                return await self._failover(p)

            return None

    async def _failover(self, failed_provider: LLMProvider) -> Optional[FailoverEvent]:
        """
        执行故障切换 — 切到下一个可用 provider。

        Returns:
            FailoverEvent 如果成功切换，否则 None
        """
        old_provider = failed_provider

        # 尝试下一个 provider
        for i in range(self._active_index + 1, len(self._fallbacks) + 1):
            candidate = self._primary if i == 0 else self._fallbacks[i - 1]
            if candidate.status != ProviderStatus.FAILED:
                self._active_index = i
                candidate.status = ProviderStatus.HEALTHY

                event = FailoverEvent(
                    from_provider=old_provider.name,
                    to_provider=candidate.name,
                    reason=f"{old_provider.name} 连续失败 {old_provider.consecutive_failures} 次",
                )
                self._failover_events.append(event)

                old_provider.status = ProviderStatus.FAILED
                print(f"🔄 [LLMProvider] 故障切换: {old_provider.name} → {candidate.name} (原因: {event.reason})")
                return event

        # 所有 provider 都不可用
        print(f"🚨 [LLMProvider] 所有 provider 均不可用！当前: {old_provider.name}")
        return None

    async def try_recovery(self) -> Optional[FailoverEvent]:
        """
        尝试恢复到主 provider — 探测主 provider 是否可用。

        Returns:
            FailoverEvent 如果成功恢复，否则 None
        """
        async with self._lock:
            if self._active_index == 0:
                return None  # 已经在主 provider 上

            primary = self._primary
            if primary.status == ProviderStatus.FAILED:
                # 检查是否到了恢复探测间隔
                time_since_failure = time.monotonic() - primary.last_failure_time
                if time_since_failure < RECOVERY_PROBE_INTERVAL:
                    return None  # 还没到探测时间

                primary.status = ProviderStatus.RECOVERING
                print(f"🔍 [LLMProvider] 尝试恢复探测: {primary.name}")

                # 尝试一个简单的调用来探测
                try:
                    await primary.client.chat.completions.create(
                        model=primary.model,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1,
                        timeout=5.0,
                    )
                    # 探测成功 — 切回主 provider
                    old_provider = self.get_active_provider()
                    self._active_index = 0
                    primary.mark_success()

                    event = FailoverEvent(
                        from_provider=old_provider.name,
                        to_provider=primary.name,
                        reason=f"{primary.name} 恢复探测成功",
                    )
                    self._failover_events.append(event)
                    print(f"✅ [LLMProvider] 恢复成功: {primary.name}")
                    return event

                except Exception as e:
                    primary.status = ProviderStatus.FAILED
                    primary.mark_failure()
                    print(f"❌ [LLMProvider] 恢复探测失败: {primary.name} ({e})")
                    return None

            return None

    async def execute_with_failover(
        self,
        create_func: Callable[[AsyncOpenAI, str], Awaitable[Any]],
        is_streaming: bool = False,  # AGENT-18: 流式标记（半截流式不重试）
    ) -> tuple[Any, Optional[FailoverEvent]]:
        """
        带自动 failover 和 AGENT-18 重试机制的 LLM 调用。

        Args:
            create_func: 调用函数，签名为 async (client, model) -> response
            is_streaming: AGENT-18 标志，表示是否为流式调用（半截流式不重试）

        Returns:
            (response, failover_event) — failover_event 仅在发生切换时非 None

        AGENT-18 Retry Semantics (codex responses_retry.rs):
        - Retryable errors: HTTP 429 / timeout / 5xx / connection reset → exponential backoff + jitter, max 3 attempts
        - Non-retryable errors: auth / 400 / param → immediate failure, no retry
        - Half-stream safety: if streaming response already emitted, cancel retry (防副作用)
        - FailureTracker integration: exhausted retries recorded to AGENT-02 tracker (via consecutive_failures counter)
        """
        from hermes_agent.retry_classifier import (
            CONTENT_FILTER_ERROR_CODE,
            ExponentialBackoff,
            RetryBudget,
            RetryConfig,
            RetryDecision,
            classify_llm_error,
        )

        max_providers = len(self.all_providers)
        last_error: Optional[Exception] = None
        failover_event: Optional[FailoverEvent] = None

        # AGENT-18: Retry budget（从环境变量读取 max_attempts / base_delay / max_delay）
        cfg = RetryConfig.from_env()
        retry_budget = RetryBudget(cfg)
        backoff = ExponentialBackoff(base_delay=cfg.base_delay, max_delay=cfg.max_delay, exponent=cfg.exponent)
        retry_budget.start()

        for attempt in range(max_providers):
            provider = self.get_active_provider()
            current_provider_attempt = 0  # Per-provider retry count
            backoff.reset()

            while current_provider_attempt < retry_budget.max_attempts:
                try:
                    response = await create_func(provider.client, provider.model)
                    await self.report_success(provider)
                    return response, failover_event  # AGENT-06: 返回切换事件（如果有）

                except Exception as e:
                    last_error = e
                    current_provider_attempt += 1

                    # AGENT-18: Classify error
                    status_code = getattr(e, "status_code", None)
                    response_headers = getattr(getattr(e, "response", None), "headers", None)
                    error_info = classify_llm_error(e, status_code, response_headers)

                    # Half-streaming protection: if we've already yielded data, don't retry
                    if is_streaming and getattr(self, "_stream_emitted", False):
                        logger.warning(
                            "⚠️ [AGENT-18] half-stream detected, cancelling retry for %s",
                            type(e).__name__,
                        )
                        raise e  # 立即抛出，不再重试

                    # 内容过滤：返回特定错误码，不重试
                    if error_info.category.value == "content_filter":
                        wrapped = RuntimeError(f"[{CONTENT_FILTER_ERROR_CODE}] {e}")
                        wrapped.__cause__ = e
                        logger.error("[AGENT-18] 内容过滤/安全拦截，不重试: %s", e)
                        await self.report_failure(provider)
                        raise wrapped

                    # 不可重试错误（4xx 参数 / 鉴权）：直接抛出并落 FailureTracker
                    if not error_info.is_retryable:
                        logger.error(
                            "❌ [AGENT-18] 不可重试错误 (%s, status=%s): %s",
                            error_info.category.value,
                            status_code,
                            e,
                        )
                        await self.report_failure(provider)
                        break  # 跳出当前 provider，尝试 fallback

                    # 检查重试预算（次数 / 总超时）
                    can_retry, reason = retry_budget.can_retry(error_info)
                    if not can_retry:
                        logger.warning(
                            "💔 [AGENT-18] 重试预算耗尽: %s (attempt %d/%d)",
                            reason,
                            current_provider_attempt,
                            retry_budget.max_attempts,
                        )
                        await self.report_failure(provider)
                        break  # 跳出当前 provider，尝试 fallback

                    # 计算退避延迟：429 优先使用 Retry-After 头
                    if error_info.category.value == "rate_limit" and error_info.retry_after is not None:
                        delay = min(error_info.retry_after, cfg.max_delay)
                        decision = RetryDecision.RETRY_BACKOFF
                    else:
                        delay = backoff.next_attempt_delay()
                        if error_info.decision == RetryDecision.RETRY_IMMEDIATE and delay <= 1.0:
                            delay = 0.0
                        decision = retry_budget.log[-1].decision if retry_budget.log else error_info.decision

                    # 需求 4：每次重试前记录结构化日志
                    retry_budget.record_retry(
                        error_info,
                        delay,
                        decision,
                        reason="proceeding with retry",
                    )

                    logger.warning(
                        "🔄 [AGENT-18] 可重试错误: %s (%s) | 退避 %.2fs | attempt %d/%d",
                        type(e).__name__,
                        error_info.category.value,
                        delay,
                        current_provider_attempt,
                        retry_budget.max_attempts,
                    )

                    # Apply backoff
                    await asyncio.sleep(delay)

            # Current provider exhausted, try next provider
            event = await self.report_failure(provider)
            if event is not None:
                failover_event = event
                print(f"🔄 [LLMProvider] switching provider: {event.from_provider} → {event.to_provider}")
                continue

            # No more providers
            raise

        # All providers and attempts exhausted
        raise last_error or RuntimeError("所有 LLM provider 均不可用")

    def get_status_summary(self) -> Dict[str, Any]:
        """获取所有 provider 状态摘要（用于调试和监控）"""
        return {
            "active_provider": self.get_active_provider().name,
            "is_degraded": self.is_degraded(),
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "priority": p.priority,
                    "status": p.status.value,
                    "consecutive_failures": p.consecutive_failures,
                    "last_success": p.last_success_time,
                    "last_failure": p.last_failure_time,
                }
                for p in self.all_providers
            ],
            "failover_events_count": len(self._failover_events),
        }


# ========================================================================
# 便捷函数
# ========================================================================


def create_provider_router_from_env() -> LLMProviderRouter:
    """从环境变量创建 Provider Router（推荐入口）"""
    return LLMProviderRouter.from_env()
