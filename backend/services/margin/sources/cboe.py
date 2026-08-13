"""
美股做空持仓（Short Interest）—— CBOE 免费公开 CSV 兜底源

数据来源 (CBOE 官方公开披露，免 token、无反爬、直链 CDN)：
- BATS/CBOE 上市全市场做空持仓半月报：
  https://cdn.cboe.com/resources/us/equities/market-statistics/short-interest/
      Bats_Listed_Short_Interest-finra-{YYYYMMDD}.csv

该端点由 CBOE 每日/每半月发布，覆盖 CBOE/BATS 上市的全体美股 + ETF。
字段说明（CSV header）：
  Cycle Settlement Date       结算日 (YYYYMMDD)
  BATS-Symbol                 标的代码
  Security Name               名称
  # Shares Net Short Current Cycle   当前周期做空净持仓(股)
  # Shares Net Short Previous Cycle  上一周期做空净持仓(股)
  Cycle Avg Daily Trade Vol          周期日均成交量(股)
  Min # of Trade Days To Cover Shorts 最小回补天数
  Percent Change in Short Position    做空持仓环比变化(%)
  Change in Short Position From Previous 做空持仓变化(股)

设计定位：
- 这是「做空持仓 (short interest)」品类，与 FINRA consolidatedShortInterest 同源，
  但 CBOE 端点稳定、免 token、无 Cloudflare 反爬 —— 作为 FINRA 免 token 路径的
  优先免费兜底源（FINRA otcMarket 接口此前实测 stale/不稳定）。
- 仅覆盖 CBOE/BATS 上市证券（非纽交所全量），但含主流 ETF + 大量美股，足以
  支撑市场级聚合指标（全市场做空总股数、做空占日均成交量比、回补天数中位数）。
- 非「每日做空成交量」(reg_sho_daily_short_sale_volume 品类)，后者仍需 FINRA token。
- 无数据时返回 None，由编排器降级，绝不写假数据（零幻觉红线）。
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import List, Optional

import structlog

from backend.services.margin.sources.base import BaseMarginSource, MarketMarginSnapshot

logger = structlog.get_logger(__name__)

# CBOE 公开短融持仓 CSV 目录（直链 CDN，免 token）
CBOE_SI_BASE = "https://cdn.cboe.com/resources/us/equities/market-statistics/short-interest"
CBOE_SI_FILE = "Bats_Listed_Short_Interest-finra-{date}.csv"
# 最多向前探测多少个候选发布日（半月报，间隔约 15 天；留足余量）
_MAX_LOOKBACK_DAYS = 45


def _csv_url_for(d: date) -> str:
    return f"{CBOE_SI_BASE}/{CBOE_SI_FILE.format(date=d.strftime('%Y%m%d'))}"


class CboeShortInterestSource(BaseMarginSource):
    """CBOE 免费做空持仓 CSV 源（市场级聚合兜底）"""

    name = "cboe_short_interest"
    market = "US"

    def __init__(self, timeout: float = 30.0, base_url: Optional[str] = None):
        super().__init__(timeout=timeout)
        self.base_url = (base_url or CBOE_SI_BASE).rstrip("/")

    def _build_url(self, d: date) -> str:
        stem = CBOE_SI_FILE.format(date=d.strftime("%Y%m%d"))
        return f"{self.base_url}/{stem}"

    async def _fetch_latest_csv(self, as_of: date) -> Optional[str]:
        """从 as_of 向前探测，找到第一个可用的 CSV 发布日。

        返回该日 CSV 文本；全部失败返回 None。
        CBOE 半月报发布日接近 settlement date（月末/半月末），发布会有 1-数日延迟，
        故从 as_of 向前最多 _MAX_LOOKBACK_DAYS 天探测。
        """
        for back in range(0, _MAX_LOOKBACK_DAYS + 1):
            cand = as_of - timedelta(days=back)
            url = self._build_url(cand)
            text = await self._http_get_text(url)
            if text and "BATS-Symbol" in text:
                logger.debug("[Margin][cboe] 命中短融 CSV", url=url, lookback=back)
                return text
            if back == 0:
                # 当天无文件属正常（未到发布日），不告警
                continue
        logger.debug("[Margin][cboe] 向前探测均未取到有效 CSV", as_of=as_of.isoformat())
        return None

    def _aggregate(self, text: str, as_of: str) -> Optional[MarketMarginSnapshot]:
        """解析 CSV 并汇总为市场级指标。

        个股口径字段：
          short_shares = # Shares Net Short Current Cycle
          avg_daily_vol = Cycle Avg Daily Trade Vol
          days_to_cover = Min # of Trade Days To Cover Shorts
        市场级聚合：
          short_interest_shares = Σ short_shares（覆盖标的做空总股数）
          short_interest_ratio   = 做空总股数 / Σ avg_daily_vol 的回补天数近似
                                    （用 Σshort_shares / Σavg_daily_vol 表示"以日均量回补所需天数"）
        注：MarketMarginSnapshot.short_interest_ratio 语义为 days_to_cover，故此处存市场级回补天数。
        """
        reader = csv.DictReader(io.StringIO(text))
        total_short = 0.0
        total_adv = 0.0
        dtc_values: List[float] = []
        n = 0
        for row in reader:
            sym = (row.get("BATS-Symbol") or "").strip()
            if not sym:
                continue
            try:
                ss = float(row.get("# Shares Net Short Current Cycle") or 0 or 0)
                adv = float(row.get("Cycle Avg Daily Trade Vol") or 0 or 0)
            except (TypeError, ValueError):
                continue
            if ss <= 0:
                # 无效/无做空持仓行跳过（避免污染聚合）
                continue
            total_short += ss
            total_adv += adv
            dtc_raw = row.get("Min # of Trade Days To Cover Shorts")
            try:
                if dtc_raw not in (None, "", "0.00", "0"):
                    dtc_values.append(float(dtc_raw))
            except (TypeError, ValueError):
                pass
            n += 1

        if n == 0 or total_short <= 0:
            return None

        # 市场级回补天数：以总做空股数 / 总日均成交量 表达（保守下界估计）
        market_dtc = round(total_short / total_adv, 4) if total_adv > 0 else None
        snap = MarketMarginSnapshot(market="US", as_of=as_of)
        snap.short_interest_shares = total_short
        snap.short_interest_ratio = market_dtc
        snap.sources.append(self.name)
        snap.note = (
            f"CBOE/BATS 公开做空持仓半月报聚合（覆盖 {n} 只标的，"
            f"做空总股数 {total_short:,.0f}，市场级回补天数≈{market_dtc}）"
        )
        return snap

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        date_str = as_of.isoformat()
        text = await self._fetch_latest_csv(as_of)
        if not text:
            logger.debug("[Margin][cboe] 无可用短融 CSV", as_of=date_str)
            return None
        try:
            snap = self._aggregate(text, date_str)
        except Exception as e:  # noqa: BLE001
            logger.warning("[Margin][cboe] CSV 聚合异常", error=str(e))
            return None
        if snap is None:
            return None
        logger.info("[Margin][cboe] 短融持仓聚合成功", as_of=date_str, symbols=snap.note)
        return snap
