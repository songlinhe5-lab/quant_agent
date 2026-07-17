import os
from typing import Any, Dict

import httpx

from hermes_agent.tool_registry import register_tool

from .base import BaseTool


@register_tool
class NotificationTool(BaseTool):
    """
    负责向用户的 Telegram、飞书或微信发送重要通知。
    """
    name = "send_notification"
    description = "通过 Telegram、飞书或微信向人类发送重要的报警信息或交易结果通知。"
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "要发送的通知文本内容"
            }
        },
        "required": ["message"]
    }

    async def run(self, message: str = "") -> Dict[str, Any]:
        if not message:
            return {"status": "error", "message": "通知内容不能为空。"}

        success_channels = []
        errors = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Telegram
            tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
            tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if tg_token and tg_chat_id:
                try:
                    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                    payload = {"chat_id": tg_chat_id, "text": message}
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    success_channels.append("Telegram")
                except Exception as e:
                    errors.append(f"Telegram失败: {repr(e)}")

            # 2. 飞书 (Feishu Webhook)
            feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL")
            if feishu_webhook:
                try:
                    payload = {"msg_type": "text", "content": {"text": message}}
                    resp = await client.post(feishu_webhook, json=payload)
                    resp.raise_for_status()
                    success_channels.append("Feishu")
                except Exception as e:
                    errors.append(f"Feishu失败: {repr(e)}")

            # 3. 微信 (Server酱)
            serverchan_key = os.getenv("SERVERCHAN_SENDKEY")
            if serverchan_key:
                try:
                    url = f"https://sctapi.ftqq.com/{serverchan_key}.send"
                    # Server酱使用 form-urlencoded
                    payload = {"title": "🤖 Quant Agent 交易通知", "desp": message}
                    resp = await client.post(url, data=payload)
                    resp.raise_for_status()
                    success_channels.append("WeChat")
                except Exception as e:
                    errors.append(f"WeChat失败: {repr(e)}")

        if not success_channels and not errors:
            return {"status": "warning", "message": "未配置任何通知渠道环境变量 (Telegram/Feishu/ServerChan)。请在 .env 中配置。"}

        return {
            "status": "success" if success_channels else "error",
            "message": f"成功发送至: {','.join(success_channels)}。" + (f" 失败信息: {'; '.join(errors)}" if errors else "")
        }
