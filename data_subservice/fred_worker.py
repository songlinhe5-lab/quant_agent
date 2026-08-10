"""FRED 采集 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=fred) 访问本 worker。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.fred import fred_service
from data_subservice._internal.logger import logger

_FRED_DISPATCH: dict[str, Any] = {
    "MACRO_SERIES": ("get_series_observations", ["series_id", "limit"]),
    "ECONOMIC_CALENDAR": ("get_economic_calendar", ["days_ahead", "days_back"]),
    # BE-ARCH-07f: 主服务日历解析所需的 FRED 发布日期原始序列
    "RELEASES_DATES": ("get_releases_dates", ["limit", "sort_order"]),
}


async def handle_fred(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action not in _FRED_DISPATCH:
        logger.warning(f"⚠️ [FRED] 未知动作: {action}")
        return {"error": f"unknown fred action: {action}"}

    method_name, arg_names = _FRED_DISPATCH[action]
    method = getattr(fred_service, method_name)
    call_args = {k: params.get(k) for k in arg_names if params.get(k) is not None}
    return await method(**call_args)


async def startup() -> None:
    logger.info("[FRED-worker] 初始化完成 (FRED REST 客户端就绪)")
