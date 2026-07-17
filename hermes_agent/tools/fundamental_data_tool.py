from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class FundamentalDataTool(BaseTool):
    """
    获取标的的核心基本面与筹码数据，用于宏观风控与估值泡沫预警。
    """

    name = "get_fundamental_data"
    description = "获取指定股票的核心基本面、估值指标与筹码博弈数据（如 P/E, PEG, ROE, Short Ratio 等）。用于判断估值泡沫或轧空风险。"
    parameters = {
        "type": "object",
        "properties": {"ticker": {"type": "string", "description": "股票标准代码，例如 AAPL, 0700.HK"}},
        "required": ["ticker"],
    }

    async def run(self, ticker: str = "") -> Dict[str, Any]:
        if not ticker:
            return {"status": "error", "message": "缺少必要的股票代码(ticker)参数。"}

        backend_url = get_backend_api_url()
        # 强制格式化 ticker
        ticker = self.normalize_ticker(ticker)
        url = f"{backend_url}/market/fundamental/{ticker}"
        # RL-14: 限流感知智能重试
        async with SecureAsyncClient(timeout=30.0) as client:
            return await self.rate_limit_aware_request(client, "GET", url, timeout=30.0)
