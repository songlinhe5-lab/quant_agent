"""
ALERT-03b · Telegram 适配器

通过 Bot API sendMessage 推送告警。
P3 使用 disable_notification=True 静默推送。

设计文档：docs/18 §五.3
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from backend.core.alert_models import AlertChannel, AlertEvent, NotificationPriority

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramAdapter:
    """Telegram Bot 适配器"""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        self._bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    @property
    def channel(self) -> AlertChannel:
        return AlertChannel.TELEGRAM

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    async def send(self, event: AlertEvent, priority: NotificationPriority) -> bool:
        """发送 Telegram 消息"""
        if not self.enabled:
            return False

        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"

        # 构造消息文本
        text = self._format_message(event, priority)

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": priority == NotificationPriority.P3,  # P3 静默
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        return True
                    logger.error(f"[Telegram] API error: {data.get('description', 'unknown')}")
                    return False
                elif resp.status_code == 429:
                    logger.warning("[Telegram] Rate limited (429)")
                    return False  # 可重试
                elif resp.status_code in (500, 502, 503, 504):
                    return False  # 可重试
                else:
                    logger.error(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
                    return False
        except httpx.TimeoutException:
            logger.warning("[Telegram] Timeout")
            return False  # 可重试
        except Exception as e:
            logger.error(f"[Telegram] Send failed: {e}")
            return False

    @staticmethod
    def _format_message(event: AlertEvent, priority: NotificationPriority) -> str:
        """格式化 Telegram 消息（HTML）"""
        priority_emoji = {
            NotificationPriority.P0: "🔴",
            NotificationPriority.P1: "🟠",
            NotificationPriority.P2: "🟡",
            NotificationPriority.P3: "⚪",
        }
        emoji = priority_emoji.get(priority, "⚪")
        header = f"<b>{emoji} {priority.value.upper()}</b>"

        # 消息体（截断防止超长）
        body = event.message[:300]

        return f"{header}\n{body}"
