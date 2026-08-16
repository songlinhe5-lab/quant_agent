"""Futu OptionFundHandler 单元测试 (期权/窝轮/资金/研报 分支覆盖)。

仅覆盖不依赖真实 OpenD 网络的前置校验分支 + 纯函数逻辑,
避免触发真实行情连接。以真实 OptionFundHandler 接口为准。
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from futu import RET_OK

from data_subservice.futu_src.cache_manager import CacheManager
from data_subservice.futu_src.option_fund_handler import OptionFundHandler


def _make_conn_mgr(status: str = "CONNECTED", quote_ctx: MagicMock | None = None):
    conn_mgr = MagicMock()
    conn_mgr.status = status
    conn_mgr.quote_ctx = quote_ctx
    return conn_mgr


def _handler(status="CONNECTED", quote_ctx=None):
    return OptionFundHandler(_make_conn_mgr(status, quote_ctx), CacheManager())


# ── 纯函数: _is_option_code ───────────────────────────────────────────────
class TestIsOptionCode:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("US.AAPL260918C150", True),
            ("US.AAPL260918P150", True),
            ("US.BABA241220C200", True),
            ("US.NVDA260115C1000", True),
            ("HK.00700", False),
            ("US.AAPL", False),
            ("US.AAPL260918X150", False),
            ("US.AAPL999999C150", True),  # 含 6位数字+C/P+数字 子串
            ("", False),
            ("   ", False),
            ("US.AAPL260918C150 ", True),  # 子串匹配, 尾空格不影响
        ],
    )
    def test_cases(self, code, expected):
        assert OptionFundHandler._is_option_code(code) is expected


# ── 纯函数: _compress_warrant_data ────────────────────────────────────────
class TestCompressWarrantData:
    def test_empty_df(self):
        out = OptionFundHandler(MagicMock(), MagicMock())._compress_warrant_data(pd.DataFrame(), "HK.00700", 0)
        assert out["status"] == "success"
        assert out["warrants"] == []
        assert out["sentiment_summary"]["call_count"] == 0

    def test_with_type_column(self):
        df = pd.DataFrame(
            [
                {
                    "stock": "HK.19001",
                    "name": "CALL W",
                    "type": "CALL",
                    "issuer": "MB",
                    "strike_price": 40.0,
                    "cur_price": 0.15,
                    "premium": 12.5,
                    "leverage": 8.2,
                    "delta": 0.45,
                    "implied_volatility": 42.0,
                    "turnover": 3_000_000.0,
                    "volume": 20_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 15.0,
                    "recovery_price": 0,
                },
                {
                    "stock": "HK.19002",
                    "name": "PUT W",
                    "type": "PUT",
                    "issuer": "SG",
                    "strike_price": 35.0,
                    "cur_price": 0.08,
                    "premium": 8.3,
                    "leverage": 6.5,
                    "delta": -0.35,
                    "implied_volatility": 38.0,
                    "turnover": 2_000_000.0,
                    "volume": 15_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 8.0,
                    "recovery_price": 0,
                },
                {
                    "stock": "HK.19003",
                    "name": "BULL W",
                    "type": "BULL",
                    "issuer": "MB",
                    "strike_price": 1.0,
                    "cur_price": 0.1,
                    "premium": 1.0,
                    "leverage": 5.0,
                    "delta": 1.0,
                    "implied_volatility": 10.0,
                    "turnover": 1_000_000.0,
                    "volume": 1_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 1.0,
                    "recovery_price": 0,
                },
                {
                    "stock": "HK.19004",
                    "name": "BEAR W",
                    "type": "BEAR",
                    "issuer": "SG",
                    "strike_price": 1.0,
                    "cur_price": 0.1,
                    "premium": 1.0,
                    "leverage": 5.0,
                    "delta": -1.0,
                    "implied_volatility": 10.0,
                    "turnover": 1_000_000.0,
                    "volume": 1_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 1.0,
                    "recovery_price": 0,
                },
            ]
        )
        out = OptionFundHandler(MagicMock(), MagicMock())._compress_warrant_data(df, "HK.00700", 4)
        assert out["status"] == "success"
        assert len(out["warrants"]) == 4
        ss = out["sentiment_summary"]
        assert ss["call_count"] == 1
        assert ss["put_count"] == 1
        assert ss["bull_count"] == 1
        assert ss["bear_count"] == 1
        assert ss["call_ratio_pct"] == 50.0
        assert ss["sentiment"] == "中性"
        # 偏多场景
        df2 = pd.DataFrame(
            [
                {
                    "stock": "x",
                    "name": "c",
                    "type": "CALL",
                    "issuer": "",
                    "strike_price": 1.0,
                    "cur_price": 1.0,
                    "premium": 1.0,
                    "leverage": 1.0,
                    "delta": 1.0,
                    "implied_volatility": 1.0,
                    "turnover": 1.0,
                    "volume": 1,
                    "maturity_time": "x",
                    "street_rate": 1.0,
                    "recovery_price": 0,
                },
                {
                    "stock": "y",
                    "name": "b",
                    "type": "BULL",
                    "issuer": "",
                    "strike_price": 1.0,
                    "cur_price": 1.0,
                    "premium": 1.0,
                    "leverage": 1.0,
                    "delta": 1.0,
                    "implied_volatility": 1.0,
                    "turnover": 1.0,
                    "volume": 1,
                    "maturity_time": "x",
                    "street_rate": 1.0,
                    "recovery_price": 0,
                },
            ]
        )
        out2 = OptionFundHandler(MagicMock(), MagicMock())._compress_warrant_data(df2, "HK.00700", 2)
        assert out2["sentiment_summary"]["sentiment"] == "偏多"

    def test_missing_type_column(self):
        df = pd.DataFrame([{"stock": "HK.19001", "name": "X"}])
        out = OptionFundHandler(MagicMock(), MagicMock())._compress_warrant_data(df, "HK.00700", 1)
        assert out["warrants"][0]["type"] == ""

    def test_nan_values(self):
        df = pd.DataFrame(
            [
                {
                    "stock": "HK.19001",
                    "name": "X",
                    "type": "PUT",
                    "strike_price": float("nan"),
                    "cur_price": float("nan"),
                    "implied_volatility": float("nan"),
                    "delta": float("nan"),
                }
            ]
        )
        out = OptionFundHandler(MagicMock(), MagicMock())._compress_warrant_data(df, "HK.00700", 1)
        assert pd.isna(out["warrants"][0]["strike_price"])
        assert pd.isna(out["warrants"][0]["implied_volatility"])


# ── 纯函数: _mock_warrant_chain ───────────────────────────────────────────
class TestMockWarrantChain:
    def test_returns_structure(self):
        chain = OptionFundHandler(MagicMock(), MagicMock())._mock_warrant_chain("HK.00700")
        assert chain["status"] == "success"
        assert chain["ticker"] == "HK.00700"
        assert "warrants" in chain
        assert isinstance(chain["warrants"], list)
        assert len(chain["warrants"]) > 0
        assert "sentiment_summary" in chain
        for c in chain["warrants"]:
            assert "type" in c and "strike_price" in c


# ── get_option_strategy ───────────────────────────────────────────────────
class TestGetOptionStrategy:
    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_option_strategy("US.AAPL")
        assert res["status"] == "error"
        assert "未连接" in res["message"]

    async def test_not_connected(self):
        conn = _make_conn_mgr(status="DISCONNECTED", quote_ctx=MagicMock())
        res = await OptionFundHandler(conn, CacheManager()).get_option_strategy("US.AAPL")
        assert res["status"] == "error"
        assert "重连中" in res["message"]

    async def test_option_code_rejected(self):
        conn = _make_conn_mgr()
        res = await OptionFundHandler(conn, CacheManager()).get_option_strategy("US.AAPL260918C150")
        assert res["status"] == "error"
        assert "正股/ETF/指数" in res["message"]

    async def test_success(self):
        qctx = MagicMock()
        qctx.get_option_strategy = lambda *a, **k: (
            RET_OK,
            pd.DataFrame([{"strike_price": 150.0, "option_type": "CALL", "net_open_interest": 100}]),
        )
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_option_strategy(
            "US.AAPL", strategy_type="STRANGLE", spread=5
        )
        assert res["status"] == "success"
        assert res["code"] == "US.AAPL"
        assert res["count"] == 1

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_option_strategy = lambda *a, **k: (1, "err")
        # 真实调用时 quote_ctx.get_option_strategy 返回 (RET_OK,df) 由 asyncio.to_thread 执行
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_option_strategy(
            "US.AAPL", strategy_type="STRANGLE", spread=5
        )
        assert res["status"] == "error"


# ── get_option_volatility ─────────────────────────────────────────────────
class TestGetOptionVolatility:
    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_option_volatility("US.AAPL260918C150")
        assert res["status"] == "error"
        assert "未连接" in res["message"]

    async def test_not_connected(self):
        conn = _make_conn_mgr(status="DISCONNECTED", quote_ctx=MagicMock())
        res = await OptionFundHandler(conn, CacheManager()).get_option_volatility("US.AAPL260918C150")
        assert res["status"] == "error"
        assert "重连中" in res["message"]

    async def test_stock_code_rejected(self):
        conn = _make_conn_mgr()
        res = await OptionFundHandler(conn, CacheManager()).get_option_volatility("US.AAPL")
        assert res["status"] == "error"
        assert "期权合约代码" in res["message"]

    async def test_success(self):
        qctx = MagicMock()
        qctx.get_option_volatility = lambda *a, **k: (RET_OK, pd.DataFrame([{"implied_volatility": 0.3}]))
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_option_volatility("US.AAPL260918C150")
        assert res["status"] == "success"
        assert "data" in res

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_option_volatility = lambda *a, **k: (1, "err")
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_option_volatility("US.AAPL260918C150")
        assert res["status"] == "error"


# ── get_capital_distribution ──────────────────────────────────────────────
class TestGetCapitalDistribution:
    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_capital_distribution("HK.00700")
        assert res["status"] == "error"

    async def test_not_connected(self):
        conn = _make_conn_mgr(status="DISCONNECTED", quote_ctx=MagicMock())
        res = await OptionFundHandler(conn, CacheManager()).get_capital_distribution("HK.00700")
        assert res["status"] == "error"

    async def test_success(self):
        qctx = MagicMock()
        qctx.get_capital_distribution = lambda *a, **k: (
            RET_OK,
            pd.DataFrame(
                [
                    {
                        "capital_in_super": 100.0,
                        "capital_out_super": 20.0,
                        "capital_in_big": 50.0,
                        "capital_out_big": 10.0,
                        "capital_in_mid": 5.0,
                        "capital_out_mid": 5.0,
                        "capital_in_small": 1.0,
                        "capital_out_small": 1.0,
                        "update_time": "2026-01-01",
                    }
                ]
            ),
        )
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_capital_distribution("HK.00700")
        assert res["status"] == "success"
        assert "layers" in res
        assert res["main_net"] == (100 - 20) + (50 - 10)
        assert res["divergence"] in ("main_in_retail_out", "main_out_retail_in", "aligned")

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_capital_distribution = lambda *a, **k: (1, "err")
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_capital_distribution("HK.00700")
        assert res["status"] == "error"


# ── get_research_analyst_consensus ────────────────────────────────────────
class TestGetResearchAnalystConsensus:
    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_research_analyst_consensus("US.AAPL")
        assert res["status"] == "error"

    async def test_not_connected(self):
        conn = _make_conn_mgr(status="DISCONNECTED", quote_ctx=MagicMock())
        res = await OptionFundHandler(conn, CacheManager()).get_research_analyst_consensus("US.AAPL")
        assert res["status"] == "error"

    async def test_success(self):
        qctx = MagicMock()
        qctx.get_research_analyst_consensus = lambda *a, **k: (
            RET_OK,
            pd.DataFrame([{"rating": "BUY", "target_price": 200.0}]),
        )
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_research_analyst_consensus("US.AAPL")
        assert res["status"] == "success"
        assert res["source"] == "futu_consensus"
        assert res["is_third_party_expectation"] is True

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_research_analyst_consensus = lambda *a, **k: (1, "err")
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_research_analyst_consensus("US.AAPL")
        assert res["status"] == "error"


# ── get_fundamental ───────────────────────────────────────────────────────
class TestGetFundamental:
    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_fundamental("US.AAPL")
        assert res["status"] == "error"

    async def test_success(self):
        qctx = MagicMock()
        qctx.get_market_snapshot = lambda *a, **k: (
            RET_OK,
            pd.DataFrame(
                [{"name": "Apple", "pe_ratio": 30.0, "pb_rate": 40.0, "dividend_yield": 0.5, "market_val": 3e12}]
            ),
        )
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_fundamental("US.AAPL")
        assert res["status"] == "success"
        assert res["data"]["company_name"] == "Apple"
        assert res["data"]["trailing_PE"] == 30.0

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_market_snapshot = lambda *a, **k: (1, "err")
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_fundamental("US.AAPL")
        assert res["status"] == "error"


# ── get_warrant_chain ─────────────────────────────────────────────────────
class TestGetWarrantChain:
    async def test_not_hk(self):
        conn = _make_conn_mgr()
        res = await OptionFundHandler(conn, CacheManager()).get_warrant_chain("US.AAPL")
        assert res["status"] == "error"
        assert "仅支持港股" in res["message"]

    async def test_not_initialized(self):
        conn = _make_conn_mgr(quote_ctx=None)
        res = await OptionFundHandler(conn, CacheManager()).get_warrant_chain("HK.00700")
        assert res["status"] == "error"

    async def test_success(self):
        qctx = MagicMock()
        df = pd.DataFrame(
            [
                {
                    "stock": "HK.19001",
                    "name": "W",
                    "type": "CALL",
                    "issuer": "MB",
                    "strike_price": 40.0,
                    "cur_price": 0.15,
                    "premium": 12.5,
                    "leverage": 8.2,
                    "delta": 0.45,
                    "implied_volatility": 42.0,
                    "turnover": 3_000_000.0,
                    "volume": 20_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 15.0,
                    "recovery_price": 0,
                }
            ]
        )
        qctx.get_warrant = lambda *a, **k: (RET_OK, (df, False, 1))
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_warrant_chain("HK.00700")
        assert res["status"] == "success"
        assert len(res["warrants"]) == 1

    async def test_failure(self):
        qctx = MagicMock()
        qctx.get_warrant = lambda *a, **k: (1, "err")
        conn = _make_conn_mgr(quote_ctx=qctx)
        res = await OptionFundHandler(conn, CacheManager()).get_warrant_chain("HK.00700")
        assert res["status"] == "error"
