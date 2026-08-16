from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class MarketSnapshotTool(BaseTool):
    """批量实时快照（Futu SNAPSHOT，最多 400 只/批）。

    获取一组标的的实时快照（最新价/涨跌幅等），派生平均涨跌幅与涨跌家数，
    用于自选股墙、板块监控与批量异动扫描。
    """

    name = "get_market_snapshot"
    description = (
        "批量获取实时快照：输入逗号分隔的标的列表（如 HK.00700,US.AAPL），"
        "返回各标的实时快照，并派生平均涨跌幅、涨跌家数。最多 400 只/批。"
        "用于自选股监控与批量异动扫描。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "tickers": {
                "type": "string",
                "description": "逗号分隔的标的列表（如 HK.00700,US.AAPL,HK.09988）。",
            },
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": ["tickers"],
    }

    async def run(self, tickers: str, prefer_sources: str | None = None) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market/snapshot"
        params: Dict[str, Any] = {"tickers": tickers}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
