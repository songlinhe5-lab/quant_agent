from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class HeatMapTool(BaseTool):
    """
    G6：板块热力图（市场级，需 market 参数）。

    获取指定市场的板块/个股热力图数据，并派生宽度统计（涨跌家数、涨跌比、
    市场情绪 risk_on/risk_off/mixed）与领涨/领跌榜，供前端 ECharts treemap 渲染。
    """

    name = "get_heat_map"
    description = (
        "获取板块热力图：指定市场(HK/US/SG)的板块/个股涨跌幅分布，"
        "并派生市场宽度统计（涨跌家数、涨跌比、risk_on/risk_off 情绪）与领涨/领跌榜。"
        "用于板块轮动与系统性风险扫描。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "description": "市场代码，默认 HK（港股），支持 US/SG。",
            },
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": [],
    }

    async def run(self, market: str = "HK", prefer_sources: str | None = None) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market/heat-map/{market}"
        params = {}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
