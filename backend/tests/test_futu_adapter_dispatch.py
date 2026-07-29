"""
FUTU-05: FutuAdapter 分发与处理器单测（补齐 history/fund_flow/option_chain 分支）
==============================================================================

复用 _connected_adapter 模式，用 MagicMock 上下文覆盖各 action 的处理路径与错误分支。
"""

from unittest.mock import MagicMock

import pandas as pd
from futu import RET_OK

from backend.adapters.futu.futu_adapter import FutuAdapter


def _connected_adapter(ctx):
    a = FutuAdapter(ctx=ctx)
    a._connected = True
    return a


class TestFetchHistory:
    def test_success(self):
        ctx = MagicMock()
        ctx.is_connected = True
        df = pd.DataFrame(
            {
                "time_key": ["2024-01-01", "2024-01-02"],
                "open": [1.0, 2.0],
                "high": [1.5, 2.5],
                "low": [0.5, 1.5],
                "close": [1.2, 2.2],
                "volume": [100.0, 200.0],
                "turnover": [10.0, 20.0],
            }
        )
        ctx.get_cur_kline.return_value = (RET_OK, df)
        a = _connected_adapter(ctx)
        res = a.fetch("history", {"ticker": "HK.00700", "num": 2})
        assert res.status == "success"
        assert len(res.data) == 2

    def test_missing_ticker(self):
        a = _connected_adapter(MagicMock())
        res = a.fetch("history", {})
        assert res.status == "error"

    def test_ctx_none(self):
        a = _connected_adapter(MagicMock())
        a._ctx = None
        res = a.fetch("history", {"ticker": "HK.00700"})
        assert res.status == "error"

    def test_failure(self):
        ctx = MagicMock()
        ctx.is_connected = True
        ctx.get_cur_kline.return_value = (1, "err")  # 非 RET_OK
        a = _connected_adapter(ctx)
        res = a.fetch("history", {"ticker": "HK.00700"})
        assert res.status == "error"


class TestFetchFundFlow:
    def test_success(self):
        ctx = MagicMock()
        ctx.is_connected = True
        df = pd.DataFrame(
            {
                "main_in_flow": [1.0],
                "in_flow": [2.0],
                "super_in_flow": [0.5],
                "big_in_flow": [0.3],
                "mid_in_flow": [0.2],
                "sml_in_flow": [0.1],
                "last_valid_time": ["2024-01-01"],
            }
        )
        ctx.get_capital_flow.return_value = (RET_OK, df)
        a = _connected_adapter(ctx)
        res = a.fetch("fund_flow", {"ticker": "HK.00700"})
        assert res.status == "success"
        assert res.data["main_in_flow"] == 1.0

    def test_missing_ticker(self):
        a = _connected_adapter(MagicMock())
        res = a.fetch("fund_flow", {})
        assert res.status == "error"

    def test_failure(self):
        ctx = MagicMock()
        ctx.is_connected = True
        ctx.get_capital_flow.return_value = (1, "err")
        a = _connected_adapter(ctx)
        res = a.fetch("fund_flow", {"ticker": "HK.00700"})
        assert res.status == "error"


class TestFetchOptionChain:
    def test_success(self):
        ctx = MagicMock()
        ctx.is_connected = True
        ctx.get_option_expiration_date.return_value = (
            RET_OK,
            pd.DataFrame({"strike_time": ["2024-01-19 00:00:00"]}),
        )
        chain = pd.DataFrame(
            {
                "strike_price": [100.0],
                "option_type": ["CALL"],
                "implied_volatility": [0.2],
                "option_code": ["HK1000"],
                "last_price": [1.0],
                "volume": [10.0],
                "open_interest": [5.0],
            }
        )
        ctx.get_option_chain.return_value = (RET_OK, chain)
        a = _connected_adapter(ctx)
        res = a.fetch("option_chain", {"underlying_ticker": "HK.00700"})
        assert res.status == "success"
        assert len(res.data["options"]) == 1

    def test_missing_underlying(self):
        a = _connected_adapter(MagicMock())
        res = a.fetch("option_chain", {})
        assert res.status == "error"

    def test_not_connected(self):
        ctx = MagicMock()
        ctx.is_connected = False
        a = _connected_adapter(ctx)
        res = a.fetch("option_chain", {"underlying_ticker": "HK.00700"})
        assert res.status == "error"


def test_unknown_action():
    a = _connected_adapter(MagicMock())
    res = a.fetch("bogus", {})
    assert res.status == "error"
