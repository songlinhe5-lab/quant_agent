"""
BE-02 融资融券 / 卖空市场级指标 —— 数据源编排框架

设计原则 (呼应 AGENTS.md 零幻觉红线)：
- 所有数据必须来自监管机构底层原始文件 / 官方数据 API，绝不写假数据。
- 数据源以适配器形式接入，按市场优先级链式尝试，任一成功即返回并写 Redis 缓存。
- 全部失败 → 返回 error 状态（不填充任何编造数字）。

数据来源（监管底层，非 API 寻租者）：
- 美股 (US)：FINRA Reg SHO 每日做空成交量 (api.finra.org) + 每半月 Equity Short Interest
- 港股 (HK)：HKEX 每日卖空成交报表 + SFC 每周淡仓申报
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional, Protocol, runtime_checkable

import aiohttp
import structlog

from backend.core.redis_client import redis_client

logger = structlog.get_logger(__name__)

CACHE_TTL = 86400  # 1 天


def _cache_key(market: str, as_of: date) -> str:
    return f"quant:margin:{market}:{as_of.isoformat()}"


@dataclass
class MarketMarginSnapshot:
    """市场级融资融券 / 卖空指标聚合"""

    market: str
    as_of: str
    short_sale_volume: Optional[float] = None  # 做空成交量（股）
    total_volume: Optional[float] = None  # 总成交量（股）
    short_volume_ratio: Optional[float] = None  # 做空成交占比 (%)
    short_interest_shares: Optional[float] = None  # 卖空余额（股，结算后公布）
    short_interest_ratio: Optional[float] = None  # 做空余额相对 ADV 的天数 (days to cover)
    financing_balance: Optional[float] = None  # 融资余额（若有）
    securities_balance: Optional[float] = None  # 融券余额（若有）
    sources: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k in ("market", "as_of", "sources", "note")}


@runtime_checkable
class MarginIndicatorSource(Protocol):
    name: str
    market: str

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        """拉取并聚合该来源的市场级指标；失败 / 无数据时返回 None"""
        ...


class BaseMarginSource:
    """适配器基类：统一 HTTP 获取与缓存封装"""

    name: str = "base"
    market: str = ""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def _http_get_json(
        self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ) -> Optional[object]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.warning(f"[Margin][{self.name}] HTTP JSON 获取失败", url=url, error=str(e))
            return None

    async def _http_get_text(
        self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    resp.raise_for_status()
                    return await resp.text()
        except Exception as e:
            logger.warning(f"[Margin][{self.name}] HTTP 文本获取失败", url=url, error=str(e))
            return None

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:  # pragma: no cover - 子类实现
        raise NotImplementedError


# ── 编排器 ────────────────────────────────────────────────────────
from backend.services.margin.sources.cboe import CboeShortInterestSource  # noqa: E402
from backend.services.margin.sources.finra import FinraRegShoSource  # noqa: E402
from backend.services.margin.sources.futu import FutuShortSellingSource  # noqa: E402
from backend.services.margin.sources.hkex import HkexShortSellingSource  # noqa: E402
from backend.services.margin.sources.sfc import SfcShortPositionsSource  # noqa: E402

# US 源优先级 (2026-08-13 调整):
#  1) CboeShortInterestSource —— CBOE 公开做空持仓 CSV，免 token、稳定、无反爬；
#     提供 short_interest_shares / days_to_cover，作为 FINRA 免 token 路径的优先兜底。
#  2) FinraRegShoSource —— FINRA Reg SHO 每日做空成交量 (需 token)，与 CBOE 互补
#     (提供 short_sale_volume / ratio)。两者字段不冲突，编排器按字段合并。
_US_SOURCES: List[MarginIndicatorSource] = [CboeShortInterestSource(), FinraRegShoSource()]
# 港股源优先级：HKEX(每日卖空成交) → SFC(每周淡仓余额) → Futu(卖空榜聚合兜底)。
# Futu 仅作兜底：监管源不可用时提供真实可算的市场级占比，不覆盖监管源。
_HK_SOURCES: List[MarginIndicatorSource] = [
    HkexShortSellingSource(),
    SfcShortPositionsSource(),
    FutuShortSellingSource(),
]


def _merge_snapshot(acc: Optional[Dict], snap: MarketMarginSnapshot) -> Dict:
    """字段级合并多个源的聚合结果（互补填充，首个非空优先）。

    不同数据源提供互补字段（如 CBOE=做空持仓、FINRA=做空成交量），
    不应首个成功即 return，而应合并以得到最完整的市场级指标。
    """
    d = snap.to_dict()
    if acc is None:
        return d
    for k, v in d.items():
        if v is None:
            continue
        if acc.get(k) is None:
            acc[k] = v
        elif k == "sources":
            # sources 列表合并去重
            acc[k] = list(dict.fromkeys(acc[k] + (v or [])))
        elif k == "note" and v:
            acc[k] = (acc.get(k, "") + " | " + v).strip(" |")
        # 其它同名非空字段：保留首个源（高优先级源优先），不覆盖
    return acc


def _sources_for(market: str) -> List[MarginIndicatorSource]:
    if market == "US":
        return _US_SOURCES
    if market == "HK":
        return _HK_SOURCES
    return []


async def get_market_margin_indicators(market: str, as_of: Optional[date] = None) -> Dict:
    """
    获取市场级融资融券 / 卖空指标（真实监管数据源，链式降级）。

    Returns:
        成功 -> MarketMarginSnapshot.to_dict()
        失败 -> {"status": "error", ...}（绝不返回编造数字）
    """
    as_of = as_of or date.today()
    cache_key = _cache_key(market, as_of)

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            logger.debug("[Margin] 命中缓存", market=market, as_of=as_of.isoformat())
            return json.loads(cached)
    except Exception as e:
        logger.debug("[Margin] 读缓存失败(忽略)", error=str(e))

    result: Optional[Dict] = None
    tried: List[str] = []
    any_success = False
    for src in _sources_for(market):
        tried.append(src.name)
        try:
            snap = await src.fetch(as_of)
            if snap is not None:
                any_success = True
                # 标记数据来源（去重，避免与源内部已 append 的重复）
                if src.name not in snap.sources:
                    snap.sources.append(src.name)
                # 字段级合并（互补填充），而非首个成功即返回
                result = _merge_snapshot(result, snap)
                logger.info("[Margin] 数据源成功(已合并)", source=src.name, market=market)
        except Exception as e:
            logger.error("[Margin] 数据源异常", source=src.name, error=str(e))

    if not any_success or result is None:
        result = {
            "status": "error",
            "market": market,
            "as_of": as_of.isoformat(),
            "message": f"无法从监管数据源获取真实数据 (tried: {', '.join(tried)})，请配置数据源或于结算日后重试",
        }
    else:
        try:
            await redis_client.set(cache_key, json.dumps(result), ex=CACHE_TTL)
        except Exception as e:
            logger.debug("[Margin] 写缓存失败(忽略)", error=str(e))

    return result
