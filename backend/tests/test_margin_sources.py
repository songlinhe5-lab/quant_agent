"""
BE-02 融资融券 / 卖空市场级指标 —— 数据源适配器单元测试

覆盖：
- FINRA Reg SHO 每日做空成交量 + Equity Short Interest 聚合
- HKEX 每日卖空成交报表解析（成交额 / 成交量口径）
- SFC 每周淡仓申报解析
- 编排器 get_market_margin_indicators 链式降级、缓存命中、全失败 error 状态
- 消费封装 get_us_share_margin / get_hk_share_margin 的 {status,data} 信封

原则：全程 mock 网络 (aiohttp)，绝不触发真实 HTTP；断言聚合逻辑正确且无假数据。
"""

import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from backend.services.margin.hk_share import get_hk_share_margin
from backend.services.margin.sources.base import (
    MarketMarginSnapshot,
    get_market_margin_indicators,
)
from backend.services.margin.sources.finra import FinraRegShoSource
from backend.services.margin.sources.hkex import HkexShortSellingSource
from backend.services.margin.sources.sfc import SfcShortPositionsSource
from backend.services.margin.us_share import get_us_share_margin


# ─── FINRA ────────────────────────────────────────────────────────
@pytest.fixture
def finra_volume_json():
    return [
        {"shortVolume": 1000.0, "totalVolume": 5000.0, "shortExemptVolume": 10.0},
        {"shortVolume": 2000.0, "totalVolume": 5000.0, "shortExemptVolume": 5.0},
    ]


@pytest.fixture
def finra_si_json():
    return [
        {"current_short_interest": 6000.0, "average_daily_volume": 1000.0},
        {"current_short_interest": 4000.0, "average_daily_volume": 1000.0},
    ]


async def test_finra_volume_and_si_aggregation(finra_volume_json, finra_si_json):
    src = FinraRegShoSource()

    async def _fake_json(url, params=None):
        if "fo_us_sn_short_sale_volume" in url:
            return finra_volume_json
        if "fo_us_equity_short_interest" in url:
            return finra_si_json
        return None

    src._http_get_json = AsyncMock(side_effect=_fake_json)
    snap = await src.fetch(date(2026, 7, 27))

    assert snap is not None
    assert snap.market == "US"
    # 做空成交量 = 1000 + 2000，总成交量 = 5000 + 5000
    assert snap.short_sale_volume == pytest.approx(3000.0)
    assert snap.total_volume == pytest.approx(10000.0)
    assert snap.short_volume_ratio == pytest.approx(30.0)
    # 卖空余额 = 6000 + 4000 = 10000，ADV = 2000，days to cover = 5
    assert snap.short_interest_shares == pytest.approx(10000.0)
    assert snap.short_interest_ratio == pytest.approx(5.0)


async def test_finra_partial_short_interest_only(finra_si_json):
    src = FinraRegShoSource()

    async def _fake_json(url, params=None):
        if "fo_us_equity_short_interest" in url:
            return finra_si_json
        return None  # 做空成交量缺失

    src._http_get_json = AsyncMock(side_effect=_fake_json)
    snap = await src.fetch(date(2026, 7, 27))

    assert snap is not None
    assert snap.short_sale_volume is None  # 缺失不编造
    assert snap.total_volume is None
    assert snap.short_volume_ratio is None
    assert snap.short_interest_shares == pytest.approx(10000.0)


async def test_finra_both_missing_returns_none():
    src = FinraRegShoSource()
    src._http_get_json = AsyncMock(return_value=None)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None


async def test_finra_http_error_returns_none():
    src = FinraRegShoSource()
    src._http_get_json = AsyncMock(side_effect=Exception("network down"))
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None


async def test_finra_zero_total_volume_skips_ratio(finra_volume_json):
    # 构造总成交为 0 的场景，校验不除零
    zero = [{"shortVolume": 0.0, "totalVolume": 0.0, "shortExemptVolume": 0.0}]
    src = FinraRegShoSource()
    src._http_get_json = AsyncMock(return_value=zero)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None  # total_volume <= 0 → 无法聚合


# ─── HKEX ─────────────────────────────────────────────────────────
_HKEX_TURNOVER_CSV = """Date,Short Sell Turnover,Total Turnover
2026-07-27,1200000,10000000
2026-07-27,800000,10000000
"""

_HKEX_VOLUME_CSV = """Date,Short Sell Volume,Total Volume
2026-07-27,50000,400000
2026-07-27,30000,400000
"""

_HKEX_UNRECOGNIZED_CSV = """Date,Foo,Bar
2026-07-27,1,2
"""


async def test_hkex_parse_turnover_basis():
    src = HkexShortSellingSource()
    src.url = "http://fake/hkex.csv"
    src._http_get_text = AsyncMock(return_value=_HKEX_TURNOVER_CSV)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is not None
    assert snap.market == "HK"
    assert snap.short_sale_volume == pytest.approx(2000000.0)
    assert snap.total_volume == pytest.approx(20000000.0)
    assert snap.short_volume_ratio == pytest.approx(10.0)


