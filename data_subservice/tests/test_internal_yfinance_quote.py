"""YFinance quote.py 单元测试 (纯函数 _normalize_option_row / fetch_bulk_quotes / mock yfinance 错误分支)"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_subservice._internal.yfinance import quote as qmod


class TestNormalizeOptionRow:
    def test_full_row(self):
        row = pd.Series(
            {
                "strike": 100.0,
                "bid": 2.5,
                "ask": 3.0,
                "lastPrice": 2.8,
                "volume": 1500,
                "openInterest": 4000,
                "impliedVolatility": 0.35,
            }
        )
        out = qmod._normalize_option_row(row, "call", "2026-09-18")
        assert out["strike"] == 100.0
        assert out["bid"] == 2.5
        assert out["option_type"] == "CALL"
        assert out["implied_volatility"] == 0.35
        assert out["expiration"] == "2026-09-18"

    def test_nan_values_become_none(self):
        row = pd.Series(
            {
                "strike": float("nan"),
                "bid": None,
                "ask": "x",
                "lastPrice": float("nan"),
                "volume": float("nan"),
                "openInterest": float("nan"),
                "impliedVolatility": float("nan"),
            }
        )
        out = qmod._normalize_option_row(row, "put")
        assert out["strike"] is None
        assert out["bid"] is None
        assert out["ask"] is None
        assert out["implied_volatility"] is None

    def test_put_upper(self):
        row = pd.Series({"strike": 50.0})
        out = qmod._normalize_option_row(row, "put")
        assert out["option_type"] == "PUT"


class TestFetchBulkQuotes:
    def test_bulk(self):
        with patch.object(qmod, "fetch_quote", side_effect=lambda t: {"symbol": t, "price": 1.0}) as m:
            out = qmod.fetch_bulk_quotes(["AAPL", "MSFT"])
        assert len(out) == 2
        assert out[0]["symbol"] == "AAPL"

    def test_bulk_empty(self):
        assert qmod.fetch_bulk_quotes([]) == []


class TestFetchQuoteMocked:
    def test_quote_success(self):
        fake_info = MagicMock()
        fake_info.last_price = 150.0
        fake_info.previous_close = 140.0
        fake_info.currency = "USD"
        fake_info.timezone = "America/New_York"
        fake_ticker = MagicMock()
        fake_ticker.fast_info = fake_info
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_quote("AAPL")
        assert result["price"] == 150.0
        assert result["change_pct"] > 0

    def test_quote_exception(self):
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", side_effect=Exception("net err")):
            result = qmod.fetch_quote("AAPL")
        assert "error" in result


class TestFetchFundFlowMocked:
    def test_flow_success(self):
        df = pd.DataFrame({"holder": ["Vanguard"], "pctHeld": [0.05]})
        fake_ticker = MagicMock()
        fake_ticker.get_institutional_holders.return_value = df
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_fund_flow("AAPL")
        assert len(result["institutional_holders"]) == 1

    def test_flow_empty(self):
        fake_ticker = MagicMock()
        fake_ticker.get_institutional_holders.return_value = None
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_fund_flow("AAPL")
        assert result["institutional_holders"] == []

    def test_flow_exception(self):
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", side_effect=Exception("e")):
            result = qmod.fetch_fund_flow("AAPL")
        assert "error" in result


class TestFetchFinancialsMocked:
    def test_financials_success(self):
        df = pd.DataFrame({"2024": [1, 2], "2025": [3, 4]})
        fake_ticker = MagicMock()
        fake_ticker.income_stmt = df
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_financials("AAPL")
        assert len(result["financials"]) <= 4

    def test_financials_quarterly(self):
        df = pd.DataFrame({"2026Q1": [1]})
        fake_ticker = MagicMock()
        fake_ticker.quarterly_income_stmt = df
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_financials("AAPL", kind="quarterly")
        assert result["kind"] == "quarterly"

    def test_financials_empty(self):
        fake_ticker = MagicMock()
        fake_ticker.income_stmt = None
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_financials("AAPL")
        assert result["financials"] == []

    def test_financials_exception(self):
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", side_effect=Exception("e")):
            result = qmod.fetch_financials("AAPL")
        assert "error" in result


class TestFetchHistoryMocked:
    def test_history_success_multindex_columns(self):
        df = pd.DataFrame({("Close", "AAPL"): [105.0], ("Open", "AAPL"): [100.0]})
        df.columns = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Open", "AAPL")])
        df["Date"] = ["2026-01-01"]
        with patch("data_subservice._internal.yfinance.quote.yf.download", return_value=df):
            out = qmod.fetch_history("AAPL", period="1mo")
        assert not out.empty
        assert "Close" in out.columns
        assert out.iloc[0]["Close"] == 105.0

    def test_history_empty(self):
        with patch("data_subservice._internal.yfinance.quote.yf.download", return_value=None):
            out = qmod.fetch_history("AAPL")
        assert out is None or (hasattr(out, "empty") and out.empty)

    def test_history_raises(self):
        with patch("data_subservice._internal.yfinance.quote.yf.download", side_effect=Exception("delisted")):
            with pytest.raises(Exception):
                qmod.fetch_history("BAD")


class TestFetchOptionChainMocked:
    def test_option_chain_success(self):
        calls_df = pd.DataFrame(
            [
                {
                    "strike": 100.0,
                    "bid": 2.0,
                    "ask": 3.0,
                    "lastPrice": 2.5,
                    "volume": 10,
                    "openInterest": 20,
                    "impliedVolatility": 0.3,
                },
            ]
        )
        puts_df = pd.DataFrame(
            [
                {
                    "strike": 90.0,
                    "bid": 1.0,
                    "ask": 1.5,
                    "lastPrice": 1.2,
                    "volume": 5,
                    "openInterest": 8,
                    "impliedVolatility": 0.25,
                },
            ]
        )
        fake_chain = MagicMock()
        fake_chain.calls = calls_df
        fake_chain.puts = puts_df
        fake_ticker = MagicMock()
        fake_ticker.option_chain.return_value = fake_chain
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", return_value=fake_ticker):
            result = qmod.fetch_option_chain("AAPL")
        assert result["count"] == 2
        assert len(result["calls"]) == 1
        assert len(result["puts"]) == 1
        assert result["calls"][0]["implied_volatility"] == 0.3

    def test_option_chain_exception(self):
        with patch("data_subservice._internal.yfinance.quote.yf.Ticker", side_effect=Exception("e")):
            result = qmod.fetch_option_chain("AAPL")
        assert "error" in result
