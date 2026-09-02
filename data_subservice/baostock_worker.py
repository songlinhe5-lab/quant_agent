"""BaoStock worker — A股历史 K 线 / 季频财务 / 复权因子（免费协议源，T+1）。

与 akshare_worker 同款薄分发模式；区别：baostock SDK 是同步阻塞 TCP API，
按 AGENTS §4（禁止 async 里同步阻塞）一律 asyncio.to_thread 卸载。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from data_subservice._internal.baostock import service as baostock_service
from data_subservice._internal.logger import logger


async def handle_baostock(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 baostock 数据源请求。"""
    symbol = str(params.get("symbol") or params.get("ticker") or "")
    try:
        if action == "KLINE_CN":
            return await asyncio.to_thread(
                baostock_service.get_kline,
                symbol,
                start_date=str(params.get("start_date") or ""),
                end_date=str(params.get("end_date") or ""),
                frequency=str(params.get("frequency") or "d"),
                adjust=str(params.get("adjust") or "front"),
            )
        if action == "FUNDAMENTALS_CN":
            year = int(params.get("year") or 0)
            quarter = int(params.get("quarter") or 0)
            if not year or not quarter:
                return {
                    "status": "error",
                    "error_category": "bad_request",
                    "message": "FUNDAMENTALS_CN 需要 year + quarter",
                    "source": "baostock",
                }
            return await asyncio.to_thread(baostock_service.get_quarter_fundamental, symbol, year, quarter)
        if action == "ADJUST_FACTOR_CN":
            return await asyncio.to_thread(
                baostock_service.get_adjust_factor,
                symbol,
                start_date=str(params.get("start_date") or ""),
                end_date=str(params.get("end_date") or ""),
            )
        if action == "STOCK_BASIC_CN":
            return await asyncio.to_thread(baostock_service.get_stock_basic, symbol)
        return {"status": "error", "message": f"未知 baostock action: {action}", "source": "baostock"}
    except ValueError as e:  # 代码归一化/参数校验失败：确定性 bad_request，禁止降级缓存
        return {"status": "error", "error_category": "bad_request", "message": str(e), "source": "baostock"}
    except Exception as e:  # noqa: BLE001 - 协议/网络错误统一语义化，由主服务熔断计数
        logger.warning(f"⚠️ [BaoStock Worker] {action} {symbol} 失败: {e}")
        return {"status": "error", "message": str(e), "source": "baostock"}
