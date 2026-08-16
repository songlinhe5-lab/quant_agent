from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class StockBasicInfoTool(BaseTool):
    """全市场股票/ETF/指数基本信息（Futu STOCK_BASICINFO）。

    获取指定市场、指定证券类型的全量基础信息（代码/名称/上市日期/每手股数等），
    用于标的检索、代码映射与基础属性校验。
    """

    name = "get_stock_basicinfo"
    description = (
        "获取全市场基础信息：输入市场代码（HK/US/SG）与证券类型（STOCK/ETF/IDX/WARRANT），"
        "返回该市场该类型全量标的的基础信息（代码/名称/上市日期等）。"
        "用于标的检索与代码映射。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "description": "市场代码（HK/US/SG）。",
            },
            "sec_type": {
                "type": "string",
                "enum": ["STOCK", "ETF", "IDX", "WARRANT"],
                "description": "证券类型，默认 STOCK。",
            },
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": ["market"],
    }

    async def run(
        self,
        market: str,
        sec_type: str = "STOCK",
        prefer_sources: str | None = None,
    ) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market/stock-basicinfo"
        params: Dict[str, Any] = {"market": market, "sec_type": sec_type}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
