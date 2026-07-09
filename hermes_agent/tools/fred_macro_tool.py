import os
from typing import Dict, Any
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
# 工具类名必须与 __init__.py 中导入的一致 (FredMacroTool)
class FredMacroTool(BaseTool):
    """
    获取权威宏观经济数据。
    """
    name = "get_fred_macro_data"
    description = "从圣路易斯联储(FRED)获取指定的宏观经济数据时间序列。例如十年期美债收益率(DGS10)、失业率(UNRATE)、CPI等。用于深度宏观经济分析。"
    parameters = {
        "type": "object",
        "properties": {
            "series_id": {
                "type": "string",
                "description": "FRED的经济序列ID, 例如 'DGS10' (10年期美债收益率) 或 'UNRATE' (失业率)。"
            },
            "limit": {
                "type": "integer",
                "description": "返回最近的数据点数量，默认为100。"
            }
        },
        "required": ["series_id"]
    }

    async def run(self, series_id: str, limit: int = 100) -> Dict[str, Any]:
        if not series_id:
            return {"status": "error", "message": "缺失宏观序列ID (series_id) 参数。"}
            
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        url = f"{backend_url}/macro/series"
        # RL-14: 限流感知智能重试
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(
                client, "GET", url, params={"series_id": series_id, "limit": limit}
            )