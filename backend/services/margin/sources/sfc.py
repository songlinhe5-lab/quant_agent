"""
港股淡仓（卖空余额）—— SFC 监管底层数据源（可配置 URL）

数据来源：SFC 每周公布的《淡仓申报》(Short Position Reporting) 原始文件
（市场级卖空余额；比率需流通股本，本适配器仅聚合股数，比率交由上层补充）。

配置（环境变量，未配置则优雅降级为 None）：
    SFC_SHORT_POSITIONS_URL     SFC 每周淡仓申报文件 URL（CSV）
    SFC_SHORT_POSITIONS_COLUMNS 可选：列名映射 JSON，覆盖默认关键词匹配
"""

import io
import json
import os
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
import structlog

from backend.services.margin.sources.base import BaseMarginSource, MarketMarginSnapshot

logger = structlog.get_logger(__name__)

_DEFAULT_COLUMNS = {
    "short_position": [
        "short position",
        "short positions",
        "淡仓",
        "short position (shares)",
        "short position shares",
    ],
}


class SfcShortPositionsSource(BaseMarginSource):
    name = "sfc_short_positions"
    market = "HK"

    def __init__(self):
        super().__init__()
        self.url: Optional[str] = os.getenv("SFC_SHORT_POSITIONS_URL") or None
        self.columns = self._load_columns("SFC_SHORT_POSITIONS_COLUMNS", _DEFAULT_COLUMNS)

    @staticmethod
    def _load_columns(env_key: str, defaults: Dict[str, List[str]]) -> Dict[str, List[str]]:
        raw = os.getenv(env_key)
        if raw:
            try:
                overrides = json.loads(raw)
                defaults.update({k: v for k, v in overrides.items() if isinstance(v, list)})
            except Exception as e:
                logger.warning("[Margin][sfc] 列映射 JSON 解析失败，使用默认", error=str(e))
        return defaults

    @staticmethod
    def _find_col(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
        low = {c: str(c).lower() for c in df.columns}
        for kw in keywords:
            kwl = kw.lower()
            for col, coll in low.items():
                if kwl in coll:
                    return col
        return None

    def _parse(self, text: str, as_of: date) -> Optional[MarketMarginSnapshot]:
        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception as e:
            logger.warning("[Margin][sfc] CSV 解析失败", error=str(e))
            return None
        if df.empty:
            return None

        col = self._find_col(df, self.columns["short_position"])
        if not col:
            logger.warning("[Margin][sfc] 未识别到淡仓股数列，无法聚合")
            return None

        shares = pd.to_numeric(df[col], errors="coerce").sum()
        if not shares or shares <= 0:
            return None

        snap = MarketMarginSnapshot(
            market="HK",
            as_of=as_of.isoformat(),
            short_interest_shares=float(shares),
        )
        snap.note = "SFC 每周淡仓申报（市场级聚合；比率需流通股本补充）"
        return snap

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        if not self.url:
            logger.debug("[Margin][sfc] 未配置 SFC_SHORT_POSITIONS_URL，跳过")
            return None
        text = await self._http_get_text(self.url, params={"date": as_of.isoformat()})
        if not text:
            return None
        return self._parse(text, as_of)
