from typing import Type

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
        # 💡 提前拦截港股，引导使用 web_search
        if ticker.startswith("HK."):
            return (
                f"⚠️ 港股内幕交易数据暂不支持直接查询。\n\n"
                f"💡 建议操作：使用 web_search 搜索 '{ticker} insider transactions HKEX 披露易' 获取相关信息。\n"
                f"或访问 HKEX 披露易网站: https://www.hkexnews.hk 查询该股票的高管交易记录。"
            )
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
