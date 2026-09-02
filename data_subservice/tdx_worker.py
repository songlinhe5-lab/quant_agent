"""TDX worker — 通达信协议（mootdx）：盘中快照 / 分时 / 分钟线与日线增量。

与 akshare_worker 同款薄分发模式；mootdx 是同步 socket，
按 AGENTS §4（禁止 async 里同步阻塞）一律 asyncio.to_thread 卸载。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from data_subservice._internal.logger import logger
from data_subservice._internal.tdx import service as tdx_service


async def handle_tdx(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tdx 数据源请求。"""
    symbol = str(params.get("symbol") or params.get("ticker") or "")
    try:
        if action == "QUOTE_CN_SNAPSHOT":
            return await asyncio.to_thread(tdx_service.get_snapshot, symbol)
        if action == "BARS_CN":
            return await asyncio.to_thread(
                tdx_service.get_bars,
                symbol,
                frequency=str(params.get("frequency") or "day"),
                offset=int(params.get("offset") or 100),
            )
        if action == "MINUTES_CN":
            return await asyncio.to_thread(tdx_service.get_minutes, symbol, date=str(params.get("date") or ""))
        return {"status": "error", "message": f"未知 tdx action: {action}", "source": "tdx"}
    except ValueError as e:  # 代码归一化/参数校验失败：确定性 bad_request，禁止降级缓存
        return {"status": "error", "error_category": "bad_request", "message": str(e), "source": "tdx"}
    except Exception as e:  # noqa: BLE001 - 协议/网络错误统一语义化，由主服务熔断计数
        logger.warning(f"⚠️ [TDX Worker] {action} {symbol} 失败: {e}")
        return {"status": "error", "message": str(e), "source": "tdx"}
