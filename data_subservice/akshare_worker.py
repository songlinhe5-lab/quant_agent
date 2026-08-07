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
        elif action == "CALENDAR":
            return await akshare_service.get_econ_cal()
        elif action == "NEWS":
            return await akshare_service.get_hk_news(days=params.get("days", 3))
        else:
            return {"error": f"未知 akshare action: {action}"}
    except Exception as e:
        logger.error(f"❌ [AK Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "akshare"}
