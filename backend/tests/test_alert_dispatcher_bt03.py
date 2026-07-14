"""
ALERT-03a/b · AlertDispatcher + 三通道适配器测试

覆盖：
- PriorityResolver: 优先级解析全矩阵
- ChannelPlanner: 通道计划（P0 强制全开 / P3 串行）
- CooldownGate: 通道级冷却（fingerprint + TTL）
- AlertDispatcher: dispatch 编排 + 并行/串行投递
- InAppAdapter: Redis PubSub 推送
- FeishuAdapter: httpx Mock 飞书 Webhook
- TelegramAdapter: httpx Mock Bot API
- RetryQueue: 重试 + DLQ
- DispatchResult: 结果结构

测试要求：≥85% 覆盖率
"""

import asyncio
import json
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    NotificationPriority,
)
from backend.services.alert_adapters.feishu import FeishuAdapter
from backend.services.alert_adapters.in_app import ALERT_PUSH_CHANNEL, InAppAdapter
from backend.services.alert_adapters.telegram import TelegramAdapter
from backend.services.alert_dispatcher import (
    AlertDispatcher,
    ChannelPlanner,
    CooldownGate,
    PriorityResolver,
    RetryQueue,
)

# ─────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────


def make_event(
    source: str = "user_rule",
    severity: AlertSeverity = AlertSeverity.WARNING,
    priority: Optional[NotificationPriority] = None,
    ticker: str = "AAPL",
    rule_id: str = "rule-001",
    message: str = "Test alert",
) -> AlertEvent:
    """创建测试用 AlertEvent"""
    return AlertEvent(
        event_id=f"evt-{id(message)}",
        rule_id=rule_id,
        ticker=ticker,
        rule_type=AlertRuleType.PRICE_ABOVE,
        severity=severity,
        message=message,
        trigger_value=200.0,
        threshold=195.0,
        source=source,
        priority=priority,
    )


def make_rule(
    channels: Optional[List[AlertChannel]] = None,
    severity: AlertSeverity = AlertSeverity.WARNING,
) -> AlertRule:
    """创建测试用 AlertRule"""
    return AlertRule(
        rule_id="rule-001",
        name="Test Rule",
        ticker="AAPL",
        rule_type=AlertRuleType.PRICE_ABOVE,
        threshold=195.0,
        severity=severity,
        channels=channels or [AlertChannel.IN_APP],
    )


class MockAdapter:
    """Mock 通道适配器"""

    def __init__(self, channel: AlertChannel, enabled: bool = True, should_succeed: bool = True):
        self._channel = channel
        self._enabled = enabled
        self._should_succeed = should_succeed
        self.send_count = 0

    @property
    def channel(self) -> AlertChannel:
        return self._channel

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def send(self, event: AlertEvent, priority: NotificationPriority) -> bool:
        self.send_count += 1
        return self._should_succeed


# ─────────────────────────────────────────────
# PriorityResolver 测试
# ─────────────────────────────────────────────


class TestPriorityResolver:
    """优先级解析器测试"""

    @pytest.fixture
    def resolver(self):
        return PriorityResolver()

    def test_kill_switch_is_p0(self, resolver):
        """kill_switch 来源 → P0"""
        event = make_event(source="kill_switch", severity=AlertSeverity.WARNING)
        assert resolver.resolve(event) == NotificationPriority.P0

    def test_oms_circuit_is_p0(self, resolver):
        """oms_circuit 来源 → P0"""
        event = make_event(source="oms_circuit")
        assert resolver.resolve(event) == NotificationPriority.P0

    def test_critical_with_rate_limit_is_p0(self, resolver):
        """CRITICAL + rate_limit → P0"""
        event = make_event(source="rate_limit", severity=AlertSeverity.CRITICAL)
        assert resolver.resolve(event) == NotificationPriority.P0

    def test_critical_with_system_is_p0(self, resolver):
        """CRITICAL + system → P0"""
        event = make_event(source="system", severity=AlertSeverity.CRITICAL)
        assert resolver.resolve(event) == NotificationPriority.P0

    def test_critical_is_p1(self, resolver):
        """CRITICAL（非 rate_limit/system）→ P1"""
        event = make_event(source="user_rule", severity=AlertSeverity.CRITICAL)
        assert resolver.resolve(event) == NotificationPriority.P1

    def test_warning_is_p2(self, resolver):
        """WARNING → P2"""
        event = make_event(severity=AlertSeverity.WARNING)
        assert resolver.resolve(event) == NotificationPriority.P2

    def test_trade_fill_is_p2(self, resolver):
        """trade_fill 来源 → P2"""
        event = make_event(source="trade_fill", severity=AlertSeverity.INFO)
        assert resolver.resolve(event) == NotificationPriority.P2

    def test_info_is_p3(self, resolver):
        """INFO → P3"""
        event = make_event(severity=AlertSeverity.INFO)
        assert resolver.resolve(event) == NotificationPriority.P3

    def test_explicit_priority_overrides(self, resolver):
        """显式指定优先级覆盖解析"""
        event = make_event(severity=AlertSeverity.INFO, priority=NotificationPriority.P0)
        assert resolver.resolve(event) == NotificationPriority.P0

    def test_agent_source_is_p3(self, resolver):
        """agent 来源 + INFO → P3"""
        event = make_event(source="agent", severity=AlertSeverity.INFO)
        assert resolver.resolve(event) == NotificationPriority.P3


