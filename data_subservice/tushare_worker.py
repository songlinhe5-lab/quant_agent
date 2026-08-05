"""Tushare worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.logger import logger
from data_subservice._internal.tushare import tushare_service


async def handle_tushare(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tushare 数据源请求。"""
    try:
        if action == "FINANCIALS":
            return await tushare_service.get_financials(
                params.get("symbol"), report_type=params.get("report_type", "income")
            )
        elif action == "HOLDER":
            return await tushare_service.get_holder_number(params.get("symbol"))
        elif action == "MONEYFLOW":
            return await tushare_service.get_moneyflow(params.get("symbol"))
        else:
            return {"error": f"未知 tushare action: {action}"}
    except Exception as e:
        logger.error(f"❌ [TS Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "tushare"}
