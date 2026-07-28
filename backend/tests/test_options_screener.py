"""TRADE-01: 期权筛选服务单元测试 (options_screener.py, 覆盖 28% → 全绿)"""

import pytest

from backend.services.screener.options_screener import OptionFilter, OptionsScreener


def _chain():
    """构造一条含 call/put 的期权链，IV 以小数给出 (0.25 = 25%)。"""
    return [
        {
            "strike": 100,
            "expiry": "2026-08-20",
            "option_type": "call",
            "bid": 3.0,
            "ask": 3.5,
            "volume": 5000,
            "open_interest": 12000,
            "days_to_expiry": 30,
            "iv": 0.25,
        },
        {
            "strike": 100,
            "expiry": "2026-08-20",
            "option_type": "put",
            "bid": 2.0,
            "ask": 2.4,
            "volume": 3000,
            "open_interest": 9000,
            "days_to_expiry": 30,
            "iv": 0.30,
        },
        {
            "strike": 110,
            "expiry": "2026-09-18",
            "option_type": "call",
            "bid": 1.0,
            "ask": 1.2,
            "volume": 200,
            "open_interest": 800,
            "days_to_expiry": 60,
            "iv": 0.40,
        },
    ]


@pytest.mark.asyncio
async def test_screen_options_type_and_expiry_filter():
    s = OptionsScreener()
    res = await s.screen_options(
        "AAPL", OptionFilter(ticker="AAPL", option_type="call", expiry="2026-08-20"), _chain(), spot_price=100
    )
    assert res["matched"] == 1
    assert res["options"][0]["option_type"] == "call"
    assert res["options"][0]["expiry"] == "2026-08-20"


@pytest.mark.asyncio
async def test_screen_options_delta_volume_oi_moneyness():
    s = OptionsScreener()
    res = await s.screen_options(
        "AAPL",
        OptionFilter(
            ticker="AAPL",
            option_type="both",
            delta_min=-1.0,  # 允许 put (delta 为负)
            min_volume=1000,
            min_open_interest=1000,
            moneyness_min=0.9,
            moneyness_max=1.1,
        ),
        _chain(),
        spot_price=100,
    )
    # strike=100 → moneyness=1.0 命中；strike=110 → moneyness=0.909 命中但 volume 仅 200 被过滤
    assert res["matched"] == 2
    for opt in res["options"]:
        assert opt["volume"] >= 1000
        assert 0.9 <= opt["moneyness"] <= 1.1


@pytest.mark.asyncio
async def test_screen_options_iv_rank_with_history():
    s = OptionsScreener()
    iv_history = [0.20, 0.22, 0.18, 0.25, 0.30]  # 当前 0.25 → rank 居中
    res = await s.screen_options(
        "AAPL",
        OptionFilter(ticker="AAPL", iv_rank_min=10, iv_rank_max=90),
        _chain(),
        spot_price=100,
        iv_history=iv_history,
    )
    for opt in res["options"]:
        assert opt["iv_rank"] is not None
        assert 10 <= opt["iv_rank"] <= 90


@pytest.mark.asyncio
async def test_screen_options_iv_rank_none_without_history():
    s = OptionsScreener()
    res = await s.screen_options("AAPL", OptionFilter(ticker="AAPL"), _chain(), spot_price=100)
    for opt in res["options"]:
        assert opt["iv_rank"] is None


@pytest.mark.asyncio
async def test_get_iv_rank_analysis_signal_paths():
    s = OptionsScreener()
    hi = await s.get_iv_rank_analysis("AAPL", current_iv=0.95, iv_history=[0.1, 0.2, 0.3, 0.4])
    assert hi["signal"] == "HIGH_IV_SELL"
    lo = await s.get_iv_rank_analysis("AAPL", current_iv=0.05, iv_history=[0.1, 0.2, 0.3, 0.4])
    assert lo["signal"] == "LOW_IV_BUY"
    mid = await s.get_iv_rank_analysis("AAPL", current_iv=0.28, iv_history=[0.1, 0.2, 0.3, 0.4])
    assert mid["signal"] in ("MODERATE_HIGH", "MODERATE_LOW")


@pytest.mark.asyncio
async def test_get_iv_rank_analysis_empty_history():
    s = OptionsScreener()
    res = await s.get_iv_rank_analysis("AAPL", current_iv=0.3, iv_history=[])
    assert res["iv_stats"]["avg"] == 0
    assert res["signal"] == "MODERATE_LOW"


@pytest.mark.asyncio
async def test_analyze_vol_smile():
    s = OptionsScreener()
    res = await s.analyze_vol_smile("AAPL", _chain(), spot_price=100)
    assert res["ticker"] == "AAPL"
    assert res["total_analyzed"] == 3
    assert "smile" in res and res["atm_iv"] >= 0


@pytest.mark.asyncio
async def test_analyze_vol_smile_empty():
    s = OptionsScreener()
    res = await s.analyze_vol_smile("AAPL", [], spot_price=100)
    assert res["smile"] == []
    assert res["atm_iv"] == 0