async def test_hkex_parse_volume_basis():
    src = HkexShortSellingSource()
    src.url = "http://fake/hkex.csv"
    src._http_get_text = AsyncMock(return_value=_HKEX_VOLUME_CSV)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is not None
    assert snap.short_sale_volume == pytest.approx(80000.0)
    assert snap.total_volume == pytest.approx(800000.0)
    assert snap.short_volume_ratio == pytest.approx(10.0)


async def test_hkex_unrecognized_columns_returns_none():
    src = HkexShortSellingSource()
    src.url = "http://fake/hkex.csv"
    src._http_get_text = AsyncMock(return_value=_HKEX_UNRECOGNIZED_CSV)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None


async def test_hkex_no_url_skips():
    src = HkexShortSellingSource()
    src.url = None
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None


# ─── SFC ─────────────────────────────────────────────────────────
_SFC_CSV = """Stock Code,Short Position (Shares)
00700,1500000
09988,800000
"""


async def test_sfc_parse_short_positions():
    src = SfcShortPositionsSource()
    src.url = "http://fake/sfc.csv"
    src._http_get_text = AsyncMock(return_value=_SFC_CSV)
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is not None
    assert snap.market == "HK"
    assert snap.short_interest_shares == pytest.approx(2300000.0)
    assert snap.short_volume_ratio is None  # 比率需流通股本补充，不编造


async def test_sfc_no_url_skips():
    src = SfcShortPositionsSource()
    src.url = None
    snap = await src.fetch(date(2026, 7, 27))
    assert snap is None


# ─── 编排器 ─────────────────────────────────────────────────────
class _FakeSource:
    def __init__(self, name, result):
        self.name = name
        self._result = result

    async def fetch(self, as_of):
        return self._result


async def test_orchestrator_us_success(monkeypatch, finra_volume_json):
    snap = MarketMarginSnapshot(market="US", as_of="2026-07-27")
    snap.short_sale_volume = 3000.0
    snap.total_volume = 10000.0
    snap.short_volume_ratio = 30.0
    monkeypatch.setattr(
        "backend.services.margin.sources.base._US_SOURCES",
        [_FakeSource("finra_reg_sho", snap)],
    )
    result = await get_market_margin_indicators("US", date(2026, 7, 27))
    assert result["short_sale_volume"] == pytest.approx(3000.0)
    assert result["market"] == "US"
    assert "finra_reg_sho" in result["sources"]


async def test_orchestrator_all_fail_returns_error(monkeypatch):
    monkeypatch.setattr(
        "backend.services.margin.sources.base._US_SOURCES",
        [_FakeSource("finra_reg_sho", None)],
    )
    result = await get_market_margin_indicators("US", date(2026, 7, 27))
    assert result["status"] == "error"
    assert "US" in result["market"]


async def test_orchestrator_unknown_market_returns_error():
    result = await get_market_margin_indicators("XX", date(2026, 7, 27))
    assert result["status"] == "error"


async def test_orchestrator_cache_hit(monkeypatch):
    cached = {
        "market": "US",
        "as_of": "2026-07-27",
        "short_sale_volume": 999.0,
        "sources": ["cached"],
    }
    fake_rc = AsyncMock()
    fake_rc.get = AsyncMock(return_value=json.dumps(cached))
    monkeypatch.setattr("backend.services.margin.sources.base.redis_client", fake_rc)
    result = await get_market_margin_indicators("US", date(2026, 7, 27))
    assert result["short_sale_volume"] == pytest.approx(999.0)
    fake_rc.get.assert_awaited()


# ─── 消费封装 ───────────────────────────────────────────────────
async def test_get_us_share_margin_success(monkeypatch, finra_volume_json):
    snap = MarketMarginSnapshot(market="US", as_of="2026-07-27")
    snap.short_sale_volume = 3000.0
    snap.total_volume = 10000.0
    snap.short_volume_ratio = 30.0
    monkeypatch.setattr(
        "backend.services.margin.sources.base._US_SOURCES",
        [_FakeSource("finra_reg_sho", snap)],
    )
    resp = await get_us_share_margin()
    assert resp["status"] == "success"
    assert resp["data"]["market"] == "US_SHARE"
    assert resp["data"]["short_sale_volume"] == pytest.approx(3000.0)


async def test_get_us_share_margin_error_envelope(monkeypatch):
    monkeypatch.setattr(
        "backend.services.margin.sources.base._US_SOURCES",
        [_FakeSource("finra_reg_sho", None)],
    )
    resp = await get_us_share_margin()
    assert resp["status"] == "error"
    assert resp["data"] is None


async def test_get_hk_share_margin_no_source_returns_error(monkeypatch):
    # HK 源未配置 URL → 全部返回 None → error 信封（绝不返回编造数字）
    monkeypatch.setattr(
        "backend.services.margin.sources.base._HK_SOURCES",
        [
            _FakeSource("hkex_short_selling", None),
            _FakeSource("sfc_short_positions", None),
        ],
    )
    resp = await get_hk_share_margin()
    assert resp["status"] == "error"
    assert resp["data"] is None
