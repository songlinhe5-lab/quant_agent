from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool(scopes=["trade"])  # 期权波动率分析
class OptionVolatilityTool(BaseTool):
    """
    F3：期权波动率（单合约，需期权 OCC 代码）。

    获取指定期权合约的隐含波动率(IV)、历史波动率(HV)、期权 Greeks
    （Delta/Gamma/Theta/Vega/Rho）与理论/市场价差，用于波动率曲面分析与
    期现套利机会研判。入参必须为期权合约代码（OCC 格式，如 US.AAPL260320C200000），
    非正股代码。
    """

    name = "get_option_volatility"
    description = (
        "获取期权合约波动率：输入期权 OCC 合约代码（非正股），"
        "返回隐含波动率(IV)、历史波动率(HV)、期权 Greeks(Delta/Gamma/Theta/Vega/Rho) "
        "与买卖盘理论价差。用于波动率曲面分析与期现套利机会研判。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "期权合约代码（OCC 格式，如 US.AAPL260320C200000），非正股代码。",
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
        url = f"{backend_url}/market/option-volatility"
        params = {"ticker": ticker}
        if prefer_sources:
            params["prefer_sources"] = prefer_sources
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, params=params)
