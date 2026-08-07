"""DBnomics 数据源实现（物理解耦裁剪版，下沉自 backend.services.macro.dbnomics）

只保留与业务无关、纯粹获取 DBnomics 独立宏观数据源的 REST 逻辑。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=dbnomics) 访问本实现。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from data_subservice._internal.logger import logger

_BASE = "https://api.db.nomics.world/api/v1"


class DbnomicsService:
    """DBnomics 底层 REST 客户端（子服务叶子节点）。"""

    async def get_economic_calendar(self, days_ahead: int = 7, days_back: int = 0) -> dict[str, Any]:
        """DBnomics 无原生日历，返回近期可用数据集清单（与 backend 行为对齐）。"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{_BASE}/datasets")
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"DBnomics request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "DBnomics 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"DBnomics HTTP {r.status_code}"}


dbnomics_service = DbnomicsService()
