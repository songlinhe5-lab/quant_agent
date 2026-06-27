import os
from typing import Dict, Any
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
class BrokerMarketTool(BaseTool):
    """
    大模型统一的市场数据感知探针。
    将原有的 4 个碎碎念的查询工具统一合并，通过 action 参数路由。
    """
    name = "get_broker_market_data"
    description = "获取券商级别的市场行情与深度数据。支持获取实时报价、历史K线、期权链、资金流向等。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string", 
                "enum": ["QUOTE", "HISTORY", "OPTION_CHAIN", "FUND_FLOW"], 
                "description": "必须指定要获取的数据类型。QUOTE(实时快照), HISTORY(历史K线), OPTION_CHAIN(期权链), FUND_FLOW(主力资金流与席位)"
            },
            "ticker": {
                "type": "string", 
                "description": "股票或期权代码, 例如 AAPL, 0700.HK"
            },
            "ktype": {"type": "string", "description": "(仅HISTORY可用) K线类型，如 K_DAY, K_1M", "default": "K_DAY"},
            "num": {"type": "integer", "description": "(仅HISTORY可用) 获取的K线数量", "default": 60},
            "expiration_date": {"type": "string", "description": "(仅OPTION_CHAIN可用) 期权到期日 YYYY-MM-DD"}
        },
        "required": ["action", "ticker"]
    }

    async def run(self, action: str, ticker: str, ktype: str = "K_DAY", num: int = 60, expiration_date: str = "") -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        action = action.upper()
        # 强制格式化 ticker
        ticker = self.normalize_ticker(ticker)
        
        try:
            async with SecureAsyncClient(timeout=15.0) as client:
                if action == "QUOTE":
                    resp = await client.get(f"{backend_url}/market/quote", params={"ticker": ticker})
                elif action == "HISTORY":
                    resp = await client.get(f"{backend_url}/market/history", params={"ticker": ticker, "ktype": ktype, "num": num})
                elif action == "OPTION_CHAIN":
                    resp = await client.get(f"{backend_url}/market/option-chain", params={"ticker": ticker, "expiration_date": expiration_date})
                elif action == "FUND_FLOW":
                    resp = await client.get(f"{backend_url}/market/fund-flow", params={"ticker": ticker})
                else:
                    return {"status": "error", "message": f"不支持的操作: {action}"}
                
                if resp.status_code != 200:
                    err_msg = resp.text
                    try:
                        err_msg = resp.json().get("detail", resp.text)
                    except:
                        pass
                    return {"status": "error", "message": f"后端网关报错 (HTTP {resp.status_code}): {err_msg}"}
                    
                return resp.json()
        except Exception as e:
            return {"status": "error", "message": f"请求后端接口失败: {str(e)}"}