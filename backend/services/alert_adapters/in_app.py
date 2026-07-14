"""
ALERT-03b · InApp 适配器

通过 Redis PubSub 推送到专用频道 quant:alerts:push，
前端 WebSocket 端点订阅此频道实现实时告警。

设计文档：docs/18 §五.1
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from backend.core.alert_models import AlertChannel, AlertEvent, NotificationPriority

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# 专用推送频道（与 macro_alerts 分离）
ALERT_PUSH_CHANNEL = "quant:alerts:push"


class InAppAdapter:
    """应用内推送适配器（Redis PubSub → /alert/ws）"""

    def __init__(self, redis_client: Optional["aioredis.Redis"] = None) -> None:
        self._redis = redis_client

    @property
    def channel(self) -> AlertChannel:
        return AlertChannel.IN_APP

    @property
    def enabled(self) -> bool:
        return True  # in_app 始终可用

    async def send(self, event: AlertEvent, priority: NotificationPriority) -> bool:
        """通过 Redis PubSub 推送告警"""
        if not self._redis:
            logger.debug("[InApp] No Redis client, skip")
            return True  # 无 Redis 不算失败

        payload = {
            "type": "alert",
            "event_id": event.event_id,
            "priority": priority.value,
            "severity": event.severity.value,
            "message": event.message,
            "ticker": event.ticker,
            "triggered_at": event.triggered_at,
            "ui_hint": event.ui_hint or self._default_ui_hint(priority),
            "rule_id": event.rule_id,
            "source": event.source,
            "ack_required": priority == NotificationPriority.P0,
        }

        try:
            await self._redis.publish(ALERT_PUSH_CHANNEL, json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"[InApp] Redis publish failed: {e}")
            return False

    @staticmethod
    def _default_ui_hint(priority: NotificationPriority) -> dict:
        """根据优先级生成默认 UI 提示"""
        hints = {
            NotificationPriority.P0: {"mode": "fullscreen", "flash": True, "sound": True},
            NotificationPriority.P1: {"mode": "toast", "duration": 8000},
            NotificationPriority.P2: {"mode": "statusbar"},
            NotificationPriority.P3: {"mode": "badge"},
        }
        return hints.get(priority, {"mode": "badge"})
