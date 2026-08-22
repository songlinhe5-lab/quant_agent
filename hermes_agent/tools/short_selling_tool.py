from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool(scopes=["fundamental", "quote"])  # 卖空拥挤度监控
class ShortSellingTool(BaseTool):
    """
    G2/F1：港股卖空拥挤度监控（Futu 真卖空源 + HKEX/SFC 监管交叉验证）。

    聚合 Futu 卖空榜（rank）/ 每日卖空量（daily）+ HKEX 市场级卖空占比，
    派生卖空成交占比中位数、拥挤度分位、挤空/崩塌告警信号。
    用于港股做空拥挤度研判与逼空机会挖掘。
    """

    name = "get_short_selling"
    description = (
        "获取港股卖空拥挤度：输入港股代码（如 HK.00700），"
        "返回卖空榜/每日卖空量经 HKEX 监管交叉验证后的卖空成交占比、"
        "拥挤度分位与挤空/崩塌告警信号。mode 可选 rank(卖空榜) / daily(每日卖空量)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "港股代码（如 HK.00700）。",
            },
            "mode": {
                "type": "string",
                "enum": ["rank", "daily"],
                "description": "卖空数据模式：rank=卖空榜(默认)，daily=每日卖空量(T-1)。",
            },
            "prefer_sources": {
                "type": "string",
                "description": "临时偏好数据源，逗号分隔，默认 futu。",
            },
        },
        "required": ["ticker"],
    }

    async def run(
        self,
        ticker: str,
        mode: str = "rank",
        prefer_sources: str | None = None,
    ) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market-fundamental/short-selling/{ticker}"
        params: Dict[str, Any] = {"mode": mode}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
