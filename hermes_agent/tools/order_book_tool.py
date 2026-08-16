from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class OrderBookTool(BaseTool):
    """实时 L2 盘口深度（Futu ORDER_BOOK）。

    获取标的实时买卖十档盘口，派生最优买卖价差(spread)与买卖盘量比(imbalance)，
    用于流动性研判与盘口博弈分析。需先经 Futu 订阅 Quote 推送。
    """

    name = "get_order_book"
    description = (
        "获取实时 L2 盘口深度：输入标的代码（如 HK.00700），"
        "返回买卖十档盘口、最优买卖价差(spread)与买卖盘量比(imbalance)。"
        "用于流动性研判与盘口博弈分析。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "标的代码（如 HK.00700 / US.AAPL）。",
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
        url = f"{backend_url}/market/order-book"
        params: Dict[str, Any] = {"ticker": ticker}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
