"""DBnomics 采集 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=dbnomics) 访问本 worker。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.dbnomics import dbnomics_service
from data_subservice._internal.logger import logger

_DBNOMICS_DISPATCH: dict[str, Any] = {
    "ECONOMIC_CALENDAR": ("get_economic_calendar", ["days_ahead", "days_back"]),
    # BE-ARCH-07f: 主服务 EM CPI 回填所需的 OECD G20 CPI 原始序列
    "EM_CPI_SERIES": ("get_em_cpi_series", ["countries"]),
}


async def handle_dbnomics(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action not in _DBNOMICS_DISPATCH:
        logger.warning(f"⚠️ [DBnomics] 未知动作: {action}")
        return {"error": f"unknown dbnomics action: {action}"}

    method_name, arg_names = _DBNOMICS_DISPATCH[action]
    method = getattr(dbnomics_service, method_name)
    call_args = {k: params.get(k) for k in arg_names if params.get(k) is not None}
    return await method(**call_args)


async def startup() -> None:
    logger.info("[DBnomics-worker] 初始化完成 (DBnomics REST 客户端就绪)")
