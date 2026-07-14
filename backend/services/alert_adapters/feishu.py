"""
ALERT-03b · 飞书适配器

复用 OBS-02 已配置的 FEISHU_WEBHOOK_URL + FEISHU_SECRET，
P0/P1 用卡片消息（interactive），P2/P3 用纯文本。

设计文档：docs/18 §五.2
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import httpx

from backend.core.alert_models import AlertChannel, AlertEvent, NotificationPriority

logger = logging.getLogger(__name__)


class FeishuAdapter:
    """飞书 Webhook 适配器"""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> None:
        self._webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL")
        self._secret = secret or os.getenv("FEISHU_SECRET")

    @property
    def channel(self) -> AlertChannel:
        return AlertChannel.FEISHU

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)

    async def send(self, event: AlertEvent, priority: NotificationPriority) -> bool:
        """发送飞书消息"""
        if not self.enabled:
            return False

        # URL 协议头校验
        if not self._webhook_url.startswith(("http://", "https://")):
            logger.error(f"[Feishu] Invalid webhook URL: {self._webhook_url}")
            return False

        # 构造消息体
        if priority in (NotificationPriority.P0, NotificationPriority.P1):
            payload = self._build_card_message(event, priority)
        else:
            payload = self._build_text_message(event)

        # 签名
        if self._secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{self._secret}"
            hmac_code = hmac.new(
                string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256
            ).digest()
            sign = base64.b64encode(hmac_code).decode("utf-8")
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._webhook_url, json=payload, headers=headers, timeout=5.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        return True
                    # 飞书频率限制
                    if data.get("code") == 11232:
                        logger.warning("[Feishu] Rate limited")
                        return False  # 可重试
                    logger.error(f"[Feishu] Response error: {data}")
                    return False
                elif resp.status_code in (500, 502, 503, 504):
                    return False  # 可重试
                else:
                    logger.error(f"[Feishu] HTTP {resp.status_code}: {resp.text[:200]}")
                    return False
        except httpx.TimeoutException:
            logger.warning("[Feishu] Timeout")
            return False  # 可重试
        except Exception as e:
            logger.error(f"[Feishu] Send failed: {e}")
            return False

    @staticmethod
    def _build_card_message(event: AlertEvent, priority: NotificationPriority) -> dict:
        """P0/P1 卡片消息"""
        color = "red" if priority == NotificationPriority.P0 else "orange"
        title_prefix = "🔴 P0" if priority == NotificationPriority.P0 else "🟠 P1"

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{title_prefix} 告警 · {event.ticker or '系统'}",
                    },
                    "template": color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "plain_text",
                            "content": event.message[:500],
                        },
                    }
                ],
            },
        }

    @staticmethod
    def _build_text_message(event: AlertEvent) -> dict:
        """P2/P3 纯文本消息"""
        return {
            "msg_type": "text",
            "content": {"text": event.message[:500]},
        }
