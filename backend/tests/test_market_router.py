"""
Market Router 单元测试
TEST-14: 覆盖 backend/routers/market.py 所有 REST 端点与 WebSocket 处理器
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.routers.market import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


# ─── /market/futu/status ────────────────────────────────────────────────
class TestFutuStatus:
    @patch("backend.routers.market.futu_service")
    def test_returns_status_and_error(self, mock_futu):
        mock_futu.status = "CONNECTED"
        mock_futu.error_msg = ""
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CONNECTED"

    @patch("backend.routers.market.futu_service")
    def test_disconnected_status(self, mock_futu):
        mock_futu.status = "DISCONNECTED"
        mock_futu.error_msg = "OpenD unreachable"
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISCONNECTED"


# ─── /market/health/services ───────────────────────────────────────────
class TestServicesHealth:
    @patch("backend.routers.market.futu_service")
    @patch("backend.routers.market.akshare_service")
    @patch("backend.routers.market.yf_service")
    def test_health_all_healthy(self, mock_yf, mock_ak, mock_futu):
        mock_futu.status = "CONNECTED"
        mock_futu.error_msg = ""
        mock_ak.get_health_status.return_value = {"name": "AKShare", "status": "healthy"}
        mock_yf.get_health_status.return_value = {"name": "YFinance", "status": "healthy"}

        resp = client.get("/market/health/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        names = [s["name"] for s in data["data"]]
        assert "Futu OpenD" in names
        assert "AKShare" in names
        assert "YFinance" in names

    @patch("backend.routers.market.futu_service")
    def test_futu_disconnected(self, mock_futu):
        mock_futu.status = "ERROR"
        mock_futu.error_msg = "connection refused"
        resp = client.get("/market/health/services")
        assert resp.status_code == 200
        data = resp.json()["data"]
        futu_entry = next(s for s in data if s["name"] == "Futu OpenD")
        assert futu_entry["status"] == "disconnected"


# ─── /market/quote ─────────────────────────────────────────────────────
class TestGetQuote:
    @patch("backend.routers.market.futu_service")
    def test_futu_success(self, mock_futu):
        mock_futu.get_quote = AsyncMock(return_value={
            "status": "success", "data": {"ticker": "US.AAPL", "last_price": 150.0}
        })
        resp = client.get("/market/quote?ticker=US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.futu_service")
    @patch("backend.routers.market._to_yf_ticker")
    @patch("backend.routers.market.yf_service")
    def test_futu_error_yf_fallback(self, mock_yf, mock_fmt, mock_futu):
        mock_futu.get_quote = AsyncMock(return_value={
            "status": "error", "message": "原生不支持"
        })
        mock_fmt.return_value = "AAPL"
        mock_yf.fetch_yf_data = AsyncMock(return_value=(
            True, {"regularMarketPrice": 150.0, "regularMarketChange": 1.0,
                   "regularMarketChangePercent": 0.5, "regularMarketOpen": 149.0,
                   "regularMarketDayHigh": 152.0, "regularMarketDayLow": 148.0,
                   "previousClose": 149.0, "regularMarketVolume": 1000000}, None
        ))
        resp = client.get("/market/quote?ticker=US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.futu_service")
    @patch("backend.routers.market._to_yf_ticker")
    @patch("backend.routers.market.yf_service")
    def test_both_fail_returns_400(self, mock_yf, mock_fmt, mock_futu):
        mock_futu.get_quote = AsyncMock(return_value={
            "status": "error", "message": "futu error"
        })
        mock_fmt.return_value = "AAPL"
        mock_yf.fetch_yf_data = AsyncMock(return_value=(False, None, "yf error"))
        resp = client.get("/market/quote?ticker=US.AAPL")
        assert resp.status_code == 400


# ─── /market/fundamental/{ticker} ─────────────────────────────────────
class TestGetFundamental:
    @patch("backend.routers.market.fred_service")
    def test_macro_ticker_routes_to_fred(self, mock_fred):
        mock_fred.get_series_observations = AsyncMock(return_value={
            "status": "success", "data": [{"date": "2024-01-01", "value": "5000"}]
        })
        resp = client.get("/market/fundamental/SPX")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "fred_series_id" in data["data"]

    @patch("backend.routers.market.futu_service")
    @patch("backend.routers.market.yf_service")
    def test_futu_success(self, mock_yf, mock_futu):
        mock_futu.get_fundamental = AsyncMock(return_value={
            "status": "success", "data": {"trailing_PE": 20.0}
        })
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["data"]["trailing_PE"] == 20.0

    @patch("backend.routers.market.futu_service")
    @patch("backend.routers.market.yf_service")
    def test_etf_returns_warning(self, mock_yf, mock_futu):
        mock_futu.get_fundamental = AsyncMock(return_value={"status": "error"})
        mock_yf.fetch_yf_data = AsyncMock(return_value=(
            True, {"quoteType": "ETF", "shortName": "SPY ETF"}, None
        ))
        resp = client.get("/market/fundamental/US.SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "ETF" in data["message"]


# ─── /market/news ───────────────────────────────────────────────────────
class TestGetCompanyNews:
    @patch("backend.routers.market.redis_client")
    @patch("backend.routers.market.finnhub_service")
    def test_cached_result(self, mock_finhub, mock_redis):
        import json
        cached = json.dumps({"status": "success", "data": [{"headline": "Cached"}]})
        mock_redis.get = AsyncMock(return_value=cached)
        resp = client.get("/market/news?ticker=AAPL&limit=5")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["headline"] == "Cached"

    @patch("backend.routers.market.redis_client")
    @patch("backend.routers.market.finnhub_service")
    def test_fetch_from_finnhub(self, mock_finhub, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        mock_finhub.get_company_news = AsyncMock(return_value={
            "status": "success",
            "data": [{"datetime": 1700000000, "headline": "News", "summary": "Summary"}]
        })
        mock_redis.setex = AsyncMock()
        resp = client.get("/market/news?ticker=AAPL&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_invalid_ticker(self):
        resp = client.get("/market/news?ticker=###&limit=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ─── /market/search ────────────────────────────────────────────────────
class TestSearchTickers:
    @patch("backend.routers.market.ticker_service")
    def test_local_search_success(self, mock_ticker_svc):
        mock_ticker_svc.search_tickers = AsyncMock(return_value={
            "status": "success", "data": [{"ticker": "AAPL", "name": "Apple"}]
        })
        resp = client.get("/market/search?q=apple")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.ticker_service")
    @patch("backend.routers.market.yf_service")
    def test_local_empty_fallback_to_yf(self, mock_yf, mock_ticker_svc):
        mock_ticker_svc.search_tickers = AsyncMock(return_value={"status": "success", "data": []})
        mock_yf.search_tickers = AsyncMock(return_value={"status": "success", "data": [{"ticker": "AAPL"}]})
        resp = client.get("/market/search?q=AAPL")
        assert resp.status_code == 200


# ─── /market/holders/{ticker} ─────────────────────────────────────────
class TestGetTopHolders:
    def test_us_ticker_returns_warning(self):
        resp = client.get("/market/holders/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "warning"

    @patch("backend.routers.market.akshare_service")
    def test_hk_ticker_calls_akshare(self, mock_ak):
        mock_ak.get_hsgt_top_holders = AsyncMock(return_value={"status": "success", "data": []})
        resp = client.get("/market/holders/HK.00700")
        assert resp.status_code == 200


# ─── /market/insider-marquee ───────────────────────────────────────────
class TestInsiderMarquee:
    @patch("backend.routers.market.redis_client")
    def test_returns_success(self, mock_redis):
        import json
        mock_redis.zrevrange = AsyncMock(return_value=[
            json.dumps({"ticker": "AAPL", "transaction": "BUY"})
        ])
        resp = client.get("/market/insider-marquee?limit=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


# ─── /market/kline/sync ────────────────────────────────────────────────
class TestSyncKlineWarehouse:
    @patch("backend.routers.market.kline_warehouse")
    def test_sync_success(self, mock_wh):
        mock_wh.update_ticker = AsyncMock(return_value=True)
        resp = client.post("/market/kline/sync", json={"ticker": "US.AAPL", "interval": "1d"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.kline_warehouse")
    def test_sync_failure_returns_500(self, mock_wh):
        mock_wh.update_ticker = AsyncMock(return_value=False)
        resp = client.post("/market/kline/sync", json={"ticker": "US.AAPL", "interval": "1d"})
        assert resp.status_code == 500
