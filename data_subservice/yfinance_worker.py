"""YFinance worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.logger import logger
from data_subservice._internal.yfinance import yfinance_service


async def handle_yfinance(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 yfinance 数据源请求。"""
    try:
        if action == "QUOTE":
            return await yfinance_service.get_quote(params.get("symbol"))
        elif action == "HISTORY":
            return await yfinance_service.get_history(
                params.get("symbol"),
                period=params.get("period"),
                start=params.get("start"),
                end=params.get("end"),
                interval=params.get("interval", "1d"),
            )
        elif action == "FUND_FLOW":
            return await yfinance_service.get_fund_flow(params.get("symbol"))
        elif action == "OPTION_CHAIN":
            return await yfinance_service.get_option_chain(params.get("symbol"), expiration=params.get("expiration"))
        elif action == "FINANCIALS":
            return await yfinance_service.get_financials(params.get("symbol"), kind=params.get("kind", "annual"))
        elif action == "SEARCH":
            return await yfinance_service.search(params.get("query", ""), limit=params.get("limit", 10))
        elif action == "TECH":
            return await yfinance_service.get_tech_indicators(
                params.get("symbol"), period=params.get("period", "1y"), indicators=params.get("indicators")
            )
        elif action == "BATCH_QUOTE":
            return await yfinance_service.get_batched_quote(params.get("symbols", []))
        else:
            return {"error": f"未知 yfinance action: {action}"}
    except Exception as e:
        logger.error(f"❌ [YF Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "yfinance"}
