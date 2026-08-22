"""
P0.5 期权全维数据 business 层聚合单元测试
验证 OptionDataService 的 8 个新方法正确 dispatch 到对应 action，
以及 get_option_put_call_panel 的产品级聚合（latest/avg_5d/signal）。
全程 mock facade，不触碰真实 Redis/Futu/外网。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.datasource.business.option import OptionDataService


def _result(data, is_error=False):
    r = MagicMock()
    r.is_error = is_error
    r.data = data
    r.source = "mock"
    r.status = "SUCCESS" if not is_error else "ERROR"
    return r


@pytest.fixture
def svc():
    return OptionDataService(facade=MagicMock())


async def test_underlying_his_vol_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    out = await svc.get_option_underlying_his_volatility("US.AAPL")
    assert out.data == {"data": []}
    svc._facade._dispatch.assert_awaited_once()
    args = svc._facade._dispatch.call_args.args
    assert args[0] == "OPTION_UNDERLYING_HIS_VOL"


async def test_underlying_overview_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_underlying_overview("US.AAPL")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_UNDERLYING_OVERVIEW"


async def test_market_statistic_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_market_statistic("US_SECURITY", "VOLUME")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_MARKET_STATISTIC"


async def test_zero_dte_screener_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_zero_dte_screener("US_SECURITY")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_ZERO_DTE_SCREENER"


async def test_zero_dte_contract_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_zero_dte_contract("US.QQQ", {"product_code": "QQQ"})
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_ZERO_DTE_CONTRACT"


async def test_earnings_screener_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_earnings_screener("US_SECURITY")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_EARNINGS_SCREENER"


async def test_seller_screener_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_seller_screener("US_SECURITY", "COVERED_CALL")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_SELLER_SCREENER"


async def test_exercise_probability_dispatches(svc):
    svc._facade._dispatch = AsyncMock(return_value=_result({"data": []}))
    await svc.get_option_exercise_probability("US.AAPL260824C205000")
    assert svc._facade._dispatch.call_args.args[0] == "OPTION_EXERCISE_PROBABILITY"


async def test_put_call_panel_derives_signal(svc):
    """P0.5.3 Put/Call 面板聚合：latest/avg_5d/signal 派生"""
    data = {
        "data": [
            {"time": "d1", "put_call_ratio": 0.62},
            {"time": "d2", "put_call_ratio": 0.65},
            {"time": "d3", "put_call_ratio": 0.68},
            {"time": "d4", "put_call_ratio": 0.60},
            {"time": "d5", "put_call_ratio": 0.63},
        ]
    }
    svc._facade._dispatch = AsyncMock(return_value=_result(data))
    out = await svc.get_option_put_call_panel("US_SECURITY", "VOLUME")
    panel = out.data["put_call_panel"]
    assert panel["available"] is True
    assert panel["latest"] == 0.63
    assert abs(panel["avg_5d"] - 0.636) < 1e-3
    assert panel["signal"] == "偏谨慎"  # 0.63 < 0.7
    assert out.data["put_call_panel"]["count"] == 5


async def test_put_call_panel_optimistic_signal(svc):
    """P/C 比 > 1.0 → 偏乐观"""
    data = {"data": [{"put_call_ratio": 1.2}, {"put_call_ratio": 1.1}]}
    svc._facade._dispatch = AsyncMock(return_value=_result(data))
    out = await svc.get_option_put_call_panel("US_SECURITY", "VOLUME")
    assert out.data["put_call_panel"]["signal"] == "偏乐观"


async def test_put_call_panel_empty_degrades(svc):
    """空数据 → available=False + note（零幻觉，不臆造）"""
    data = {"data": []}
    svc._facade._dispatch = AsyncMock(return_value=_result(data))
    out = await svc.get_option_put_call_panel("US_SECURITY", "VOLUME")
    assert out.data["put_call_panel"]["available"] is False
    assert "note" in out.data["put_call_panel"]


async def test_put_call_panel_error_passthrough(svc):
    """上游 error → 原样透传，不崩溃"""
    svc._facade._dispatch = AsyncMock(return_value=_result(None, is_error=True))
    out = await svc.get_option_put_call_panel("US_SECURITY", "VOLUME")
    assert out.is_error is True
