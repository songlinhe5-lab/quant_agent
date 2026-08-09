"""AKShare worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.akshare import akshare_service
from data_subservice._internal.logger import logger


async def handle_akshare(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 akshare 数据源请求。"""
    try:
        if action == "QUOTE":
            return await akshare_service.get_quote(params.get("symbol"), market=params.get("market", "A"))
        elif action == "HISTORY":
            return await akshare_service.get_history(
                params.get("symbol"), market=params.get("market", "A"), period=params.get("period", "daily")
            )
        elif action == "FUND_FLOW":
            return await akshare_service.get_fund_flow(params.get("symbol"))
        elif action == "SOUTHBOUND":
            return await akshare_service.get_southbound()
        elif action == "HK_CONNECT":
            return await akshare_service.get_hk_connect()
        elif action == "HSGT_HOLDERS":
            return await akshare_service.get_hsgt_top_holders(params.get("symbol", "00700"))
        elif action == "STOCK_NEWS":
            return await akshare_service.get_stock_news(params.get("ticker"))
        elif action == "QUOTE_A":
            return await akshare_service.get_quote_a(params.get("ticker"))
        elif action == "HISTORY_A":
            return await akshare_service.get_history_a(params.get("ticker"), num=params.get("num", 60))
        elif action in ("CALENDAR", "ECONOMIC_CALENDAR"):
            return await akshare_service.get_econ_cal(
                days_ahead=params.get("days_ahead", 7), days_back=params.get("days_back", 0)
            )
        elif action == "NEWS":
            return await akshare_service.get_hk_news(days=params.get("days", 3))
        elif action == "MARGIN_A_SHARE":
            return await akshare_service.get_margin_a_share()
        elif action == "SECTOR_FLOW_A":
            return await akshare_service.get_sector_flow_a()
        elif action == "SECTOR_FLOW_HK":
            return await akshare_service.get_sector_flow_hk()
        else:
            return {"error": f"未知 akshare action: {action}"}
    except Exception as e:
        logger.error(f"❌ [AK Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "akshare"}