# ─────────────────────────────────────────────
# ChannelPlanner 测试
# ─────────────────────────────────────────────


class TestChannelPlanner:
    """通道计划器测试"""

    @pytest.fixture
    def planner(self):
        return ChannelPlanner()

    def test_p0_forces_all_channels(self, planner):
        """P0 强制全开三通道"""
        channels = planner.plan(NotificationPriority.P0, user_channels=[AlertChannel.IN_APP])
        assert AlertChannel.IN_APP in channels
        assert AlertChannel.FEISHU in channels
        assert AlertChannel.TELEGRAM in channels

    def test_p1_uses_user_channels(self, planner):
        """P1 使用用户指定通道"""
        channels = planner.plan(NotificationPriority.P1, user_channels=[AlertChannel.TELEGRAM])
        assert AlertChannel.TELEGRAM in channels
        assert AlertChannel.IN_APP in channels  # 始终包含 in_app

    def test_p1_default_channels(self, planner):
        """P1 无用户指定时使用默认"""
        channels = planner.plan(NotificationPriority.P1)
        assert AlertChannel.IN_APP in channels
        assert AlertChannel.TELEGRAM in channels

    def test_p2_default_channels(self, planner):
        """P2 默认 in_app + feishu"""
        channels = planner.plan(NotificationPriority.P2)
        assert AlertChannel.IN_APP in channels
        assert AlertChannel.FEISHU in channels

    def test_p3_default_only_in_app(self, planner):
        """P3 默认仅 in_app"""
        channels = planner.plan(NotificationPriority.P3)
        assert channels == [AlertChannel.IN_APP]

    def test_p3_is_serial(self, planner):
        """P3 串行模式"""
        assert not ChannelPlanner.is_parallel(NotificationPriority.P3)

    def test_p0_is_parallel(self, planner):
        """P0 并行模式"""
        assert ChannelPlanner.is_parallel(NotificationPriority.P0)

    def test_user_channels_adds_in_app_if_missing(self, planner):
        """用户通道不含 in_app 时自动补充"""
        channels = planner.plan(NotificationPriority.P2, user_channels=[AlertChannel.FEISHU])
        assert AlertChannel.IN_APP in channels
        assert AlertChannel.FEISHU in channels


# ─────────────────────────────────────────────
# CooldownGate 测试
# ─────────────────────────────────────────────


class TestCooldownGate:
    """通道级冷却测试"""

    def test_in_app_never_cooldown(self):
        """in_app 永远不冷却"""
        gate = CooldownGate()
        event = make_event()
        # 内存模式
        assert not asyncio.get_event_loop().run_until_complete(
            gate.is_blocked(AlertChannel.IN_APP, event, NotificationPriority.P1)
        )

    def test_fingerprint_deterministic(self):
        """fingerprint 计算确定性"""
        event = make_event()
        fp1 = CooldownGate.compute_fingerprint(event)
        fp2 = CooldownGate.compute_fingerprint(event)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_different_events_different_fingerprint(self):
        """不同事件不同 fingerprint"""
        e1 = make_event(ticker="AAPL")
        e2 = make_event(ticker="MSFT")
        assert CooldownGate.compute_fingerprint(e1) != CooldownGate.compute_fingerprint(e2)

    def test_memory_cooldown_blocks_second_call(self):
        """内存冷却模式：第二次调用被阻断"""
        gate = CooldownGate()
        event = make_event()
        loop = asyncio.get_event_loop()

        # 第一次：不阻断
        blocked1 = loop.run_until_complete(
            gate.is_blocked(AlertChannel.FEISHU, event, NotificationPriority.P2)
        )
        assert not blocked1

        # 第二次：被阻断（冷却期内）
        blocked2 = loop.run_until_complete(
            gate.is_blocked(AlertChannel.FEISHU, event, NotificationPriority.P2)
        )
        assert blocked2


