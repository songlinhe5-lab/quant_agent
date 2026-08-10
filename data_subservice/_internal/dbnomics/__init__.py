"""DBnomics 数据源实现（物理解耦裁剪版，下沉自 backend.services.macro.dbnomics）

只保留与业务无关、纯粹获取 DBnomics 独立宏观数据源的 REST 逻辑。
主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=dbnomics) 访问本实现。
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE = "https://api.db.nomics.world/api/v1"
# ── OECD G20 CPI 数据集（BE-ARCH-07f：主服务 EM CPI 回填的真实数据出口）──
_SERIES_BASE = "https://api.db.nomics.world/v22/series"
_DATASET = "OECD/DSD_G20_PRICES@DF_G20_PRICES"
# 序列后缀: 年度(A) · 国家口径(N) · CPI · 年百分比(PA) · 全口径(_T) · 未做调整(N) · 年增长率(YoY)
_SERIES_SUFFIX = ".A.N.CPI.PA._T.N.GY"

# G20 新兴市场经济体国码（AKShare 与 FRED 盲区）
_EM_CODES = ("ARG", "BRA", "CHN", "IND", "IDN", "MEX", "RUS", "ZAF", "TUR")


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

    async def get_em_cpi_series(self, countries: list[str] | None = None) -> dict[str, Any]:
        """拉取 G20 新兴市场 CPI 年度同比原始序列（observations=true）。

        主服务负责解析 docs -> 事件结构与 Redis 缓存，本方法仅做纯网络出口。
        """
        codes = [str(c).upper() for c in (countries or _EM_CODES) if c]
        series_ids = ",".join(f"{_DATASET}/{code}{_SERIES_SUFFIX}" for code in codes)
        params = {"series_ids": series_ids, "observations": "true"}
        try:
            async with httpx.AsyncClient(timeout=20.0, verify=False) as c:
                r = await c.get(_SERIES_BASE, params=params)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"DBnomics request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "DBnomics 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"DBnomics HTTP {r.status_code}"}


dbnomics_service = DbnomicsService()
