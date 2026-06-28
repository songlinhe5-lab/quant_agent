import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse

import httpx

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

class NotificationService:
    """后端原生通知服务，负责将系统级报警广播给前端或外部渠道 (支持 DingTalk/WeCom/Feishu/Telegram 等)"""  # noqa: E501

    async def send_alert(self, message: str):
        logger.info(f"🔔 [System Notification] {message}")
        try:
            # 1. 推送到现有的 WebSocket Redis PubSub 通道 (前端会在全局监听到)
            payload = json.dumps({"type": "notification", "message": message, "channel": "system_alerts"})  # noqa: E501
            await redis_client.publish("macro_alerts", payload)
        except Exception as e:
            logger.error(f"发送系统通知失败: {e}")

        # 2. 推送到企业钉钉机器人 (如果配置了环境变量)
        await self._send_to_dingtalk(message)

        # 3. 推送到企业微信机器人 (如果配置了环境变量)
        await self._send_to_wecom(message)

        # 4. 推送到飞书机器人 (如果配置了环境变量)
        await self._send_to_feishu(message)

    async def _send_to_dingtalk(self, message: str):
        webhook_url = os.getenv("DINGTALK_WEBHOOK_URL")
        if not webhook_url:
            return

        secret = os.getenv("DINGTALK_SECRET")
        if secret:
            # 钉钉签名计算规则
            timestamp = str(round(time.time() * 1000))
            secret_enc = secret.encode('utf-8')
            string_to_sign = f'{timestamp}\n{secret}'
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()  # noqa: E501
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            webhook_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"

        headers = {'Content-Type': 'application/json'}
        payload = {"msgtype": "text", "text": {"content": message}}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json=payload, headers=headers, timeout=5.0)  # noqa: E501
                if resp.status_code != 200 or resp.json().get('errcode', 0) != 0:
                    logger.error(f"钉钉推送失败，返回信息: {resp.text}")
        except Exception as e:
            logger.error(f"钉钉推送接口异常: {e}")

    async def _send_to_wecom(self, message: str):
        webhook_url = os.getenv("WECOM_WEBHOOK_URL")
        if not webhook_url:
            return

        headers = {'Content-Type': 'application/json'}
        payload = {"msgtype": "text", "text": {"content": message}}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json=payload, headers=headers, timeout=5.0)  # noqa: E501
                if resp.status_code != 200 or resp.json().get('errcode', 0) != 0:
                    logger.error(f"企业微信推送失败，返回信息: {resp.text}")
        except Exception as e:
            logger.error(f"企业微信推送接口异常: {e}")

    async def _send_to_feishu(self, message: str):
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
        if not webhook_url:
            return

        # 💡 健壮性修复：校验 webhook_url 合法性，防止 httpx 因缺失协议头而崩溃
        if not webhook_url.startswith(("http://", "https://")):
            logger.error(f"飞书推送失败: 无效的 Webhook URL (必须以 http:// 或 https:// 开头): {webhook_url}")  # noqa: E501
            return

        payload = {
            "msg_type": "text",
            "content": {"text": message}
        }

        secret = os.getenv("FEISHU_SECRET")
        if secret:
            # 飞书签名计算规则 (注意：飞书使用秒级时间戳，且算法与钉钉不同)
            timestamp = str(int(time.time()))
            string_to_sign = f'{timestamp}\n{secret}'
            hmac_code = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()  # noqa: E501
            sign = base64.b64encode(hmac_code).decode('utf-8')

            payload["timestamp"] = timestamp
            payload["sign"] = sign

        headers = {'Content-Type': 'application/json'}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json=payload, headers=headers, timeout=5.0)  # noqa: E501
                if resp.status_code != 200 or resp.json().get('code', 0) != 0:
                    logger.error(f"飞书推送失败，返回信息: {resp.text}")
        except Exception as e:
            logger.error(f"飞书推送接口异常: {e}")

notification_service = NotificationService()
