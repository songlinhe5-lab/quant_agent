"""子服务远程数据源 worker 单测（finnhub/fred/dbnomics/rbi/search）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice.baostock_worker import handle_baostock
from data_subservice.dbnomics_worker import handle_dbnomics
from data_subservice.finnhub_worker import handle_finnhub
from data_subservice.fred_worker import handle_fred
from data_subservice.rbi_worker import handle_rbi
from data_subservice.search_worker import handle_search
from data_subservice.tdx_worker import handle_tdx


class TestFinnhubWorker:
    @pytest.mark.asyncio
    async def test_dispatch_quote(self):
        with patch("data_subservice.finnhub_worker.finnhub_service") as svc:
            svc.get_quote = AsyncMock(return_value={"status": "success", "data": {"c": 1.0}})
            out = await handle_finnhub("QUOTE", {"symbol": "AAPL"})
        svc.get_quote.assert_awaited_once_with(ticker="AAPL")
        assert out == {"status": "success", "data": {"c": 1.0}}

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        out = await handle_finnhub("BOGUS", {})
        assert "error" in out


class TestFREDWorker:
    @pytest.mark.asyncio
    async def test_dispatch_macro_series(self):
        with patch("data_subservice.fred_worker.fred_service") as svc:
            svc.get_series_observations = AsyncMock(return_value={"status": "success", "data": {"observations": []}})
            out = await handle_fred("MACRO_SERIES", {"series_id": "DGS10", "limit": 10})
        svc.get_series_observations.assert_awaited_once_with(series_id="DGS10", limit=10)
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        out = await handle_fred("BOGUS", {})
        assert "error" in out


class TestDbnomicsWorker:
    @pytest.mark.asyncio
    async def test_dispatch_economic_calendar(self):
        with patch("data_subservice.dbnomics_worker.dbnomics_service") as svc:
            svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": []})
            out = await handle_dbnomics("ECONOMIC_CALENDAR", {"days_ahead": 7})
        svc.get_economic_calendar.assert_awaited_once_with(days_ahead=7)
        assert out["status"] == "success"


class TestRBIWorker:
    @pytest.mark.asyncio
    async def test_dispatch_economic_calendar(self):
        with patch("data_subservice.rbi_worker.rbi_service") as svc:
            svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": {}})
            out = await handle_rbi("ECONOMIC_CALENDAR", {"days_back": 3})
        svc.get_economic_calendar.assert_awaited_once_with(days_back=3)
        assert out["status"] == "success"


class TestSearchWorker:
    @pytest.mark.asyncio
    async def test_tavily(self):
        with patch("data_subservice.search_worker.tavily_service") as svc:
            svc.search = AsyncMock(return_value={"status": "success", "data": [{"title": "T"}]})
            out = await handle_search("tavily", "SEARCH", {"query": "apple", "max_results": 3})
        svc.search.assert_awaited_once()
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_bocha(self):
        with patch("data_subservice.search_worker.bocha_service") as svc:
            svc.search = AsyncMock(return_value={"status": "success", "data": [{"title": "N"}]})
            out = await handle_search("bocha", "SEARCH", {"query": "腾讯"})
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_jina(self):
        with patch("data_subservice.search_worker.jina_service") as svc:
            svc.scrape = AsyncMock(return_value={"status": "success", "data": {"content": "x"}})
            out = await handle_search("jina", "SEARCH", {"url": "https://example.com"})
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_unknown_source(self):
        out = await handle_search("foo", "SEARCH", {})
        assert "error" in out


class TestBaoStockWorker:
    @pytest.mark.asyncio
    async def test_dispatch_kline(self):
        with patch("data_subservice.baostock_worker.baostock_service") as svc:
            svc.get_kline = MagicMock(return_value={"status": "success", "data": []})
            out = await handle_baostock("KLINE_CN", {"symbol": "600000", "frequency": "d"})
        assert out["status"] == "success"
        svc.get_kline.assert_called_once_with("600000", start_date="", end_date="", frequency="d", adjust="front")

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        out = await handle_baostock("BOGUS", {})
        assert out["status"] == "error" and "未知" in out["message"]


class TestTdxWorker:
    @pytest.mark.asyncio
    async def test_dispatch_snapshot(self):
        with patch("data_subservice.tdx_worker.tdx_service") as svc:
            svc.get_snapshot = MagicMock(return_value={"status": "success", "data": [{"price": 10.5}]})
            out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "600036"})
        svc.get_snapshot.assert_called_once_with("600036")
        assert out["data"][0]["price"] == 10.5

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        out = await handle_tdx("BOGUS", {})
        assert out["status"] == "error" and "未知" in out["message"]
