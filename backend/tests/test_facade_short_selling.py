"""
G2 卖空拥挤度（get_short_selling）单元测试。

覆盖 2026-08-30 S1 实战修复的三个缺陷（子服务实测 200 返回真实卖空榜，
故障全部在主服务 facade 侧）：

1. `_safe` 返回 (label, value)，旧代码 `fr, _ = futu_res` 取到的是标签字符串
   "futu"，`isinstance(fr, Result)` 恒 False → futu_payload 恒 None →
   接口恒定返回 ALL_SOURCES_FAILED。
2. `get_hk_share_margin()` 返回 dict（非元组），经 _safe 包装后为
   (label, payload)。旧代码解包成 (hk_status, hk_payload)，hk_status 实为标签
   "hkex"，与 "success" 永不相等 → HKEX/SFC 监管交叉验证被静默丢弃。
3. 派生指标读 short_sell_turnover / total_turnover——Futu 卖空榜真实列名为
   short_ratio（已是百分比成交占比）/ short_number / volume → ratios 恒空，
   所有派生指标恒 None。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.datasource import ErrorInfo, Result
from backend.services.datasource.business.facade import DataServiceFacade

# Futu 卖空榜真实返回行（data_subservice/futu_src/short_selling_handler.py 实测）
_ROW_A = {
    "security": "HK.03033",
    "name": "南方恒生科技",
    "close_price": 4.522,
    "volume": 1374700288.0,
    "short_number": 661753200.0,
    "short_ratio": 48.13,
    "short_position_ratio": 0.07,
}
_ROW_B = {
    "security": "HK.02800",
    "name": "盈富基金",
    "close_price": 26.12,
    "volume": 1069004005.0,
    "short_number": 693475000.0,
    "short_ratio": 64.87,
    "short_position_ratio": 0.14,
}

# daily 模式港美股**分表**，列名不同（futu 10.10 open_quote_context 实测）：
# us_df 自带 short_percent；hk_df 无该列，须自行计算占比
_US_DAILY_ROW = {
    "timestamp": 1787889600.0,
    "timestamp_str": "2026-08-28",
    "total_shares_short": 5328185.0,
    "nasdaq_shares_short": 3240483.0,
    "nyse_shares_short": 2087702.0,
    "short_percent": 13.785,  # 5328185 / 38649398 * 100
    "volume": 38649398.0,
    "close_price": 319.7,
    "last_close_price": 314.58,
    "daily_trade_avg_ratio": 11.74,
}
_HK_DAILY_ROW = {
    "timestamp": 1787976000.0,  # 比美股行晚一天，用于验证取最新一日
    "timestamp_str": "2026-08-29",
    "shares_traded": 1000000.0,
    "turnover": 50000000.0,
    "short_sell_shares_traded": 200000.0,
    "short_sell_turnover": 12000000.0,  # 12000000 / 50000000 * 100 = 24.0
    "close_price": 400.0,
    "last_close_price": 395.0,
    "daily_trade_avg_ratio": 1.2,
}

_HK_PAYLOAD = {
    "status": "success",
    "data": {
        "market": "HK_SHARE",
        "as_of": "2026-08-29",
        "short_volume_ratio": 20.0,
        "sources": ["HKEX"],
        "note": "市场级卖空占比",
    },
}


def _build_facade(futu_result, monkeypatch, hk_payload=_HK_PAYLOAD) -> DataServiceFacade:
    """构造替身 facade：_dispatch 与 HKEX 源全部打桩，不触网、不依赖 Redis/Futu。"""
    facade = DataServiceFacade()
    facade._dispatch = AsyncMock(return_value=futu_result)
    hk_share_module = __import__("backend.services.margin.hk_share", fromlist=["get_hk_share_margin"])
    monkeypatch.setattr(hk_share_module, "get_hk_share_margin", AsyncMock(return_value=hk_payload))
    return facade


def _futu_success(rows) -> Result:
    """Futu 子服务成功信封（rank / daily 两种模式的 data 都挂在 data 字段）。"""
    return Result.make_success(
        {"status": "success", "source": "futu", "ticker": "HK.00700", "count": len(rows), "data": rows},
        source="futu",
    )


@pytest.mark.asyncio
async def test_rank_unpacks_result_and_derives_median(monkeypatch):
    """回归核心：_safe 解包修复后能拿到 Result，且按真实列名 short_ratio 派生中位占比。"""
    facade = _build_facade(_futu_success([_ROW_A, _ROW_B]), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="rank")

    assert res.is_success, res.error.message if res.error else "未知错误"
    assert res.data["sources"]["futu"] == "ok"
    # median(48.13, 64.87) = 56.5
    assert res.data["derived"]["short_sale_ratio_median"] == pytest.approx(56.5)
    assert res.data["derived"]["rank_count"] == 2
    assert res.data["derived"]["crowding_level"] == "high"


@pytest.mark.asyncio
async def test_ratio_falls_back_to_short_number_over_volume(monkeypatch):
    """缺 short_ratio 时回退 short_number / volume，不再是恒 None。"""
    row = {"security": "HK.09988", "short_number": 250.0, "volume": 1000.0}
    facade = _build_facade(_futu_success([row]), monkeypatch)

    res = await facade.get_short_selling("HK.09988", mode="rank")

    assert res.data["derived"]["short_sale_ratio_median"] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_hkex_cross_validation_not_dropped(monkeypatch):
    """回归 HKEX 监管交叉验证：dict 形态 payload 须被识别，不再静默丢弃。"""
    facade = _build_facade(_futu_success([_ROW_A, _ROW_B]), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="rank")

    assert res.data["sources"]["hkex_sfc"] == "ok"
    assert res.data["regulatory"]["short_volume_ratio"] == pytest.approx(20.0)
    # (56.5 - 20) / 20 * 100 = 182.5 → 超出 30% 阈值，判不一致
    assert res.data["derived"]["cross_validation_deviation_pct"] == pytest.approx(182.5)
    assert res.data["derived"]["cross_validation_consistent"] is False


@pytest.mark.asyncio
async def test_daily_no_data_reported_as_no_data(monkeypatch):
    """T-1 红线：daily 0 行如实标 no_data，不输出卖空为 0。"""
    facade = _build_facade(
        Result.make_success(
            {"status": "no_data", "source": "futu", "count": 0, "data": [], "message": "当日卖空量尚未结算"},
            source="futu",
        ),
        monkeypatch,
    )

    res = await facade.get_short_selling("HK.00700", mode="daily")

    assert res.is_success
    assert res.data["sources"]["futu"] == "no_data"
    assert res.data["futu"]["status"] == "no_data"


@pytest.mark.asyncio
async def test_futu_failure_returns_all_sources_failed(monkeypatch):
    """Futu 源失败时如实报错，不假绿。"""
    facade = _build_facade(
        Result.make_error(ErrorInfo.normal("FUTU_DISCONNECTED", "OpenD 未连接", retryable=True), source="futu"),
        monkeypatch,
    )

    res = await facade.get_short_selling("HK.00700", mode="rank")

    assert res.is_error
    assert res.error.code == "ALL_SOURCES_FAILED"


@pytest.mark.asyncio
async def test_daily_us_uses_short_percent(monkeypatch):
    """daily 美股：us_df 自带 short_percent，直接采用。"""
    facade = _build_facade(_futu_success([_US_DAILY_ROW]), monkeypatch)

    res = await facade.get_short_selling("US.AAPL", mode="daily")

    assert res.data["derived"]["short_sale_ratio"] == pytest.approx(13.785)
    assert res.data["derived"]["as_of"] == "2026-08-28"
    assert res.data["derived"]["crowding_level"] == "mid"  # 13.785 < 15


@pytest.mark.asyncio
async def test_daily_hk_computes_ratio_from_turnover(monkeypatch):
    """daily 港股：hk_df 无 short_percent，按 short_sell_turnover / turnover 计算。"""
    facade = _build_facade(_futu_success([_HK_DAILY_ROW]), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="daily")

    assert res.data["derived"]["short_sale_ratio"] == pytest.approx(24.0)
    assert res.data["derived"]["crowding_level"] == "high"


@pytest.mark.asyncio
async def test_daily_hk_falls_back_to_shares(monkeypatch):
    """港股缺 turnover/amount 时回退股数口径：short_sell_shares_traded / shares_traded。"""
    row = dict(_HK_DAILY_ROW)
    row.pop("short_sell_turnover")
    row.pop("turnover")
    facade = _build_facade(_futu_success([row]), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="daily")

    assert res.data["derived"]["short_sale_ratio"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_daily_series_and_alert_message(monkeypatch):
    """daily 产出 T-1 序列；告警文案引用个股占比，不得触碰 rank 专属字段。"""
    facade = _build_facade(_futu_success([_US_DAILY_ROW, _HK_DAILY_ROW]), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="daily")
    derived = res.data["derived"]

    # 按 timestamp 取最新一日（不依赖返回顺序）
    assert derived["as_of"] == "2026-08-29"
    assert [s["ratio"] for s in derived["daily_series"]] == pytest.approx([13.785, 24.0])
    # crowding_level=high → 生成告警；旧实现取 short_sale_ratio_median 会 KeyError
    assert derived["alert_signal"]["type"] == "squeeze_candidate"


@pytest.mark.asyncio
async def test_rank_list_payload_after_envelope_unwrap(monkeypatch):
    """回归：FutuDataSource.fetch 循环剥离 {status,data} 信封后 res.data 是 list。

    旧实现对 list 调 .get("status") → AttributeError → 接口 500
    （2026-08-30 部署后实测：HK.00700/US.AAPL 的 rank 与 daily 全部 500）。
    """
    facade = _build_facade(Result.make_success([_ROW_A, _ROW_B], source="futu"), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="rank")

    assert res.is_success
    assert res.data["derived"]["short_sale_ratio_median"] == pytest.approx(56.5)


@pytest.mark.asyncio
async def test_daily_list_payload_derives_stock_ratio(monkeypatch):
    """daily + list 形态：个股占比按列名正确派生（生产实际路径）。"""
    facade = _build_facade(Result.make_success([_HK_DAILY_ROW], source="futu"), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="daily")

    assert res.data["derived"]["short_sale_ratio"] == pytest.approx(24.0)
    assert res.data["derived"]["as_of"] == "2026-08-29"


@pytest.mark.asyncio
async def test_empty_list_payload_reports_no_data(monkeypatch):
    """空 list（daily 0 行）如实标 no_data，不输出卖空为 0（T-1 红线）。"""
    facade = _build_facade(Result.make_success([], source="futu"), monkeypatch)

    res = await facade.get_short_selling("HK.00700", mode="daily")

    assert res.is_success
    assert res.data["sources"]["futu"] == "no_data"
    assert res.data["futu"]["status"] == "no_data"
