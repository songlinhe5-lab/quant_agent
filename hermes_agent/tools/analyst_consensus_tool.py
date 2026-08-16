from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class AnalystVsFundamentalTool(BaseTool):
    """
    G7：卖方分析师共识 vs 实际基本面（交叉验证面板）。

    并发聚合 Futu 分析师共识（卖方观点）与真基本面三源合并，
    派生分析师目标价上行空间并给出交叉验证结论。
    注意：分析师共识是卖方观点而非事实，返回显式标注 consensus_is_third_party_expectation。
    """

    name = "get_analyst_vs_fundamental"
    description = (
        "获取卖方分析师共识 vs 实际基本面交叉验证：分析师目标价上行空间、"
        "交叉验证结论（卖方乐观/中性/看空）。用于识别卖方过度乐观或预期差机会。"
        "返回中明确标注共识为第三方观点（is_third_party_expectation），不应当作事实结论。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "标的代码（如 AAPL、00700.HK）。",
            },
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": ["ticker"],
    }

    async def run(self, ticker: str, prefer_sources: str | None = None) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market/analyst-vs-fundamental/{ticker}"
        params = {}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
