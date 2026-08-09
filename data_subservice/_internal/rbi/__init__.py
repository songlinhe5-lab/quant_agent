"""RBI 数据源实现（物理解耦裁剪版，下沉自 backend.services.macro.rbi）

只保留与业务无关、纯粹抓取 RBI / World Bank 公开宏观经济数据的逻辑。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=rbi) 访问本实现。
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE = "https://www.rbi.org.in"
# BE-ARCH-07f: 印度 CPI 真实出口（World Bank 开放 API，完全免 Key）
_WB_BASE = "https://api.worldbank.org/v2/country/IND/indicator"
_WB_INDICATOR = "FP.CPI.TOTL.ZG"


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
            return {"status": "success", "data": {"url": str(r.url), "length": len(r.text)}}
        if r.status_code == 429:
            return {"status": "error", "message": "RBI 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"RBI HTTP {r.status_code}"}

    async def get_india_cpi_series(self, date_range: str = "2010:2035", per_page: int = 100) -> dict[str, Any]:
        """获取印度 CPI 通胀率 (YoY) 原始序列（World Bank 开放 API）。

        主服务负责解析与 Redis 缓存，本方法仅做纯网络出口。
        """
        params = {"format": "json", "date": date_range, "per_page": per_page}
        try:
            async with httpx.AsyncClient(timeout=12.0, verify=False) as c:
                r = await c.get(f"{_WB_BASE}/{_WB_INDICATOR}", params=params)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"WorldBank request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "WorldBank 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"WorldBank HTTP {r.status_code}"}


rbi_service = RBIService()
