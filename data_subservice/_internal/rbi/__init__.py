"""RBI 数据源实现（物理解耦裁剪版，下沉自 backend.services.macro.rbi）

只保留与业务无关、纯粹抓取 RBI 公开宏观经济数据的逻辑。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=rbi) 访问本实现。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from data_subservice._internal.logger import logger

_BASE = "https://www.rbi.org.in"


class RBIService:
    """RBI 公开数据抓取客户端（子服务叶子节点）。"""

    async def get_economic_calendar(self, days_ahead: int = 7, days_back: int = 0) -> dict[str, Any]:
        """RBI 无标准化日历 API，返回近期公告页快照（与 backend 行为对齐）。"""
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
                r = await c.get(f"{_BASE}/Scripts/BS_PressRelease.aspx")
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"RBI request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": {"url": r.url, "length": len(r.text)}}
        if r.status_code == 429:
            return {"status": "error", "message": "RBI 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"RBI HTTP {r.status_code}"}


rbi_service = RBIService()
