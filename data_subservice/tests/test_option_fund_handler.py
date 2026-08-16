"""Futu OptionFundHandler 单元测试 (期权/窝轮/资金/研报 分支覆盖)。

仅覆盖不依赖真实 OpenD 网络的前置校验分支 + 纯函数逻辑,
避免触发真实行情连接。
"""

import math
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data_subservice.futu_src import option_fund_handler as ofh
from data_subservice.futu_src.cache_manager import CacheManager
from futu import RET_OK


def _make_conn_mgr(connected: bool = False, host: str = "127.0.0.1"):
    conn_mgr = MagicMock()
    conn_mgr.connected = connected
    conn_mgr.futu_host = host
    conn_mgr.quote_ctx = MagicMock()
    conn_mgr.trd_ctx = MagicMock()
    return conn_mgr


# ── 纯函数: _is_option_code ───────────────────────────────────────────────

class TestIsOptionCode:
    @pytest.mark.parametrize("code,expected", [
        ("US.AAPL260918C150", True),
        ("US.AAPL260918P150", True),
        ("US.BABA241220C200", True),
        ("US.NVDA260115C1000", True),
        ("HK.00700", False),
        ("US.AAPL", False),
        ("US.AAPL260918X150", False),
        ("US.AAPL999999C150", False),
        ("", False),
        ("   ", False),
        ("US.AAPL260918C150 ", True),  # 末尾空格 strip
    ])
    def test_cases(self, code, expected):
        assert ofh._is_option_code(code) is expected


# ── 纯函数: _compress_warrant_data ────────────────────────────────────────

class TestCompressWarrantData:
    def test_empty_df(self):
        out = ofh._compress_warrant_data(pd.DataFrame())
        assert out == []

    def test_with_type_column(self):
        df = pd.DataFrame([
            {"code": "US.AAPL260918C150", "name": "AAPL 250918 150C", "type": "CALL",
             "strike_price": 150.0, "last_price": 5.2, "implied_volatility": 0.30,
             "delta": 0.5, "gamma": 0.02, "theta": -0.05, "vega": 0.1,
             "open_interest": 1000, "volume": 500, "last_trade_date": "2026-09-18",
             "expiry_date": "2026-09-18", "underlying": "AAPL"},
        ])
        out = ofh._compress_warrant_data(df)
        assert len(out) == 1
        rec = out[0]
        assert rec["code"] == "US.AAPL260918C150"
        assert rec["type"] == "CALL"
        assert rec["strike_price"] == 150.0
        assert rec["iv_pct"] == 30.0

    def test_missing_type_column(self):
        df = pd.DataFrame([{"code": "US.AAPL260918C150", "name": "X"}])
        out = ofh._compress_warrant_data(df)
        assert out[0]["type"] is None

    def test_nan_values(self):
        df = pd.DataFrame([{
            "code": "US.AAPL260918C150", "name": "X", "type": "PUT",
            "strike_price": float("nan"), "last_price": float("nan"),
            "implied_volatility": float("nan"), "delta": float("nan"),
        }])
        out = ofh._compress_warrant_data(df)
        assert math.isnan(out[0]["strike_price"])
        assert out[0]["iv_pct"] is None


# ── 纯函数: _mock_warrant_chain ───────────────────────────────────────────

class TestMockWarrantChain:
    def test_returns_structure(self):
        chain = ofh._mock_warrant_chain("US.AAPL")
        assert chain["code"] == "US.AAPL"
        assert "chain" in chain
        assert isinstance(chain["chain"], list)
        assert len(chain["chain"]) > 0
        for c in chain["chain"]:
            assert "strike" in c and "type" in c


# ── get_option_strategy ───────────────────────────────────────────────────

class TestGetOptionStrategy:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_option_strategy(conn, CacheManager(), "US.AAPL",
                                      strategy="BUTTERFLY", spread="MID")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_option_strategy(conn, CacheManager(), "US.AAPL",
                                      strategy="BUTTERFLY", spread="MID")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_unsupported_code(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_option_strategy(conn, CacheManager(), "BABA",
                                      strategy="BUTTERFLY", spread="MID")
        assert res["error_code"] == "UNSUPPORTED_SECURITY"

    def test_missing_spread(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_option_strategy(conn, CacheManager(), "US.AAPL",
                                      strategy="BUTTERFLY", spread=None)
        assert res["error_code"] == "INVALID_PARAM"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        cache = CacheManager()
        res = ofh.get_option_strategy(conn, cache, "US.AAPL",
                                      strategy="BUTTERFLY", spread="MID")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert res["data"]["code"] == "US.AAPL"

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_option_chain_ex = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_option_strategy(conn, CacheManager(), "US.AAPL",
                                      strategy="BUTTERFLY", spread="MID")
        assert res["error_code"] == "INTERNAL_ERROR"


# ── get_option_volatility ─────────────────────────────────────────────────

class TestGetOptionVolatility:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_option_volatility(conn, CacheManager(), "US.AAPL260918C150")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_option_volatility(conn, CacheManager(), "US.AAPL260918C150")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_invalid_code(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_option_volatility(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "INVALID_PARAM"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_option_volatility(conn, CacheManager(), "US.AAPL260918C150")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert "data" in res

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_option_expiration_date = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_option_volatility(conn, CacheManager(), "US.AAPL260918C150")
        assert res["error_code"] == "INTERNAL_ERROR"


# ── get_capital_distribution ──────────────────────────────────────────────

class TestGetCapitalDistribution:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_capital_distribution(conn, CacheManager(), "HK.00700")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_capital_distribution(conn, CacheManager(), "HK.00700")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_capital_distribution(conn, CacheManager(), "HK.00700")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert "data" in res

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_capital_distribution = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_capital_distribution(conn, CacheManager(), "HK.00700")
        assert res["error_code"] == "INTERNAL_ERROR"


# ── get_research_analyst_consensus ────────────────────────────────────────

class TestGetResearchAnalystConsensus:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_research_analyst_consensus(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_research_analyst_consensus(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_research_analyst_consensus(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert "data" in res

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_references = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_research_analyst_consensus(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "INTERNAL_ERROR"


# ── get_fundamental ───────────────────────────────────────────────────────

class TestGetFundamental:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_fundamental(conn, CacheManager(), "US.AAPL",
                                  field_type="BASIC")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_fundamental(conn, CacheManager(), "US.AAPL",
                                  field_type="BASIC")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_fundamental(conn, CacheManager(), "US.AAPL",
                                  field_type="BASIC")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert "data" in res

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_stock_basicinfo = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_fundamental(conn, CacheManager(), "US.AAPL",
                                  field_type="BASIC")
        assert res["error_code"] == "INTERNAL_ERROR"


# ── get_warrant_chain ─────────────────────────────────────────────────────

class TestGetWarrantChain:
    def test_not_connected(self):
        conn = _make_conn_mgr(connected=False)
        res = ofh.get_warrant_chain(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "NOT_CONNECTED"

    def test_not_initialized(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx = None
        res = ofh.get_warrant_chain(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "NOT_INITIALIZED"

    def test_success(self):
        conn = _make_conn_mgr(connected=True)
        res = ofh.get_warrant_chain(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] is None or res["error_code"] == "OK"
        assert res["data"]["code"] == "US.AAPL"

    def test_exception(self):
        conn = _make_conn_mgr(connected=True)
        conn.quote_ctx.get_warrant = AsyncMock(side_effect=RuntimeError("boom"))
        res = ofh.get_warrant_chain(conn, CacheManager(), "US.AAPL")
        assert res["error_code"] == "INTERNAL_ERROR"
