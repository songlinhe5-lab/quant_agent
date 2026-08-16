"""
港股卖空成交 —— HKEX 监管底层数据源（可配置 URL）

数据来源：HKEX 每日发布的《卖空成交 - 每日报表》原始文件
（港股源无干净的免费市场级 API，故由运维将监管底层文件 URL 通过环境变量注入，
适配器负责拉取 + 解析 + 市场级聚合，绝不写假数据）。

配置（环境变量，未配置则使用下面 DEFAULT_HKEX_URL 兜底模板）：
    HKEX_SHORT_SELLING_URL     HKEX 每日卖空成交报表文件 URL（CSV，支持 {YYYYMMDD} 占位符）
    HKEX_SHORT_SELLING_COLUMNS 可选：列名映射 JSON，覆盖默认关键词匹配

列识别为 best-effort（中英文关键词），若实际文件列名不同，调环境变量即可，无需改代码。
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

# 默认 HKEX 每日卖空成交报表 CSV 模板（env 未配置时使用；{YYYYMMDD} 按当天日期替换）。
# 若实际文件 URL 格式变化，配 HKEX_SHORT_SELLING_URL 环境变量覆盖即可，无需改代码。
DEFAULT_HKEX_URL = "https://www.hkex.com.hk/chi/stat/smarts/short_selling_{YYYYMMDD}.csv"

_DEFAULT_COLUMNS = {
    "short_turnover": [
        "short sell turnover",
        "short-selling turnover",
        "short turnover",
        "沽空成交",
        "卖空成交额",
        "卖空成交金额",
    ],
    "total_turnover": ["total turnover", "总成交", "成交总额"],
    "short_volume": [
        "short sell volume",
        "short volume",
        "short sell vol",
        "沽空量",
        "卖空成交量",
        "卖空股数",
    ],
    "total_volume": ["total volume", "总成交量", "总股数"],
}


class HkexShortSellingSource(BaseMarginSource):
    name = "hkex_short_selling"
    market = "HK"

    def __init__(self):
        super().__init__()
        # 环境变量优先；未配置则使用默认模板（{YYYYMMDD} 占位符在 fetch 时按日期替换）
        self.url: Optional[str] = os.getenv("HKEX_SHORT_SELLING_URL") or DEFAULT_HKEX_URL
        self.columns = self._load_columns("HKEX_SHORT_SELLING_COLUMNS", _DEFAULT_COLUMNS)

    @staticmethod
    def _load_columns(env_key: str, defaults: Dict[str, List[str]]) -> Dict[str, List[str]]:
        raw = os.getenv(env_key)
        if raw:
            try:
                overrides = json.loads(raw)
                defaults.update({k: v for k, v in overrides.items() if isinstance(v, list)})
            except Exception as e:
                logger.warning("[Margin][hkex] 列映射 JSON 解析失败，使用默认", error=str(e))
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
            logger.warning("[Margin][hkex] CSV 解析失败", error=str(e))
            return None
        if df.empty:
            return None

        snap = MarketMarginSnapshot(market="HK", as_of=as_of.isoformat())
        st = self._find_col(df, self.columns["short_turnover"])
        tt = self._find_col(df, self.columns["total_turnover"])
        sv = self._find_col(df, self.columns["short_volume"])
        tv = self._find_col(df, self.columns["total_volume"])

        # 优先用成交额口径，其次用成交量口径
        if st and tt:
            s = pd.to_numeric(df[st], errors="coerce").sum()
            t = pd.to_numeric(df[tt], errors="coerce").sum()
            if t and t > 0:
                snap.short_sale_volume = float(s)
                snap.total_volume = float(t)
                snap.short_volume_ratio = round(float(s) / float(t) * 100, 4)
        elif sv and tv:
            s = pd.to_numeric(df[sv], errors="coerce").sum()
            t = pd.to_numeric(df[tv], errors="coerce").sum()
            if t and t > 0:
                snap.short_sale_volume = float(s)
                snap.total_volume = float(t)
                snap.short_volume_ratio = round(float(s) / float(t) * 100, 4)

        if snap.short_volume_ratio is None:
            logger.warning("[Margin][hkex] 未识别到卖空/总成交列，无法聚合")
            return None
        snap.note = "HKEX 每日卖空成交报表（市场级聚合）"
        return snap

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        if not self.url:
            logger.debug("[Margin][hkex] 未配置 HKEX_SHORT_SELLING_URL，跳过")
            return None
        # 支持 URL 模板：含 {YYYYMMDD} 占位符时按日期自动拼真实地址，
        # 否则视为固定直链原样使用（兼容旧的完整固定 URL 配置）。
        url = self.url
        if "{YYYYMMDD}" in url:
            url = url.replace("{YYYYMMDD}", as_of.strftime("%Y%m%d"))
        text = await self._http_get_text(url, params={"date": as_of.isoformat()})
        if not text:
            return None
        return self._parse(text, as_of)
