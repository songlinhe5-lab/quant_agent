"""Tushare worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.logger import logger
from data_subservice._internal.tushare import tushare_service


async def handle_tushare(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tushare 数据源请求。

    新增 6 个 action（STOCK_HISTORY / STOCK_QUOTE / FUNDAMENTAL / STOCK_LIST /
    LOWFREQ_HISTORY / MACRO）补全审计发现的能力缺口（audit: capability-gap）。
    """
    try:
        if action == "FINANCIALS":
            return await tushare_service.get_financials(
                params.get("symbol"), report_type=params.get("report_type", "income")
            )
        elif action == "HOLDER":
            return await tushare_service.get_holder_number(params.get("symbol"))
        elif action == "MONEYFLOW":
            return await tushare_service.get_moneyflow(params.get("symbol"))
        elif action == "STOCK_HISTORY":
            return await tushare_service.get_daily_history(
                params.get("symbol"),
                params.get("start_date", ""),
                params.get("end_date", ""),
                asset=params.get("asset", "E"),
            )
        elif action == "STOCK_QUOTE":
            return await tushare_service.get_realtime_quote(params.get("symbol"))
        elif action == "FUNDAMENTAL":
            # fundamental 在子服务内部分流到 daily_basic（PE/PB/市值）或 financials
            if params.get("kind") == "daily_basic":
                return await tushare_service.get_daily_basic(
                    params.get("symbol"),
                    trade_date=params.get("trade_date", ""),
                    start_date=params.get("start_date", ""),
                    end_date=params.get("end_date", ""),
                )
            return await tushare_service.get_financials(
                params.get("symbol"), report_type=params.get("report_type", "income")
            )
        elif action == "STOCK_LIST":
            return await tushare_service.get_stock_basic(
                list_status=params.get("list_status", "L"),
                exchange=params.get("exchange", ""),
                fields=params.get("fields", "ts_code,symbol,name,area,industry,market,list_status,list_date"),
            )
        elif action == "LOWFREQ_HISTORY":
            return await tushare_service.get_lowfreq_history(
                params.get("symbol"),
                params.get("freq", "W"),
                params.get("start_date", ""),
                params.get("end_date", ""),
            )
        elif action == "MACRO":
            return await tushare_service.get_macro(
                params.get("symbol"),
                params.get("start_date", ""),
                params.get("end_date", ""),
            )
        else:
            return {"error": f"未知 tushare action: {action}"}
    except Exception as e:
        logger.error(f"❌ [TS Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "tushare"}
