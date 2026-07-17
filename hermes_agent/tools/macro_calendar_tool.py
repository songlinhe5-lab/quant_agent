import os
from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool
from .secure_client import SecureAsyncClient


@register_tool
class MacroCalendarTool(BaseTool):
    """
    单一职责 (SRP)：获取并提纯全球核心经济体的宏观日历数据。
    架构约束：内部进行高优过滤，防止原始冗余数据撑爆 LLM Context Window。
    """
    name = "get_macro_calendar"
    description = "获取未来 N 天内，美(US)、日(JP)、中(CN)、欧(EU)的高影响(High Impact)宏观经济事件（如利率决议、非农、CPI等）。"
    parameters = {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "获取未来几天的数据，默认值为 7"
            }
        }
    }

    async def run(self, days_ahead: int = 7) -> Dict[str, Any]:
        try:
            days_ahead = int(days_ahead)
            days_ahead = max(1, min(days_ahead, 30))
        except (ValueError, TypeError):
            days_ahead = 7

        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/v1")
        url = f"{backend_url}/macro/calendar"
        # RL-14: 限流感知智能重试
        async with SecureAsyncClient(timeout=15.0) as client:
            return await self.rate_limit_aware_request(
                client, "GET", url, params={"days_ahead": days_ahead}, timeout=15.0
            )
