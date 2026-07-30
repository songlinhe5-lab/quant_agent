"""
美股融资融券 / 卖空指标 —— FINRA 监管底层数据源

数据来源 (FINRA 官方数据 API，监管底层，非第三方寻租者)：
- Reg SHO 每日做空成交量：fo_us_sn_short_sale_volume
  https://api.finra.org/data/securities/fo_us_sn_short_sale_volume?date=YYYY-MM-DD
- Equity Short Interest（每半月结算）：fo_us_equity_short_interest
  https://api.finra.org/data/equity/fo_us_equity_short_interest?date=YYYY-MM-DD

聚合为市场级指标：做空成交占比、卖空余额及 days to cover。
未配置或网络不可达 → 返回 None，由编排器降级（绝不写假数据）。
"""

import asyncio
import os
from datetime import date
from typing import Dict, Optional

import structlog

from backend.services.margin.sources.base import BaseMarginSource, MarketMarginSnapshot

logger = structlog.get_logger(__name__)

# 可经环境变量覆盖（默认 FINRA 官方 Query API）
FINRA_API_BASE = os.getenv("FINRA_API_BASE", "https://api.finra.org/data")

# FINRA 字段名（与其公布 schema 对齐，若官方调整可在此集中修改）
_VOL_FIELDS = {
    "short_volume": "shortVolume",
    "short_exempt_volume": "shortExemptVolume",
    "total_volume": "totalVolume",
}
_SI_FIELDS = {
    "short_interest": "current_short_interest",
    "avg_daily_volume": "average_daily_volume",
}


class FinraRegShoSource(BaseMarginSource):
    name = "finra_reg_sho"
    market = "US"

    def __init__(self, api_base: Optional[str] = None, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.api_base = (api_base or FINRA_API_BASE).rstrip("/")

    async def _fetch_daily_short_volume(self, date_str: str) -> Optional[Dict]:
        url = f"{self.api_base}/securities/fo_us_sn_short_sale_volume"
        data = await self._http_get_json(url, params={"date": date_str})
        if not isinstance(data, list) or not data:
            return None
        sv = sum(float(r.get(_VOL_FIELDS["short_volume"], 0) or 0) for r in data)
        tv = sum(float(r.get(_VOL_FIELDS["total_volume"], 0) or 0) for r in data)
        if tv <= 0:
            return None
        return {
            "short_volume": sv,
            "total_volume": tv,
            "ratio": round(sv / tv * 100, 4),
        }

    async def _fetch_equity_short_interest(self, date_str: str) -> Optional[Dict]:
        url = f"{self.api_base}/equity/fo_us_equity_short_interest"
        data = await self._http_get_json(url, params={"date": date_str})
        if not isinstance(data, list) or not data:
            return None
        si = sum(float(r.get(_SI_FIELDS["short_interest"], 0) or 0) for r in data)
        adv = sum(float(r.get(_SI_FIELDS["avg_daily_volume"], 0) or 0) for r in data)
        if si <= 0:
            return None
        days_to_cover = round(si / adv, 4) if adv > 0 else None
        return {"short_interest": si, "days_to_cover": days_to_cover}

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        date_str = as_of.strftime("%Y-%m-%d")
        vol, si = await asyncio.gather(
            self._fetch_daily_short_volume(date_str),
            self._fetch_equity_short_interest(date_str),
            return_exceptions=True,
        )

        snap = MarketMarginSnapshot(market="US", as_of=date_str)
        ok = False
        if isinstance(vol, dict):
            snap.short_sale_volume = vol["short_volume"]
            snap.total_volume = vol["total_volume"]
            snap.short_volume_ratio = vol["ratio"]
            ok = True
        if isinstance(si, dict):
            snap.short_interest_shares = si["short_interest"]
            snap.short_interest_ratio = si["days_to_cover"]
            ok = True

        if not ok:
            return None
        snap.note = "FINRA Reg SHO 每日做空成交量 + Equity Short Interest（市场级聚合）"
        return snap
