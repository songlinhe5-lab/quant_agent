import asyncio
from typing import Type

import httpx
from pydantic import BaseModel, Field

from backend.services.finnhub_service import finnhub_service
from hermes_agent.tool_registry import register_tool


class InsiderTransactionsInput(BaseModel):
    ticker: str = Field(..., description="股票代码，仅支持美股，例如 US.AAPL, US.TSLA。港股暂不支持，请使用 web_search 搜索 'HK.00700 insider transactions HKEX' 获取信息。")
    limit: int = Field(default=20, description="返回的交易记录条数，默认 20")


@register_tool
class InsiderTransactionsTool:
    """
    查询高管内幕交易的 Agent Tool。
    （请根据您的 hermes_agent/tool_registry.py 的具体规范调整继承的 BaseTool 类）
    """

    name = "get_insider_transactions"
    description = "获取目标公司的近期高管内幕交易记录 (Insider Transactions)。用于追踪 CEO/CFO 等核心高管在公开市场是净买入还是抛售自家股票，是极强的基本面领先信号 (Smart Money)。"
    args_schema: Type[BaseModel] = InsiderTransactionsInput

    @property
    def parameters(self):
        return self.args_schema.model_json_schema()

    async def run(self, ticker: str, limit: int = 20) -> str:
        # 💡 港股并行查询：web_search + HKEX 披露易
        if ticker.startswith("HK."):
            stock_code = ticker[3:]  # 提取股票代码，如 00772
            return await self._query_hk_insider_parallel(ticker, stock_code)

        try:
            res = await finnhub_service.get_insider_transactions(ticker=ticker, limit=limit)
            if res.get("status") == "success":
                data = res.get("data", [])
                if not data:
                    return f"未查询到 {ticker} 近期的高管内幕交易记录。"

                # 格式化输出为紧凑的字符串，节省大模型 Token 上下文
                output = []
                for item in data:
                    action_icon = "🟢" if item["action"] == "BUY" else "🔴"
                    output.append(
                        f"- {item['date']} | {item['name'][:15]:<15} | {action_icon}{item['action']} {item['change']:+,} 股 @ ${item['transaction_price']}"
                    )

                return f"【{ticker} 近期高管内幕交易记录】\n" + "\n".join(output)
            else:
                return f"获取失败: {res.get('message')}"
        except Exception as e:
            return f"执行工具异常: {str(e)}"

    async def _query_hk_insider_parallel(self, ticker: str, stock_code: str) -> str:
        """港股内幕交易并行查询：web_search + HKEX 披露易"""
        # 💡 并行发起两个查询
        search_task = self._search_hk_insider(stock_code)
        hkex_task = self._fetch_hkex_disclosure(stock_code)

        results = await asyncio.gather(search_task, hkex_task, return_exceptions=True)
        search_result, hkex_result = results

        # 💡 组装结果
        output_parts = [f"【{ticker} 高管内幕交易查询】\n"]

        # 处理搜索结果
        if isinstance(search_result, dict) and search_result.get("status") == "success":
            output_parts.append("📰 相关新闻与公告：")
            for item in search_result.get("data", [])[:5]:
                output_parts.append(f"- {item.get('title', '无标题')}")
                if item.get("url"):
                    output_parts.append(f"  {item['url']}")
            output_parts.append("")
        elif isinstance(search_result, Exception):
            output_parts.append(f"⚠️ 搜索失败: {search_result}\n")

        # 处理 HKEX 结果
        if isinstance(hkex_result, dict) and hkex_result.get("status") == "success":
            output_parts.append("📋 HKEX 披露易数据：")
            output_parts.append(hkex_result.get("content", "")[:2000])
        elif isinstance(hkex_result, Exception):
            output_parts.append(f"⚠️ HKEX 查询失败: {hkex_result}\n")

        # 💡 如果两个都失败，返回引导信息
        if len(output_parts) == 1:
            return (
                f"⚠️ 港股内幕交易数据暂不支持直接查询。\n\n"
                f"💡 建议操作：\n"
                f"1. 使用 web_search 搜索 '{ticker} 高管交易 HKEX 披露易'\n"
                f"2. 访问 HKEX 披露易: https://www.hkexnews.hk\n"
                f"3. 搜索该股票的官方公告"
            )

        output_parts.append("\n🔗 官方查询入口: https://www.hkexnews.hk")
        return "\n".join(output_parts)

    async def _search_hk_insider(self, stock_code: str) -> dict:
        """通过后端搜索 API 查询港股内幕交易新闻"""
        import os

        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        query = f"{stock_code} 高管交易 内幕交易 披露易"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{backend_url}/api/v1/search/web",
                params={"query": query, "count": 5},
            )
            resp.raise_for_status()
            return resp.json()

    async def _fetch_hkex_disclosure(self, stock_code: str) -> dict:
        """尝试从 HKEX 披露易获取数据"""
        # 💡 HKEX 披露易搜索 URL
        url = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content = resp.text

            # 💡 简单提取页面内容（实际 HKEX 需要 JS 渲染，这里只返回提示）
            if len(content) < 500:
                return {
                    "status": "success",
                    "content": f"HKEX 披露易需要 JavaScript 渲染，请访问: {url} 搜索股票代码 {stock_code}",
                }
            return {"status": "success", "content": f"HKEX 披露易页面已加载，请手动访问搜索 {stock_code}"}
