"""RBI 采集 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=rbi) 访问本 worker。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.logger import logger
from data_subservice._internal.rbi import rbi_service

_RBI_DISPATCH: dict[str, Any] = {
    "ECONOMIC_CALENDAR": ("get_economic_calendar", ["days_ahead", "days_back"]),
}


async def handle_rbi(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action not in _RBI_DISPATCH:
        logger.warning(f"⚠️ [RBI] 未知动作: {action}")
        return {"error": f"unknown rbi action: {action}"}

    method_name, arg_names = _RBI_DISPATCH[action]
    method = getattr(rbi_service, method_name)
    call_args = {k: params.get(k) for k in arg_names if params.get(k) is not None}
    return await method(**call_args)


async def startup() -> None:
    logger.info("[RBI-worker] 初始化完成 (RBI 抓取客户端就绪)")
