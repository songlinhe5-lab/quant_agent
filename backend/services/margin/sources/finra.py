"""
美股融资融券 / 卖空指标 —— FINRA 监管底层数据源

数据来源 (FINRA 官方数据 API，监管底层，非第三方寻租者)：
- Reg SHO 每日做空成交量：reg_sho_daily_short_sale_volume (group=equity，需 API token)
  https://api.finra.org/data/group/equity/name/reg_sho_daily_short_sale_volume
- Consolidated Short Interest（每半月结算）：consolidatedShortInterest (group=otcMarket)
  https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest

路径格式为 /data/group/{group}/name/{dataset}（旧版 /data/securities/{dataset} 已废弃 404）。
做空成交量数据集在 equity group 需 FINRA_API_TOKEN 认证；做空持仓在 otcMarket 免认证但
可能返回历史快照（FINRA 已迁移部分数据集，仅当数据有效才聚合，绝不写假数据）。

聚合为市场级指标：做空成交占比、卖空余额及 days to cover。
未配置/网络不可达/token 缺失 → 返回 None，由编排器降级。
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
# 做空成交量数据集需认证（equity group），无 token 时该部分优雅降级
FINRA_API_TOKEN = os.getenv("FINRA_API_TOKEN", "")

# FINRA 字段名（与官方 CSV schema 对齐，若官方调整可在此集中修改）。
# 实测 consolidatedShortInterest 返回 CSV，字段为驼峰命名。
_VOL_FIELDS = {
    "short_volume": "shortVolume",
    "short_exempt_volume": "shortExemptVolume",
    "total_volume": "totalVolume",
}
_SI_FIELDS = {
    "short_interest": "currentShortPositionQuantity",
    "avg_daily_volume": "averageDailyVolumeQuantity",
    "days_to_cover": "daysToCoverQuantity",
    "settlement_date": "settlementDate",
}


class FinraRegShoSource(BaseMarginSource):
    name = "finra_reg_sho"
    market = "US"

    def __init__(self, api_base: Optional[str] = None, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.api_base = (api_base or FINRA_API_BASE).rstrip("/")
        self.token = FINRA_API_TOKEN

    def _headers(self) -> Dict[str, str]:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _fetch_daily_short_volume(self, date_str: str) -> Optional[Dict]:
        # Reg SHO 每日做空成交量：group=equity，需 FINRA_API_TOKEN（401 未认证）。
        if not self.token:
            logger.debug("[Margin][finra] 未配置 FINRA_API_TOKEN，跳过做空成交量")
            return None
        url = f"{self.api_base}/group/equity/name/reg_sho_daily_short_sale_volume"
        data = await self._http_get_json(url, params={"date": date_str}, headers=self._headers())
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
        # Consolidated Short Interest：group=otcMarket，免认证，返回 CSV 文本（非 JSON）。
        url = f"{self.api_base}/group/otcMarket/name/consolidatedShortInterest"
        text = await self._http_get_text(url, params={"date": date_str}, headers=self._headers())
        if not text:
            return None
        try:
            import csv as _csv
            import io as _io

            reader = _csv.DictReader(_io.StringIO(text))
            rows = [r for r in reader if r.get(_SI_FIELDS["short_interest"])]
        except Exception as e:  # noqa: BLE001
            logger.warning("[Margin][finra] 做空持仓 CSV 解析失败", error=str(e))
            return None
        if not rows:
            return None
        si = sum(float(r.get(_SI_FIELDS["short_interest"], 0) or 0) for r in rows)
        adv = sum(float(r.get(_SI_FIELDS["avg_daily_volume"], 0) or 0) for r in rows)
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
        snap.note = "FINRA Reg SHO 每日做空成交量 + Consolidated Short Interest（市场级聚合）"
        return snap
