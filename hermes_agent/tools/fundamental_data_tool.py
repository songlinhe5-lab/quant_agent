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
        # G1 · 优先走三源合并端点（戳破单源假基本面）；旧端点作为兜底（兼容未部署节点）
        url = f"{backend_url}/market/fundamental/merged/{ticker}"
        async with SecureAsyncClient(timeout=30.0) as client:
            resp = await self.rate_limit_aware_request(client, "GET", url, timeout=30.0)
            # merged 端点未部署（404）或全源失败时，回退旧单源端点
            if isinstance(resp, dict) and resp.get("status") in ("error", "warning", None):
                fallback_url = f"{backend_url}/market/fundamental/{ticker}"
                return await self.rate_limit_aware_request(client, "GET", fallback_url, timeout=30.0)
            return resp
