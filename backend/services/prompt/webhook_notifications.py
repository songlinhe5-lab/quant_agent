"""
Prompt Governance Webhook Notification System

发送新版本创建、低质量反馈警告、周报复告等通知到 Slack/飞书/钉钉。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class WebhookConfig:
    """Webhook 配置"""

    # Slack configuration
    slack_webhook_url: str = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL", ""))
    slack_channel: str = "#prompt-governance"

    # Feishu/Lark configuration
    feishu_webhook_url: str = field(default_factory=lambda: os.getenv("FEISHU_WEBHOOK_URL", ""))

    # DingTalk configuration
    dingtalk_webhook_url: str = field(default_factory=lambda: os.getenv("DINGTALK_WEBHOOK_URL", ""))

    # Email configuration (optional)
    smtp_server: str = field(default_factory=lambda: os.getenv("SMTP_SERVER", ""))
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    alert_email: str = field(default_factory=lambda: os.getenv("ALERT_EMAIL", ""))

    # Quality thresholds for alerts
    quality_warning_threshold: float = 0.6
    quality_critical_threshold: float = 0.5
    feedback_up_ratio_warning: float = 0.5

    # Weekly report schedule
    weekly_report_day: int = 1  # Monday (1-7)
    weekly_report_hour: int = 9  # 9 AM UTC


class BaseWebhookSender:
    """Base class for webhook senders"""

    def __init__(self, config: WebhookConfig):
        self.config = config

    def send(self, message: Dict[str, Any]) -> bool:
        """Send webhook notification"""
        raise NotImplementedError

    def validate_config(self) -> bool:
        """Check if webhook is configured"""
        raise NotImplementedError


class SlackWebhookSender(BaseWebhookSender):
    """Slack webhook sender"""

    def validate_config(self) -> bool:
        return bool(self.config.slack_webhook_url)

    def _build_slack_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Build Slack Blocks API message"""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": message.get("title", "🔔 Prompt Governance Alert"),
                },
            },
            {"type": "divider"},
        ]

        # Add fields based on message type
        if message.get("type") == "new_version":
            blocks.extend(
                [
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Prompt*:\n{message['prompt_name']}"},
                            {"type": "mrkdwn", "text": f"*Version*:\n{message['version']}"},
                            {"type": "mrkdwn", "text": f"*Quality Score*:\n{message['quality_score']:.2f}"},
                            {"type": "mrkdwn", "text": f"*Author*:\n{message.get('author', 'N/A')}"},
                        ],
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"⏰ {datetime.fromtimestamp(message['timestamp']).isoformat()}"}
                        ],
                    },
                ]
            )

        elif message.get("type") == "low_quality_alert":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⚠️ *Quality Alert*: {message['prompt_name']} v{message['version']} scored {message['quality_score']:.2f} (threshold: {self.config.quality_warning_threshold})",
                    },
                }
            )

        elif message.get("type") == "feedback_warning":
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📉 *Feedback Alert*: {message['prompt_name']} up_ratio={message['up_ratio']:.2f} < threshold {self.config.feedback_up_ratio_warning}",
                    },
                }
            )

        elif message.get("type") == "weekly_report":
            blocks.extend(
                [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Weekly Report*: {message['period_start']} → {message['period_end']}\n\n"
                            + "\n".join(f"{idx}. {item}" for idx, item in enumerate(message["summary_items"], 1)),
                        },
                    },
                ]
            )

        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Dashboard"},
                        "url": "http://localhost:5173/prompt-governance",
                        "style": "primary",
                    }
                    if message.get("type") != "weekly_report"
                    else None,
                ],
            }
        )

        return {"blocks": blocks}

    def send(self, message: Dict[str, Any]) -> bool:
        if not self.validate_config():
            print(f"⚠️ [SlackWebhook] Not configured, skipping")
            return False

        try:
            import httpx

            payload = self._build_slack_message(message)

            response = httpx.post(
                self.config.slack_webhook_url,
                json=payload,
                timeout=10.0,
            )

            if response.status_code == 200:
                print(f"✅ [SlackWebhook] Sent to {self.config.slack_channel}")
                return True
            else:
                print(f"❌ [SlackWebhook] Failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"❌ [SlackWebhook] Error: {e}")
            return False


class FeishuWebhookSender(BaseWebhookSender):
    """Feishu/Lark webhook sender"""

    def validate_config(self) -> bool:
        return bool(self.config.feishu_webhook_url)

    def _build_feishu_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Build Feishu card message"""
        if message.get("type") == "new_version":
            return {
                "msg_type": "card",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": "🎉 新版本已发布"},
                    },
                    "elements": [
                        {"tag": "markdown", "content": f"**Prompt**: {message['prompt_name']}"},
                        {"tag": "markdown", "content": f"**版本**: {message['version']}"},
                        {"tag": "markdown", "content": f"**质量评分**: {message['quality_score']:.2f}"},
                        {"tag": "markdown", "content": f"**作者**: {message.get('author', 'N/A')}"},
                    ],
                },
            }
        elif message.get("type") == "low_quality_alert":
            return {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": "⚠️ 质量警告"},
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"Prompt: `{message['prompt_name']}` 得分 {message['quality_score']:.2f} 低于阈值 {self.config.quality_warning_threshold}",
                        },
                    ],
                },
            }
        else:
            return {"msg_type": "text", "content": f"Prompt Governance: {message.get('title', 'Alert')}"}

    def send(self, message: Dict[str, Any]) -> bool:
        if not self.validate_config():
            return False

        try:
            import httpx

            payload = self._build_feishu_message(message)

            response = httpx.post(
                self.config.feishu_webhook_url,
                json=payload,
                timeout=10.0,
            )

            if response.json().get("StatusCode") == 0:
                print(f"✅ [FeishuWebhook] Sent successfully")
                return True
            else:
                print(f"❌ [FeishuWebhook] Failed: {response.json()}")
                return False

        except Exception as e:
            print(f"❌ [FeishuWebhook] Error: {e}")
            return False


class WebhookManager:
    """统一 Webhook 管理器"""

    def __init__(self):
        self.config = WebhookConfig()
        self.senders: Dict[str, BaseWebhookSender] = {}

        # Initialize senders
        if self.config.slack_webhook_url:
            self.senders["slack"] = SlackWebhookSender(self.config)

        if self.config.feishu_webhook_url:
            self.senders["feishu"] = FeishuWebhookSender(self.config)

    def send_notification(self, message: Dict[str, Any], destinations: Optional[List[str]] = None):
        """发送通知到指定渠道"""
        destinations = destinations or list(self.senders.keys())

        successful = []
        failed = []

        for dest in destinations:
            sender = self.senders.get(dest)
            if sender and sender.send(message):
                successful.append(dest)
            else:
                failed.append(dest)

        print(f"📨 [WebhookManager] Sent to: {successful}, Failed: {failed}")

        return {
            "total": len(destinations),
            "successful": successful,
            "failed": failed,
        }

    async def notify_new_version(
        self,
        prompt_name: str,
        version: str,
        quality_score: float,
        author: Optional[str] = None,
    ):
        """新版本创建通知"""
        message = {
            "type": "new_version",
            "title": "🎉 New Version Created",
            "prompt_name": prompt_name,
            "version": version,
            "quality_score": quality_score,
            "author": author or "system",
            "timestamp": time.time(),
        }

        return self.send_notification(message)

    async def notify_low_quality(
        self,
        prompt_name: str,
        version: str,
        quality_score: float,
        threshold: float = None,
    ):
        """低质量预警通知"""
        threshold = threshold or self.config.quality_warning_threshold

        message = {
            "type": "low_quality_alert",
            "title": "⚠️ Low Quality Alert",
            "prompt_name": prompt_name,
            "version": version,
            "quality_score": quality_score,
            "threshold": threshold,
            "timestamp": time.time(),
        }

        return self.send_notification(message, destinations=["slack", "feishu"])

    async def notify_feedback_warning(
        self,
        prompt_name: str,
        version: str,
        up_ratio: float,
    ):
        """用户反馈警告通知"""
        message = {
            "type": "feedback_warning",
            "title": "📉 Feedback Warning",
            "prompt_name": prompt_name,
            "version": version,
            "up_ratio": up_ratio,
            "timestamp": time.time(),
        }

        return self.send_notification(message, destinations=["slack"])

    async def send_weekly_report(
        self,
        period_start: str,
        period_end: str,
        summary_items: List[str],
    ):
        """周报推送"""
        message = {
            "type": "weekly_report",
            "title": "📊 Weekly Prompt Governance Report",
            "period_start": period_start,
            "period_end": period_end,
            "summary_items": summary_items,
            "timestamp": time.time(),
        }

        return self.send_notification(message, destinations=["slack", "feishu"])


# Global singleton instance
_manager_instance: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    """获取全局 Webhook Manager 单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = WebhookManager()
    return _manager_instance


async def initialize_webhook_notifications():
    """初始化 Webhook 通知系统"""
    from backend.services.prompt.governance_service import get_prompt_governance_service

    service = get_prompt_governance_service()
    manager = get_webhook_manager()

    # Check if any webhooks are configured
    has_slack = bool(service.version_manager.templates)  # Has prompts to monitor

    if has_slack:
        print("✅ [WebhookNotifications] Service initialized")
    else:
        print("ℹ️ [WebhookNotifications] No prompts to monitor, notifications disabled")


# FastAPI endpoint for manual trigger (optional)
def create_webhook_trigger_endpoint(app=None):
    """创建手动触发 Webhook 的 API endpoint"""
    if app is None:
        from fastapi import FastAPI

        app = FastAPI()

    @app.post("/webhook/trigger/new-version")
    async def trigger_new_version_notification(
        prompt_name: str,
        version: str,
        quality_score: float = 0.8,
    ):
        """手动触发新版本通知（用于测试）"""
        manager = get_webhook_manager()
        result = await manager.notify_new_version(prompt_name, version, quality_score)

        return {"status": "sent", "result": result}

    return app
