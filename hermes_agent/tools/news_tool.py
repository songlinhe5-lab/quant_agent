from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class GetCompanyNewsTool(BaseTool):
    name = "get_company_news"
    description = "获取指定股票（如 AAPL, 0700.HK）的近期相关公司新闻与舆情公告。"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "股票代码，如 AAPL, HK.00700"},
            "limit": {"type": "integer", "description": "返回的新闻数量限制，最大 20，默认 10"},
        },
        "required": ["ticker"],
    }

    async def run(self, ticker: str, limit: int = 10) -> Dict[str, Any]:
        if not ticker:
            return {"status": "error", "message": "股票代码 ticker 不能为空"}

        backend_url = get_backend_api_url()
        try:
            async with SecureAsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{backend_url}/market/news", params={"ticker": ticker, "limit": limit})

                # 💡 精准捕获非 200 状态，提取 FastApi 后端返回的具体错误详情
                if resp.status_code != 200:
                    err_msg = resp.text
                    try:
                        err_msg = resp.json().get("detail", resp.text)
                    except:
                        pass
                    return {"status": "error", "message": f"网关接口返回错误 (HTTP {resp.status_code}): {err_msg}"}

                return resp.json()
        except Exception as e:
            return {"status": "error", "message": f"请求后端网关异常: {str(e)}"}
