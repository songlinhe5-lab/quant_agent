"""FRED 数据源实现（物理解耦裁剪版，下沉自 backend.services.macro.fred_service）

只保留与业务无关、纯粹获取 FRED 独立宏观数据源的 REST 逻辑。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=fred) 访问本实现。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://api.stlouisfed.org/fred"


class FREDService:
    """FRED 底层 REST 客户端（子服务叶子节点）。"""

    @property
    def api_key(self) -> str:
        return os.getenv("FRED_API_KEY", "")

    async def get_series_observations(self, series_id: str, limit: int = 100) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "error", "message": "FRED_API_KEY 未配置"}
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{_BASE}/series/observations", params=params)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"FRED request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "FRED 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"FRED HTTP {r.status_code}"}

    async def get_releases_dates(self, limit: int = 1000, sort_order: str = "desc") -> dict[str, Any]:
        """获取 FRED 全部数据发布日期原始序列（主服务负责窗口过滤与事件归一化）。"""
        if not self.api_key:
            return {"status": "error", "message": "FRED_API_KEY 未配置"}
        params = {
            "api_key": self.api_key,
            "file_type": "json",
            "limit": limit,
            "sort_order": sort_order,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{_BASE}/releases/dates", params=params)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"FRED request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "FRED 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"FRED HTTP {r.status_code}"}

    async def get_economic_calendar(self, days_ahead: int = 7, days_back: int = 0) -> dict[str, Any]:
        """FRED 无原生日历，复用 series/observations 近窗口（与 backend 行为对齐）。"""
        return await self.get_series_observations("FEDFUNDS", limit=days_ahead + days_back + 5)


fred_service = FREDService()
