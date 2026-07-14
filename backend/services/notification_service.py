"""
系统通知服务（ALERT-03 收敛）

ALERT-03 后，NotificationService 改为 AlertDispatcher 的薄包装。
所有系统级通知经 dispatcher 统一路由，禁止直连 Webhook。

向后兼容：保留 send_alert(message) 接口，内部转为 AlertEvent 派发。
"""

import logging
import time
import uuid

from backend.core.alert_models import AlertEvent, AlertSeverity, NotificationPriority

logger = logging.getLogger(__name__)


class NotificationService:
    """后端原生通知服务（ALERT-03 薄包装）

    所有系统级报警经 AlertDispatcher 统一路由。
    保留原有 send_alert(message) 接口向后兼容。
    """

    def __init__(self):
        self._dispatcher = None  # 延迟导入

    def _get_dispatcher(self):
        """延迟导入 AlertDispatcher（避免循环依赖）"""
        if self._dispatcher is None:
            from backend.services.alert_dispatcher import get_alert_dispatcher
            self._dispatcher = get_alert_dispatcher()
        return self._dispatcher

    async def send_alert(self, message: str, priority: NotificationPriority = NotificationPriority.P2, source: str = "system"):
        """发送系统通知（经 AlertDispatcher 统一路由）"""
        logger.info(f"🔔 [System Notification] {message}")

        dispatcher = self._get_dispatcher()

        # 构造 AlertEvent
        event = AlertEvent(
            event_id=str(uuid.uuid4()),
            message=message,
            severity=self._priority_to_severity(priority),
            source=source,
            priority=priority,
            triggered_at=time.time(),
        )

        try:
            await dispatcher.dispatch(event)
        except Exception as e:
            logger.error(f"发送系统通知失败: {e}")

    @staticmethod
    def _priority_to_severity(priority: NotificationPriority) -> AlertSeverity:
        """优先级 → 严重程度映射"""
        mapping = {
            NotificationPriority.P0: AlertSeverity.CRITICAL,
            NotificationPriority.P1: AlertSeverity.CRITICAL,
            NotificationPriority.P2: AlertSeverity.WARNING,
            NotificationPriority.P3: AlertSeverity.INFO,
        }
        return mapping.get(priority, AlertSeverity.INFO)


notification_service = NotificationService()
