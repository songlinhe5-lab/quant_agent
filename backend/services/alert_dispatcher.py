"""
ALERT-03a · AlertDispatcher 统一推送路由

全系统通知的唯一出口——AlertEngine / RateLimitAlertMonitor / PaperSettlement /
Kill Switch / Hermes Agent 全部经此投递，禁止各模块直连 Webhook/Telegram。

核心组件：
- PriorityResolver: severity + source → P0~P3
- ChannelPlanner: 优先级 × 规则 channels → 通道计划
- CooldownGate: 通道级冷却（fingerprint 去重）
- DeliveryRecord: 投递记录契约
- AlertDispatcher: 编排以上组件，完成 dispatch 全流程

设计文档：docs/18. 多通道推送路由设计.md
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertSeverity,
    NotificationPriority,
)

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 通道适配器协议
# ─────────────────────────────────────────────


class ChannelAdapter(Protocol):
    """通道适配器接口"""

    @property
    def channel(self) -> AlertChannel: ...

    @property
    def enabled(self) -> bool: ...

    async def send(self, event: AlertEvent, priority: NotificationPriority) -> bool:
        """发送告警，返回是否成功"""
        ...


# ─────────────────────────────────────────────
# PriorityResolver
# ─────────────────────────────────────────────


class PriorityResolver:
    """优先级解析器：severity + source → P0~P3

    解析规则（按序匹配，首条命中）：
    1. source == kill_switch / oms_circuit → P0
    2. severity == CRITICAL 且 source ∈ {rate_limit, system} → P0
    3. severity == CRITICAL 或 rule_type == strategy_signal → P1
    4. severity == WARNING 或 source == trade_fill → P2
    5. 其他 → P3
    """

    # P0 来源
    _P0_SOURCES = {"kill_switch", "oms_circuit"}
    # P0 组合来源
    _P0_COMBINED_SOURCES = {"rate_limit", "system"}

    def resolve(self, event: AlertEvent, rule: Optional[AlertRule] = None) -> NotificationPriority:
        """解析事件优先级"""
        # 如果事件已显式指定优先级，直接使用
        if event.priority is not None:
            return event.priority

        source = event.source
        severity = event.severity

        # Rule 1: kill_switch / oms_circuit → P0
        if source in self._P0_SOURCES:
            return NotificationPriority.P0

        # Rule 2: CRITICAL + (rate_limit | system) → P0
        if severity == AlertSeverity.CRITICAL and source in self._P0_COMBINED_SOURCES:
            return NotificationPriority.P0

        # Rule 3: CRITICAL 或 strategy_signal → P1
        if severity == AlertSeverity.CRITICAL:
            return NotificationPriority.P1

        # Rule 4: WARNING 或 trade_fill → P2
        if severity == AlertSeverity.WARNING or source == "trade_fill":
            return NotificationPriority.P2

        # Rule 5: 其他 → P3
        return NotificationPriority.P3


# ─────────────────────────────────────────────
# ChannelPlanner
# ─────────────────────────────────────────────


class ChannelPlanner:
    """通道计划器：优先级 × 用户 channels → 实际推送通道列表

    路由矩阵（设计文档 §3.2）：
    - P0: 强制全开 in_app + feishu + telegram（安全例外）
    - P1: 用户 channels；默认 in_app + telegram
    - P2: 用户 channels；默认 in_app + feishu
    - P3: 用户 channels；默认仅 in_app
    """

    _DEFAULT_CHANNELS = {
        NotificationPriority.P0: [AlertChannel.IN_APP, AlertChannel.FEISHU, AlertChannel.TELEGRAM],
        NotificationPriority.P1: [AlertChannel.IN_APP, AlertChannel.TELEGRAM],
        NotificationPriority.P2: [AlertChannel.IN_APP, AlertChannel.FEISHU],
        NotificationPriority.P3: [AlertChannel.IN_APP],
    }

    def plan(
        self,
        priority: NotificationPriority,
        user_channels: Optional[List[AlertChannel]] = None,
    ) -> List[AlertChannel]:
        """计算实际推送通道"""
        # P0 强制全开（安全例外）
        if priority == NotificationPriority.P0:
            return list(self._DEFAULT_CHANNELS[NotificationPriority.P0])

        # 其他优先级：使用用户指定通道，或默认通道
        if user_channels:
            # 确保 in_app 始终包含（零成本）
            channels = list(user_channels)
            if AlertChannel.IN_APP not in channels:
                channels.insert(0, AlertChannel.IN_APP)
            return channels

        return list(self._DEFAULT_CHANNELS[priority])

    @staticmethod
    def is_parallel(priority: NotificationPriority) -> bool:
        """是否并行推送（P3 为串行）"""
        return priority != NotificationPriority.P3


# ─────────────────────────────────────────────
# CooldownGate（通道级冷却）
# ─────────────────────────────────────────────


# 优先级 → 通道冷却秒数
_COOLDOWN_TTL = {
    NotificationPriority.P0: 60,
    NotificationPriority.P1: 300,
    NotificationPriority.P2: 300,
    NotificationPriority.P3: 900,
}


class CooldownGate:
    """通道级冷却门控

    键：quant:alerts:cooldown:{channel}:{fingerprint}
    fingerprint = sha256(source + rule_id + ticker + severity)[:16]
    in_app 不受冷却限制。
    """

    def __init__(self, redis_client: Optional["aioredis.Redis"] = None) -> None:
        self._redis = redis_client
        # 内存 fallback（无 Redis 时）
        self._memory_cooldowns: Dict[str, float] = {}

    @staticmethod
    def compute_fingerprint(event: AlertEvent) -> str:
        """计算冷却 fingerprint"""
        raw = f"{event.source}:{event.rule_id}:{event.ticker}:{event.severity.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def is_blocked(self, channel: AlertChannel, event: AlertEvent, priority: NotificationPriority) -> bool:
        """检查通道是否被冷却阻断

        in_app 永远不冷却。
        """
        if channel == AlertChannel.IN_APP:
            return False

        fingerprint = self.compute_fingerprint(event)
        cooldown_key = f"{channel.value}:{fingerprint}"
        ttl = _COOLDOWN_TTL.get(priority, 300)

        if self._redis:
            redis_key = f"quant:alerts:cooldown:{cooldown_key}"
            exists = await self._redis.exists(redis_key)
            if exists:
                return True
            # 设置冷却
            await self._redis.set(redis_key, "1", ex=ttl)
            return False

        # 内存 fallback
        now = time.time()
        if cooldown_key in self._memory_cooldowns:
            if now - self._memory_cooldowns[cooldown_key] < ttl:
                return True
        self._memory_cooldowns[cooldown_key] = now
        return False


# ─────────────────────────────────────────────
# DeliveryRecord
# ─────────────────────────────────────────────


class DeliveryStatus(str, Enum):
    """投递状态"""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # 被冷却抑制
    PARTIAL = "partial"


@dataclass
class DeliveryRecord:
    """单次投递记录"""

    delivery_id: str
    event_id: str
    channel: str
    priority: str
    status: str
    attempt: int = 1
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class DispatchResult:
    """dispatch 返回结果"""

    event_id: str
    priority: NotificationPriority
    channels: Dict[str, str]  # channel_value → status
    suppressed_channels: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# RetryQueue
# ─────────────────────────────────────────────


# 优先级 → 退避序列（秒）+ 最大尝试次数
_RETRY_CONFIG = {
    NotificationPriority.P0: ([1, 2, 4, 8, 16], 5),
    NotificationPriority.P1: ([1, 4, 16], 3),
    NotificationPriority.P2: ([1, 4], 2),
    NotificationPriority.P3: ([], 1),  # 不重试
}

# 可重试的 HTTP 状态码
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryQueue:
    """重试队列（asyncio 内存队列 + Redis DLQ）"""

    def __init__(self, redis_client: Optional["aioredis.Redis"] = None) -> None:
        self._redis = redis_client
        self._pending_retries: List[asyncio.Task] = []

    async def schedule_retry(
        self,
        adapter: ChannelAdapter,
        event: AlertEvent,
        priority: NotificationPriority,
        attempt: int,
        error: str,
    ) -> bool:
        """安排重试

        Returns:
            True = 已安排重试, False = 已达上限，进入 DLQ
        """
        backoff_seq, max_attempts = _RETRY_CONFIG.get(priority, ([], 1))

        if attempt >= max_attempts or not backoff_seq:
            # 进入 DLQ
            await self._send_to_dlq(event, adapter.channel.value, attempt, error)
            return False

        delay = backoff_seq[min(attempt - 1, len(backoff_seq) - 1)]

        async def _retry_later():
            await asyncio.sleep(delay)
            try:
                success = await adapter.send(event, priority)
                if success:
                    logger.info(f"[RetryQueue] 重试成功: {adapter.channel.value} attempt={attempt + 1}")
                else:
                    # 继续重试
                    await self.schedule_retry(adapter, event, priority, attempt + 1, "retry failed")
            except Exception as e:
                logger.warning(f"[RetryQueue] 重试异常: {e}")
                await self.schedule_retry(adapter, event, priority, attempt + 1, str(e))

        task = asyncio.create_task(_retry_later())
        self._pending_retries.append(task)
        return True

    async def _send_to_dlq(self, event: AlertEvent, channel: str, attempt: int, error: str) -> None:
        """写入 Dead Letter Queue"""
        import json

        dlq_entry = {
            "event_id": event.event_id,
            "channel": channel,
            "attempt": attempt,
            "error": error,
            "message": event.message[:200],
            "ts": time.time(),
        }

        if self._redis:
            try:
                await self._redis.lpush("quant:alerts:dlq", json.dumps(dlq_entry))
                await self._redis.ltrim("quant:alerts:dlq", 0, 9999)
            except Exception as e:
                logger.error(f"[RetryQueue] DLQ 写入失败: {e}")

        logger.error(f"[RetryQueue] DLQ: event={event.event_id} channel={channel} attempt={attempt} error={error}")

    def cleanup(self) -> None:
        """清理已完成的重试任务"""
        self._pending_retries = [t for t in self._pending_retries if not t.done()]


# ─────────────────────────────────────────────
# AlertDispatcher 核心
# ─────────────────────────────────────────────


class AlertDispatcher:
    """告警调度器——全系统通知的唯一出口

    用法:
        dispatcher = AlertDispatcher(redis_client)
        dispatcher.register_adapter(feishu_adapter)
        dispatcher.register_adapter(telegram_adapter)
        dispatcher.register_adapter(in_app_adapter)
        await dispatcher.start()

        result = await dispatcher.dispatch(event, rule=alert_rule)
    """

    def __init__(self, redis_client: Optional["aioredis.Redis"] = None) -> None:
        self._redis = redis_client
        self._adapters: Dict[AlertChannel, ChannelAdapter] = {}
        self._resolver = PriorityResolver()
        self._planner = ChannelPlanner()
        self._cooldown_gate = CooldownGate(redis_client)
        self._retry_queue = RetryQueue(redis_client)
        self._delivery_records: Dict[str, List[DeliveryRecord]] = {}
        self._started = False

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """注册通道适配器"""
        self._adapters[adapter.channel] = adapter
        logger.info(f"[AlertDispatcher] 注册适配器: {adapter.channel.value} (enabled={adapter.enabled})")

    async def start(self) -> None:
        """启动 dispatcher"""
        self._started = True
        logger.info("[AlertDispatcher] ✅ 已启动")

    async def stop(self) -> None:
        """停止 dispatcher"""
        self._started = False
        self._retry_queue.cleanup()
        logger.info("[AlertDispatcher] 已停止")

    async def dispatch(
        self,
        event: AlertEvent,
        rule: Optional[AlertRule] = None,
        channels: Optional[List[AlertChannel]] = None,
    ) -> DispatchResult:
        """核心调度方法

        1. 解析优先级
        2. 规划通道
        3. 冷却检查
        4. 执行投递
        5. 记录结果
        """
        # 1. 解析优先级
        priority = self._resolver.resolve(event, rule)

        # 2. 规划通道
        user_channels = channels or (rule.channels if rule else None) or (event.channels if event.channels else None)
        planned_channels = self._planner.plan(priority, user_channels)

        # 3. 过滤不可用适配器
        available_channels = []
        for ch in planned_channels:
            adapter = self._adapters.get(ch)
            if adapter and adapter.enabled:
                available_channels.append(ch)
            elif ch == AlertChannel.IN_APP:
                # in_app 始终可用（即使未注册适配器，也记录成功）
                available_channels.append(ch)

        # 4. 冷却检查 + 投递
        result_channels: Dict[str, str] = {}
        suppressed: List[str] = []
        is_parallel = self._planner.is_parallel(priority)

        if is_parallel:
            # 并行投递
            tasks = []
            for ch in available_channels:
                tasks.append(self._deliver_one(ch, event, priority, suppressed))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for ch, res in zip(available_channels, results):
                if isinstance(res, Exception):
                    result_channels[ch.value] = "failed"
                else:
                    result_channels[ch.value] = res
        else:
            # 串行投递（P3: in_app 成功则跳过外部）
            for ch in available_channels:
                status = await self._deliver_one(ch, event, priority, suppressed)
                result_channels[ch.value] = status
                # P3: in_app 成功则跳过外部通道
                if ch == AlertChannel.IN_APP and status == "success":
                    for remaining_ch in available_channels:
                        if remaining_ch != AlertChannel.IN_APP:
                            suppressed.append(remaining_ch.value)
                            result_channels[remaining_ch.value] = "suppressed"
                    break

        return DispatchResult(
            event_id=event.event_id,
            priority=priority,
            channels=result_channels,
            suppressed_channels=suppressed,
        )

    async def _deliver_one(
        self,
        channel: AlertChannel,
        event: AlertEvent,
        priority: NotificationPriority,
        suppressed: List[str],
    ) -> str:
        """投递单个通道"""
        # 冷却检查
        blocked = await self._cooldown_gate.is_blocked(channel, event, priority)
        if blocked:
            suppressed.append(channel.value)
            self._record_delivery(event.event_id, channel.value, priority.value, "suppressed")
            return "suppressed"

        # in_app 特殊处理（直接 Redis publish）
        if channel == AlertChannel.IN_APP:
            adapter = self._adapters.get(channel)
            if adapter:
                start = time.time()
                try:
                    success = await adapter.send(event, priority)
                    latency = (time.time() - start) * 1000
                    status = "success" if success else "failed"
                    self._record_delivery(event.event_id, channel.value, priority.value, status, latency_ms=latency)
                    return status
                except Exception as e:
                    self._record_delivery(event.event_id, channel.value, priority.value, "failed", error=str(e))
                    return "failed"
            else:
                # 无适配器也记录成功（Redis publish 不抛错即成功）
                self._record_delivery(event.event_id, channel.value, priority.value, "success")
                return "success"

        # 外部通道
        adapter = self._adapters.get(channel)
        if not adapter:
            self._record_delivery(event.event_id, channel.value, priority.value, "failed", error="no adapter")
            return "failed"

        start = time.time()
        try:
            success = await adapter.send(event, priority)
            latency = (time.time() - start) * 1000

            if success:
                self._record_delivery(event.event_id, channel.value, priority.value, "success", latency_ms=latency)
                return "success"
            else:
                # 重试
                retry_scheduled = await self._retry_queue.schedule_retry(
                    adapter, event, priority, attempt=1, error="send returned false"
                )
                status = "pending" if retry_scheduled else "failed"
                self._record_delivery(event.event_id, channel.value, priority.value, status, latency_ms=latency)
                return status

        except Exception as e:
            latency = (time.time() - start) * 1000
            retry_scheduled = await self._retry_queue.schedule_retry(adapter, event, priority, attempt=1, error=str(e))
            status = "pending" if retry_scheduled else "failed"
            self._record_delivery(
                event.event_id, channel.value, priority.value, status, latency_ms=latency, error=str(e)
            )
            return status

    def _record_delivery(
        self,
        event_id: str,
        channel: str,
        priority: str,
        status: str,
        attempt: int = 1,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """记录投递"""
        record = DeliveryRecord(
            delivery_id=str(uuid.uuid4()),
            event_id=event_id,
            channel=channel,
            priority=priority,
            status=status,
            attempt=attempt,
            latency_ms=latency_ms,
            error=error,
        )
        if event_id not in self._delivery_records:
            self._delivery_records[event_id] = []
        self._delivery_records[event_id].append(record)

    def get_delivery_records(self, event_id: str) -> List[DeliveryRecord]:
        """获取事件的投递记录"""
        return self._delivery_records.get(event_id, [])

    async def health(self) -> Dict[str, Any]:
        """各适配器状态"""
        return {
            "started": self._started,
            "adapters": {ch.value: {"enabled": adapter.enabled} for ch, adapter in self._adapters.items()},
            "pending_retries": len(self._retry_queue._pending_retries),
        }


# ─────────────────────────────────────────────
# 全局单例（延迟初始化）
# ─────────────────────────────────────────────

_alert_dispatcher: Optional[AlertDispatcher] = None


def get_alert_dispatcher() -> AlertDispatcher:
    """获取全局 AlertDispatcher 实例"""
    global _alert_dispatcher
    if _alert_dispatcher is None:
        _alert_dispatcher = AlertDispatcher()
    return _alert_dispatcher
