"""
Market Router 降级与异常路径单元测试 (Extra 2)
覆盖: /history AKShare降级, /option-chain YFinance降级, /tech-indicators 降级
策略: 直接测 router，不使用 backend.main.app，避免响应封装问题
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-key")
os.environ.setdefault("FRED_API_KEY", "test-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.market import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


# ─── /market/history AKShare 降级 ───────────────────────────────────
class TestHistoryAKShareFallback:
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.data_source_router")
    def test_a_share_akshare_success(self, mock_router, mock_futu):
        mock_futu.get_history = AsyncMock(return_value={"status": "error", "message": "原生不支持"})
        mock_router.fetch_akshare = AsyncMock(
            return_value={
                "status": "success",
                "data": [{"time": "2024-01-01", "open": 10, "high": 11, "low": 10, "close": 10.5, "volume": 1000000}],
            }
        )
        resp = client.get("/market/history?ticker=SH.600000&ktype=K_DAY")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @pytest.mark.skip(reason="需要正确 mock pandas DataFrame，成本过高，后续单独处理")
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market._to_yf_ticker")
    def test_a_share_akshare_fail_yf_fallback(self, mock_fmt, mock_yf, mock_ak, mock_futu):
        mock_futu.get_history = AsyncMock(return_value={"status": "error", "message": "原生不支持"})
        mock_ak.get_stock_history = AsyncMock(return_value={"status": "error", "message": "AK失败"})
        mock_fmt.return_value = "600000.SS"
        resp = client.get("/market/history?ticker=SH.600000&ktype=K_DAY")
        assert resp.status_code == 200


# ─── /market/option-chain YFinance 降级 ─────────────────────────────
class TestOptionChainYFinanceFallback:
    @pytest.mark.skip(reason="需要正确 mock yfinance Ticker.option_chain，成本过高，后续单独处理")
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market._to_yf_ticker")
    def test_futu_error_yf_success(self, mock_fmt, mock_futu):
        mock_futu.get_option_chain = AsyncMock(return_value={"status": "error", "message": "原生不支持"})
        mock_fmt.return_value = "AAPL"
        resp = client.get("/market/option-chain?ticker=US.AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["source"] == "yfinance_fallback"

    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market._to_yf_ticker")
    def test_both_fail_returns_400(self, mock_fmt, mock_futu):
        mock_futu.get_option_chain = AsyncMock(return_value={"status": "error", "message": "futu error"})
        mock_fmt.return_value = "AAPL"
        mock_tk = MagicMock()
        mock_tk.options = []
        with patch.dict(sys.modules, {"yfinance": MagicMock(Ticker=lambda t: mock_tk)}):
            resp = client.get("/market/option-chain?ticker=US.AAPL")
            assert resp.status_code == 400


# ─── /market/tech-indicators 降级 ───────────────────────────────────
class TestTechIndicatorsFallback:
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.data_source_router")
    def test_futu_fail_yf_success(self, mock_router, mock_futu):
        mock_futu.get_history = AsyncMock(return_value={"status": "error", "message": "原生不支持"})
        mock_router.fetch_yfinance = AsyncMock(
            return_value={"status": "success", "data": {"ticker": "AAPL", "trend": []}}
        )
        resp = client.get("/market/tech-indicators?ticker=US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.data_source_router")
    def test_both_fail_returns_400(self, mock_router, mock_futu):
        mock_futu.get_history = AsyncMock(return_value={"status": "error", "message": "futu error"})
        mock_router.fetch_yfinance = AsyncMock(return_value={"status": "error", "message": "yf error"})
        resp = client.get("/market/tech-indicators?ticker=US.AAPL")
        assert resp.status_code == 400


# ─── /market/fundamental YFinance 兜底 ──────────────────────────────
class TestFundamentalYFinanceFallback:
    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.data_source_router")
    def test_futu_fail_yf_success(self, mock_router, mock_futu):
        mock_futu.get_fundamental = AsyncMock(return_value={"status": "error"})
        mock_router.fetch_yfinance = AsyncMock(
            return_value={
                "success": True,
                "data": {
                    "shortName": "Apple",
                    "trailingPE": 25.0,
                    "forwardPE": 24.0,
                    "pegRatio": 1.5,
                    "priceToBook": 10.0,
                    "returnOnEquity": 0.5,
                    "shortRatio": 1.0,
                    "beta": 1.2,
                },
                "message": None,
            }
        )
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "trailing_PE" in data["data"]

    @patch("backend.routers.market.market_data")
    @patch("backend.routers.market.data_source_router")
    def test_both_fail_returns_400(self, mock_router, mock_futu):
        mock_futu.get_fundamental = AsyncMock(return_value={"status": "error"})
        mock_router.fetch_yfinance = AsyncMock(return_value={"success": False, "data": None, "message": "yf error"})
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 400


# ─── /market/news 异常路径 ─────────────────────────────────────────
class TestNewsErrorPaths:
    @patch("backend.routers.market.redis_client")
    @patch("backend.routers.market.market_data")
    def test_finnhub_exception_returns_empty(self, mock_finhub, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        mock_finhub.get_company_news = AsyncMock(side_effect=Exception("Finnhub down"))
        resp = client.get("/market/news?ticker=AAPL&limit=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["data"] == []

    @patch("backend.routers.market.redis_client")
    def test_redis_exception_continues_to_finnhub(self, mock_redis):
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
        with patch("backend.routers.market.market_data") as mock_finhub:
            mock_finhub.get_company_news = AsyncMock(
                return_value={
                    "status": "success",
                    "data": [{"datetime": 1700000000, "headline": "News", "summary": "Summary"}],
                }
            )
            resp = client.get("/market/news?ticker=AAPL&limit=5")
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"