# ─────────────────────────────────────────────
# AlertDispatcher 测试
# ─────────────────────────────────────────────


class TestAlertDispatcher:
    """AlertDispatcher 核心测试"""

    @pytest.fixture
    def dispatcher(self):
        d = AlertDispatcher()
        return d

    @pytest.mark.asyncio
    async def test_dispatch_with_no_adapters(self, dispatcher):
        """无适配器时 in_app 仍记录成功"""
        event = make_event()
        result = await dispatcher.dispatch(event)
        assert result.event_id == event.event_id
        assert result.channels.get("in_app") == "success"

    @pytest.mark.asyncio
    async def test_dispatch_with_mock_adapter(self, dispatcher):
        """Mock 适配器成功投递"""
        adapter = MockAdapter(AlertChannel.FEISHU)
        dispatcher.register_adapter(adapter)

        event = make_event()
        result = await dispatcher.dispatch(event, channels=[AlertChannel.FEISHU])

        assert adapter.send_count == 1
        assert result.channels.get("feishu") == "success"

    @pytest.mark.asyncio
    async def test_p0_forces_all_channels(self, dispatcher):
        """P0 强制全开三通道"""
        in_app = MockAdapter(AlertChannel.IN_APP)
        feishu = MockAdapter(AlertChannel.FEISHU)
        telegram = MockAdapter(AlertChannel.TELEGRAM)
        dispatcher.register_adapter(in_app)
        dispatcher.register_adapter(feishu)
        dispatcher.register_adapter(telegram)

        event = make_event(source="kill_switch")  # P0
        result = await dispatcher.dispatch(event, channels=[AlertChannel.IN_APP])  # 用户只选 in_app

        # P0 强制全开
        assert in_app.send_count == 1
        assert feishu.send_count == 1
        assert telegram.send_count == 1
        assert result.priority == NotificationPriority.P0

    @pytest.mark.asyncio
    async def test_p3_serial_skips_external_on_in_app_success(self, dispatcher):
        """P3 串行：in_app 成功则跳过外部"""
        in_app = MockAdapter(AlertChannel.IN_APP)
        feishu = MockAdapter(AlertChannel.FEISHU)
        dispatcher.register_adapter(in_app)
        dispatcher.register_adapter(feishu)

        event = make_event(severity=AlertSeverity.INFO)  # P3
        result = await dispatcher.dispatch(event, channels=[AlertChannel.IN_APP, AlertChannel.FEISHU])

        assert in_app.send_count == 1
        assert feishu.send_count == 0  # 被跳过
        assert "feishu" in result.suppressed_channels

    @pytest.mark.asyncio
    async def test_disabled_adapter_skipped(self, dispatcher):
        """禁用适配器被跳过"""
        adapter = MockAdapter(AlertChannel.TELEGRAM, enabled=False)
        dispatcher.register_adapter(adapter)

        event = make_event()
        await dispatcher.dispatch(event, channels=[AlertChannel.TELEGRAM])

        assert adapter.send_count == 0
        # telegram 不在结果中（被过滤）

    @pytest.mark.asyncio
    async def test_delivery_records_created(self, dispatcher):
        """投递记录正确创建"""
        adapter = MockAdapter(AlertChannel.FEISHU)
        dispatcher.register_adapter(adapter)

        event = make_event()
        await dispatcher.dispatch(event, channels=[AlertChannel.FEISHU])

        records = dispatcher.get_delivery_records(event.event_id)
        assert len(records) > 0
        assert records[0].event_id == event.event_id

    @pytest.mark.asyncio
    async def test_health_returns_adapter_status(self, dispatcher):
        """health 返回适配器状态"""
        adapter = MockAdapter(AlertChannel.FEISHU)
        dispatcher.register_adapter(adapter)

        health = await dispatcher.health()
        assert "feishu" in health["adapters"]
        assert health["adapters"]["feishu"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_dispatch_with_rule(self, dispatcher):
        """传入 rule 时使用 rule.channels"""
        adapter = MockAdapter(AlertChannel.FEISHU)
        dispatcher.register_adapter(adapter)

        event = make_event()
        rule = make_rule(channels=[AlertChannel.FEISHU])
        await dispatcher.dispatch(event, rule=rule)

        assert adapter.send_count == 1


# ─────────────────────────────────────────────
# InAppAdapter 测试
# ─────────────────────────────────────────────


class TestInAppAdapter:
    """InApp 适配器测试"""

    def test_channel_is_in_app(self):
        adapter = InAppAdapter()
        assert adapter.channel == AlertChannel.IN_APP

    def test_always_enabled(self):
        adapter = InAppAdapter()
        assert adapter.enabled is True

    @pytest.mark.asyncio
    async def test_send_without_redis_succeeds(self):
        """无 Redis 时返回 True（不算失败）"""
        adapter = InAppAdapter(redis_client=None)
        event = make_event()
        result = await adapter.send(event, NotificationPriority.P1)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_with_redis_publishes(self):
        """有 Redis 时正确 publish"""
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        adapter = InAppAdapter(redis_client=mock_redis)
        event = make_event()
        result = await adapter.send(event, NotificationPriority.P1)

        assert result is True
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == ALERT_PUSH_CHANNEL

        # 验证 payload 结构
        payload = json.loads(call_args[0][1])
        assert payload["type"] == "alert"
        assert payload["event_id"] == event.event_id
        assert payload["priority"] == "p1"

    def test_default_ui_hint_p0(self):
        """P0 默认 ui_hint"""
        hint = InAppAdapter._default_ui_hint(NotificationPriority.P0)
        assert hint["mode"] == "fullscreen"
        assert hint["flash"] is True

    def test_default_ui_hint_p3(self):
        """P3 默认 ui_hint"""
        hint = InAppAdapter._default_ui_hint(NotificationPriority.P3)
        assert hint["mode"] == "badge"


# ─────────────────────────────────────────────
# FeishuAdapter 测试
# ─────────────────────────────────────────────


class TestFeishuAdapter:
    """飞书适配器测试"""

    def test_disabled_without_config(self):
        """无配置时禁用"""
        with patch.dict("os.environ", {}, clear=True):
            adapter = FeishuAdapter(webhook_url=None)
            assert adapter.enabled is False

    def test_enabled_with_url(self):
        """有 URL 时启用"""
        adapter = FeishuAdapter(webhook_url="https://open.feishu.cn/test")
        assert adapter.enabled is True

    @pytest.mark.asyncio
    async def test_send_when_disabled_returns_false(self):
        """禁用时返回 False"""
        with patch.dict("os.environ", {}, clear=True):
            adapter = FeishuAdapter(webhook_url=None)
            event = make_event()
            result = await adapter.send(event, NotificationPriority.P1)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_with_invalid_url(self):
        """无效 URL 返回 False"""
        adapter = FeishuAdapter(webhook_url="not-a-url")
        event = make_event()
        result = await adapter.send(event, NotificationPriority.P1)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """成功发送"""
        adapter = FeishuAdapter(webhook_url="https://open.feishu.cn/test")
        event = make_event()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await adapter.send(event, NotificationPriority.P1)
            assert result is True

    @pytest.mark.asyncio
    async def test_send_p0_uses_card_message(self):
        """P0 使用卡片消息"""
        adapter = FeishuAdapter(webhook_url="https://open.feishu.cn/test")
        event = make_event()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await adapter.send(event, NotificationPriority.P0)

            # 验证使用卡片消息
            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert payload["msg_type"] == "interactive"
            assert "card" in payload

    @pytest.mark.asyncio
    async def test_send_p3_uses_text_message(self):
        """P3 使用纯文本消息"""
        adapter = FeishuAdapter(webhook_url="https://open.feishu.cn/test")
        event = make_event()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": 0}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await adapter.send(event, NotificationPriority.P3)

            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert payload["msg_type"] == "text"


# ─────────────────────────────────────────────
# TelegramAdapter 测试
# ─────────────────────────────────────────────


class TestTelegramAdapter:
    """Telegram 适配器测试"""

    def test_disabled_without_config(self):
        """无配置时禁用"""
        with patch.dict("os.environ", {}, clear=True):
            adapter = TelegramAdapter(bot_token=None, chat_id=None)
            assert adapter.enabled is False

    def test_enabled_with_config(self):
        """有配置时启用"""
        adapter = TelegramAdapter(bot_token="test-token", chat_id="12345")
        assert adapter.enabled is True

    @pytest.mark.asyncio
    async def test_send_when_disabled_returns_false(self):
        """禁用时返回 False"""
        with patch.dict("os.environ", {}, clear=True):
            adapter = TelegramAdapter()
            event = make_event()
            result = await adapter.send(event, NotificationPriority.P1)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """成功发送"""
        adapter = TelegramAdapter(bot_token="test-token", chat_id="12345")
        event = make_event()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await adapter.send(event, NotificationPriority.P1)
            assert result is True

    @pytest.mark.asyncio
    async def test_p3_disables_notification(self):
        """P3 静默推送"""
        adapter = TelegramAdapter(bot_token="test-token", chat_id="12345")
        event = make_event()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await adapter.send(event, NotificationPriority.P3)

            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert payload["disable_notification"] is True

    def test_format_message_includes_priority(self):
        """消息格式包含优先级"""
        event = make_event(message="Test message")
        text = TelegramAdapter._format_message(event, NotificationPriority.P0)
        assert "P0" in text
        assert "🔴" in text
        assert "Test message" in text


# ─────────────────────────────────────────────
# RetryQueue 测试
# ─────────────────────────────────────────────


class TestRetryQueue:
    """重试队列测试"""

    @pytest.mark.asyncio
    async def test_p3_no_retry_goes_to_dlq(self):
        """P3 不重试，直接进入 DLQ"""
        queue = RetryQueue()
        adapter = MockAdapter(AlertChannel.FEISHU, should_succeed=False)
        event = make_event()

        result = await queue.schedule_retry(
            adapter, event, NotificationPriority.P3, attempt=1, error="failed"
        )
        assert result is False  # 已达上限

    @pytest.mark.asyncio
    async def test_p1_schedules_retry(self):
        """P1 安排重试"""
        queue = RetryQueue()
        adapter = MockAdapter(AlertChannel.FEISHU, should_succeed=False)
        event = make_event()

        result = await queue.schedule_retry(
            adapter, event, NotificationPriority.P1, attempt=1, error="failed"
        )
        assert result is True  # 已安排
        assert len(queue._pending_retries) == 1

        # 清理
        queue.cleanup()


# ─────────────────────────────────────────────
# NotificationPriority 测试
# ─────────────────────────────────────────────


class TestNotificationPriority:
    """NotificationPriority 枚举测试"""

    def test_values(self):
        assert NotificationPriority.P0.value == "p0"
        assert NotificationPriority.P1.value == "p1"
        assert NotificationPriority.P2.value == "p2"
        assert NotificationPriority.P3.value == "p3"

    def test_is_string_enum(self):
        assert isinstance(NotificationPriority.P0, str)


# ─────────────────────────────────────────────
# AlertEvent 扩展字段测试
# ─────────────────────────────────────────────


class TestAlertEventExtension:
    """AlertEvent ALERT-03 扩展字段测试"""

    def test_default_source(self):
        """默认 source 为 user_rule"""
        event = AlertEvent(event_id="test")
        assert event.source == "user_rule"

    def test_default_priority_none(self):
        """默认 priority 为 None"""
        event = AlertEvent(event_id="test")
        assert event.priority is None

    def test_ui_hint_default_empty(self):
        """默认 ui_hint 为空 dict"""
        event = AlertEvent(event_id="test")
        assert event.ui_hint == {}

    def test_explicit_source(self):
        """显式设置 source"""
        event = AlertEvent(event_id="test", source="kill_switch")
        assert event.source == "kill_switch"

    def test_explicit_priority(self):
        """显式设置 priority"""
        event = AlertEvent(event_id="test", priority=NotificationPriority.P0)
        assert event.priority == NotificationPriority.P0
