from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class FedWatchTool(BaseTool):
    """
    G5：FedWatch 面板（市场级，无 code 参数）。

    从 Futu FedWatch 获取 FOMC 各次会议的目标利率隐含概率，
    并派生下一会议隐含利率与政策斜率（hawkish/dovish/flat），
    用于 Tier1 流动性前瞻推演。
    """

    name = "get_fed_watch"
    description = (
        "获取美联储 FedWatch 面板：FOMC 各次会议的目标利率隐含概率，"
        "并派生下一会议隐含利率与政策斜率(hawkish/dovish/flat)。"
        "用于全球流动性与利率前瞻推演（Tier1 宏观）。无标的参数，为市场级数据。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": [],
    }

    async def run(self, prefer_sources: str | None = None) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/macro/fed-watch"
        params = {}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
