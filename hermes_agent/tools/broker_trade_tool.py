import os
from typing import Dict, Any
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
class BrokerTradeTool(BaseTool):
    """
    大模型统一的 OMS (Order Management System) 交互探针。
    将查账户、买入、卖出、撤单收口在一个 Tool 里，模拟真实交易员的工作台终端。
    """
    name = "manage_broker_orders_and_account"
    description = "执行真实的股票/期权交易指令，以及查询交易账户资产与持仓。必须严格遵守风控。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["BUY", "SELL", "CANCEL", "STATUS", "ACCOUNT"],
                "description": "操作类型：BUY(买入), SELL(卖出), CANCEL(撤单), STATUS(查单), ACCOUNT(查账户资产与持仓)"
            },
            "ticker": {"type": "string", "description": "(BUY/SELL必填) 股票代码"},
            "qty": {"type": "integer", "description": "(BUY/SELL必填) 交易数量"},
            "price": {"type": "number", "description": "(BUY/SELL可选) 限价，不填即为市价单"},
            "order_id": {"type": "string", "description": "(CANCEL/STATUS必填) 订单号"},
            "market": {"type": "string", "description": "(ACCOUNT可选) 账户市场如 HK, US，默认 HK", "default": "HK"}
        },
        "required": ["action"]
    }

    async def run(self, action: str, ticker: str = "", qty: Any = 0, price: Any = 0.0, order_id: str = "", market: str = "HK") -> Dict[str, Any]:
        action = action.upper()
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        
        if action in ["BUY", "SELL"] and (not ticker or not qty):
            return {"status": "error", "message": f"{action} 操作必须提供 ticker 和 qty"}
        if action in ["CANCEL", "STATUS"] and not order_id:
            return {"status": "error", "message": f"{action} 操作必须提供 order_id"}
            
        try:
            async with SecureAsyncClient(timeout=15.0) as client:
                if action == "ACCOUNT":
                    resp = await client.get(f"{backend_url}/trade/account", params={"market": market})
                else:
                    payload = {"action": action, "ticker": ticker, "qty": int(qty), "price": float(price), "order_id": order_id}
                    resp = await client.post(f"{backend_url}/trade/order", json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            return {"status": "error", "message": f"请求后端接口失败: {str(e)}"}