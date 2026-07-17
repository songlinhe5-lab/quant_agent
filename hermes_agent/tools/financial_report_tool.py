import os
from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool
from .secure_client import SecureAsyncClient


@register_tool
class FinancialReportTool(BaseTool):
    """
    自动寻找并解析本地存放的财报文件。
    """
    name = "analyze_financial_report"
    description = "扫描并读取本地存放的财报或研报文件内容（支持 .txt, .md, .pdf）。用于大模型进行深度的财务与战略分析。"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码，用于匹配对应的财报文件，例如 AAPL"
            },
            "chunk_index": {
                "type": "integer",
                "description": "可选：由于财报较长，系统支持分块读取。指定要读取的内容块索引，默认为 0。"
            }
        },
        "required": ["ticker"]
    }

    async def run(self, ticker: str = "", chunk_index: int = 0) -> Dict[str, Any]:
        if not ticker:
            return {"status": "error", "message": "缺失股票代码参数。"}

        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/v1")
        url = f"{backend_url}/financial-report"
        try:
            async with SecureAsyncClient(timeout=60.0) as client:
                response = await client.get(url, params={"ticker": ticker, "chunk_index": chunk_index}, timeout=60.0)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"status": "error", "message": f"请求后端接口失败: {str(e)}"}
