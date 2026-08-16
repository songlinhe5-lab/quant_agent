from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class OptionStrategyLabTool(BaseTool):
    """
    G4：期权损益实验室（依赖 F3 OPTION_STRATEGY）。

    拉取真实期权策略组合，构建纯代数到期损益曲线，并派生盈亏平衡点、
    最大盈亏与真实 Greeks 敞口。注意：损益来自真实组合腿推演，非 Black-Scholes 近似。
    """

    name = "get_option_strategy_lab"
    description = (
        "期权损益实验室：给定正股/ETF/指数 + 策略类型（如 STRANGLE），"
        "返回真实组合腿的到期损益曲线、盈亏平衡点、最大盈亏与 Greeks 敞口。"
        "用于期权策略损益情景推演。入参必须是正股/ETF/指数代码，非期权合约代码。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "正股/ETF/指数代码（如 US.AAPL），非期权 code。",
            },
            "strategy_type": {
                "type": "string",
                "description": "策略类型，默认 STRANGLE（跨式）。",
            },
            "spread": {
                "type": "integer",
                "description": "价差档位，默认 5。",
            },
            "underlying_price": {
                "type": "number",
                "description": "情景网格中心价（可选，默认取行权价中值）。",
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
        strategy_type: str = "STRANGLE",
        spread: int = 5,
        underlying_price: float | None = None,
        prefer_sources: str | None = None,
    ) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/market/option-strategy-lab"
        params = {"ticker": ticker, "strategy_type": strategy_type, "spread": spread}
        if underlying_price is not None:
            params["underlying_price"] = underlying_price
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
