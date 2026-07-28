"""单测：services/alert/notification.NotificationService

覆盖：优先级 -> 严重度映射（P0~P3）、send_alert 事件构造与派发、
派发异常被安全吞掉不向上抛。
"""

from unittest.mock import AsyncMock

from backend.core.alert_models import AlertEvent, AlertSeverity, NotificationPriority
from backend.services.alert import notification as notification_mod
from backend.services.alert.notification import NotificationService, notification_service


def test_priority_to_severity_mapping():
    svc = NotificationService()
    assert svc._priority_to_severity(NotificationPriority.P0) == AlertSeverity.CRITICAL
    assert svc._priority_to_severity(NotificationPriority.P1) == AlertSeverity.CRITICAL
    assert svc._priority_to_severity(NotificationPriority.P2) == AlertSeverity.WARNING
    assert svc._priority_to_severity(NotificationPriority.P3) == AlertSeverity.INFO
    # 缺省降级
    assert svc._priority_to_severity(None) == AlertSeverity.INFO
    assert svc._priority_to_severity("P9") == AlertSeverity.INFO


async def test_send_alert_builds_and_dispatches_event():
    svc = NotificationService()
    fake_dispatcher = AsyncMock()
    svc._get_dispatcher = lambda: fake_dispatcher

    await svc.send_alert(message="系统告警", priority=NotificationPriority.P2, source="system")

    fake_dispatcher.dispatch.assert_awaited_once()
    event = fake_dispatcher.dispatch.await_args.args[0]
    assert isinstance(event, AlertEvent)
    assert event.message == "系统告警"
    assert event.severity == AlertSeverity.WARNING  # P2 -> WARNING
    assert event.source == "system"
    assert event.priority == NotificationPriority.P2


async def test_send_alert_p0_maps_critical():
    svc = NotificationService()
    fake_dispatcher = AsyncMock()
    svc._get_dispatcher = lambda: fake_dispatcher

    await svc.send_alert(message="致命错误", priority=NotificationPriority.P0, source="macro")

    event = fake_dispatcher.dispatch.await_args.args[0]
    assert event.severity == AlertSeverity.CRITICAL
    assert event.priority == NotificationPriority.P0


async def test_send_alert_swallows_dispatch_exception():
    svc = NotificationService()
    fake_dispatcher = AsyncMock()
    fake_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("broker down"))
    svc._get_dispatcher = lambda: fake_dispatcher

    # 不应向上抛出异常
    await svc.send_alert(message="x", priority=NotificationPriority.P3, source="system")

    fake_dispatcher.dispatch.assert_awaited_once()


async def test_singleton_instance_callable():
    # 模块级单例可被直接使用
    fake_dispatcher = AsyncMock()
    notification_service._get_dispatcher = lambda: fake_dispatcher
    await notification_service.send_alert(message="y", priority=NotificationPriority.P1, source="system")
    fake_dispatcher.dispatch.assert_awaited_once()
    # 还原，避免影响其它测试
    notification_mod.notification_service._get_dispatcher = NotificationService._get_dispatcher
