"""YFinanceService 单元测试 (路由表 / _df_to_records / 错误分类 / 熔断入口)"""

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from data_subservice._internal.yfinance.service import YFinanceService


def _svc():
    return YFinanceService()


class TestIsDataUnavailable:
    def test_no_data_marker(self):
        assert YFinanceService._is_data_unavailable(Exception("Yahoo error = No data")) is True

    def test_not_found_marker(self):
        assert YFinanceService._is_data_unavailable(Exception("No data found")) is True

    def test_delisted_marker(self):
        assert YFinanceService._is_data_unavailable(Exception("delisted")) is True

    def test_generic_error_not_data_unavailable(self):
        assert YFinanceService._is_data_unavailable(Exception("connection reset")) is False


class TestDfToRecords:
    def test_empty_df(self):
        svc = _svc()
        assert svc._df_to_records(None) == []
        assert svc._df_to_records(pd.DataFrame()) == []

    def test_normal_df(self):
        svc = _svc()
        df = pd.DataFrame(
            {
                "Date": ["2026-01-01", "2026-01-02"],
                "Open": [100.0, 101.0],
                "High": [110.0, 111.0],
                "Low": [90.0, 91.0],
                "Close": [105.0, 106.0],
                "Volume": [1_000_000, 2_000_000],
            }
        )
        recs = svc._df_to_records(df)
        assert len(recs) == 2
        assert recs[0]["close"] == 105.0
        assert recs[0]["volume"] == 1_000_000

    def test_multindex_columns_flattened(self):
        svc = _svc()
        df = pd.DataFrame({("Close", "AAPL"): [105.0], ("Open", "AAPL"): [100.0]})
        df.columns = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Open", "AAPL")])
        df["Date"] = ["2026-01-01"]
        df["High"] = [110.0]
        df["Low"] = [90.0]
        df["Volume"] = [1_000_000]
        recs = svc._df_to_records(df)
        assert recs[0]["close"] == 105.0

    def test_nan_volume_becomes_zero(self):
        svc = _svc()
        df = pd.DataFrame(
            {
                "Date": ["2026-01-01"],
                "Open": [100.0],
                "High": [110.0],
                "Low": [90.0],
                "Close": [105.0],
                "Volume": [float("nan")],
            }
        )
        recs = svc._df_to_records(df)
        assert recs[0]["volume"] == 0


class TestFetchYfDataRouting:
    @pytest.mark.asyncio
    async def test_unknown_endpoint(self):
        svc = _svc()
        result = await svc.fetch_yf_data("bogus", "AAPL")
        assert result["error"] == "unknown endpoint: bogus"

    @pytest.mark.asyncio
    async def test_quote_route(self):
        svc = _svc()
        with patch.object(svc, "get_quote", new=AsyncMock(return_value={"symbol": "AAPL"})) as m:
            result = await svc.fetch_yf_data("QUOTE", "AAPL")
        m.assert_awaited_once_with("AAPL")
        assert result["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_history_route(self):
        svc = _svc()
        with patch.object(svc, "get_history", new=AsyncMock(return_value={"symbol": "AAPL"})) as m:
            result = await svc.fetch_yf_data("history", "AAPL", period="1mo")
        m.assert_awaited_once()
        assert result["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_flow_route(self):
        svc = _svc()
        with patch.object(svc, "get_fund_flow", new=AsyncMock(return_value={"ok": 1})) as m:
            await svc.fetch_yf_data("FLOW", "AAPL")
        m.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_option_chain_route(self):
        svc = _svc()
        with patch.object(svc, "get_option_chain", new=AsyncMock(return_value={"ok": 1})) as m:
            await svc.fetch_yf_data("option_chain", "AAPL")
        m.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_route(self):
        svc = _svc()
        with patch.object(svc, "search", new=AsyncMock(return_value=[{"s": "AAPL"}])) as m:
            await svc.fetch_yf_data("search", "apple")
        m.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_technical_route(self):
        svc = _svc()
        with patch.object(svc, "get_tech_indicators", new=AsyncMock(return_value={"ok": 1})) as m:
            await svc.fetch_yf_data("technical", "AAPL")
        m.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_financials_route(self):
        svc = _svc()
        with patch.object(svc, "get_financials", new=AsyncMock(return_value={"ok": 1})) as m:
            await svc.fetch_yf_data("financials", "AAPL")
        m.assert_awaited_once()


class TestGetQuoteErrorPaths:
    @pytest.mark.asyncio
    async def test_quote_source_error(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=ConnectionError("net down"))):
            result = await svc.get_quote("AAPL")
        assert result["error_category"] == "source_error"

    @pytest.mark.asyncio
    async def test_quote_data_unavailable(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("No data found for ticker"))):
            result = await svc.get_quote("BADTICKER")
        assert result["error_category"] == "data_unavailable"

    @pytest.mark.asyncio
    async def test_quote_rate_limit_classified(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("rate limit exceeded"))):
            result = await svc.get_quote("AAPL")
        assert result["error_category"] == "source_error"


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_history_success(self):
        svc = _svc()
        df = pd.DataFrame(
            {
                "Date": ["2026-01-01"],
                "Open": [100.0],
                "High": [110.0],
                "Low": [90.0],
                "Close": [105.0],
                "Volume": [1_000_000],
            }
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=df)):
            result = await svc.get_history("AAPL", period="1mo")
        assert result["count"] == 1
        assert result["data"][0]["close"] == 105.0

    @pytest.mark.asyncio
    async def test_history_error(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("No data"))):
            result = await svc.get_history("AAPL")
        assert result["error_category"] == "data_unavailable"


class TestHelperNoops:
    def test_ensure_router_noop(self):
        assert _svc()._ensure_router() is None

    def test_get_macro_daemon_none(self):
        assert _svc().get_macro_daemon() is None

    @pytest.mark.asyncio
    async def test_get_tech_indicators_no_data(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=pd.DataFrame())):
            result = await svc.get_tech_indicators("AAPL")
        assert result["error"] == "no history data"

    @pytest.mark.asyncio
    async def test_get_tech_indicators_error(self):
        svc = _svc()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("boom"))):
            result = await svc.get_tech_indicators("AAPL")
        assert "error" in result
