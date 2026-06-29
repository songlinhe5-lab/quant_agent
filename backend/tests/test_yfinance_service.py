import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestYFinanceService:

    @pytest.fixture
    def service(self):
        from backend.services.yfinance_service import YFinanceService
        svc = YFinanceService()
        yield svc
        svc.close()

    def test_format_yf_ticker_various_mappings_return_correct(self):
        from backend.services.yfinance_service import format_yf_ticker
        cases = {"HSI": "^HSI", "HK.00700": "0700.HK", "SH.600000": "600000.SS",
                 "US.AAPL": "AAPL", "SZ.000001": "000001.SZ", "VIX": "^VIX"}
        for inp, exp in cases.items():
            assert format_yf_ticker(inp) == exp

    def test_get_health_status_circuit_open_returns_circuit_open(self, service):
        service._circuit_breaker_until = time.time() + 60.0
        s = service.get_health_status()
        assert s["status"] == "circuit_open" and s["cooldown_remaining"] > 0

    def test_get_health_status_circuit_closed_returns_healthy(self, service):
        service._circuit_breaker_until = 0.0
        assert service.get_health_status()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_fetch_yf_data_circuit_breaker_returns_cooldown(self, service):
        service._circuit_breaker_until = time.time() + 60.0
        ok, _, msg = await service.fetch_yf_data("AAPL", "info", 60)
        assert not ok and "熔断" in msg

    @pytest.mark.asyncio
    async def test_fetch_yf_data_error_cache_recent_returns_cooldown(self, service):
        service._error_cache["yf_info_AAPL"] = time.time()
        ok, _, msg = await service.fetch_yf_data("AAPL", "info", 60)
        assert not ok and "冷却" in msg

    @pytest.mark.asyncio
    async def test_fetch_yf_data_cache_hit_returns_cached(self, service):
        service._cache["yf_info_AAPL"] = (time.time(), {"symbol": "AAPL", "price": 150.0})
        ok, data, _ = await service.fetch_yf_data("AAPL", "info", 60)
        assert ok and data["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_fetch_yf_data_success_returns_data(self, service):
        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = {}
        mock_yf.Ticker.return_value.info = {"symbol": "AAPL", "price": 150.0}
        with patch("backend.services.yfinance_service.yf", mock_yf):
            ok, data, _ = await service.fetch_yf_data("AAPL", "info", 60)
        assert ok and data["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_fetch_yf_data_429_triggers_circuit_breaker(self, service):
        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = {}
        mock_yf.download = MagicMock(side_effect=Exception("429 Too Many Requests"))
        with patch("backend.services.yfinance_service.yf", mock_yf):
            ok, _, msg = await service.fetch_yf_data("AAPL", "history", 60, period="5d")
        assert not ok and "限流" in msg
        assert service._circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_get_batched_quote_circuit_breaker_returns_error(self, service):
        service._circuit_breaker_until = time.time() + 60.0
        r = await service.get_batched_quote("AAPL")
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_batched_quote_cache_hit_returns_cached(self, service):
        cached = {"status": "success", "last_price": 150.0}
        service._cache["yf_batch_quote_AAPL_default"] = (time.time(), cached)
        assert await service.get_batched_quote("AAPL") == cached

    @pytest.mark.asyncio
    async def test_get_batched_quote_error_cache_returns_cooldown(self, service):
        service._error_cache["yf_batch_quote_AAPL_default"] = time.time()
        r = await service.get_batched_quote("AAPL")
        assert r["status"] == "error" and "冷却" in r["message"]

    @pytest.mark.asyncio
    async def test_get_tech_indicators_success_with_pre_fetched_df(self, service):
        dates = pd.date_range("2026-05-01", periods=30, freq="D")
        df = pd.DataFrame({"Open": range(30), "High": range(1, 31), "Low": range(30),
                           "Close": range(30), "Volume": [10000] * 30}, index=dates)
        r = await service.get_tech_indicators("AAPL", pre_fetched_df=df, lookback_days=2)
        assert r["status"] == "success" and len(r["data"]["trend"]) == 2

    @pytest.mark.asyncio
    async def test_get_tech_indicators_empty_df_returns_error(self, service):
        r = await service.get_tech_indicators("AAPL", pre_fetched_df=pd.DataFrame())
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_tech_indicators_fetch_failure_returns_mock(self, service):
        with patch.object(service, "fetch_yf_data", new=AsyncMock(return_value=(False, None, "数据无效"))):
            r = await service.get_tech_indicators("AAPL")
        assert r["status"] == "success" and "降级" in r["message"]

    @pytest.mark.asyncio
    async def test_search_tickers_empty_query_returns_empty(self, service):
        r = await service.search_tickers("")
        assert r["status"] == "success" and r["data"] == []

    @pytest.mark.asyncio
    async def test_search_tickers_too_long_query_returns_empty(self, service):
        r = await service.search_tickers("a" * 51)
        assert r["data"] == []

    @pytest.mark.asyncio
    async def test_search_tickers_circuit_breaker_returns_warning(self, service):
        service._circuit_breaker_until = time.time() + 60.0
        r = await service.search_tickers("AAPL")
        assert r["status"] == "warning" and r["data"] == []

    @pytest.mark.asyncio
    async def test_search_tickers_cache_hit_returns_cached(self, service):
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(return_value=json.dumps([{"symbol": "US.AAPL"}]))
            r = await service.search_tickers("AAPL")
        assert r["status"] == "success" and len(r["data"]) == 1

    @pytest.mark.asyncio
    async def test_search_tickers_success_returns_results(self, service):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"quotes": [{"symbol": "AAPL", "quoteType": "EQUITY", "shortname": "Apple"}]}
        mock_resp.raise_for_status = MagicMock()
        service.session.get = MagicMock(return_value=mock_resp)
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(return_value=None)
            m.setex = AsyncMock()
            r = await service.search_tickers("AAPL")
        assert r["status"] == "success" and len(r["data"]) >= 2

    @pytest.mark.asyncio
    async def test_search_tickers_429_triggers_circuit_breaker(self, service):
        service.session.get = MagicMock(side_effect=Exception("429 Too Many Requests"))
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(return_value=None)
            r = await service.search_tickers("AAPL")
        assert r["status"] == "warning"
        assert service._circuit_breaker_until > time.time()

    def test_close_releases_resources(self, service):
        service.session = MagicMock()
        service._executor = MagicMock()
        service.close()
        service.session.close.assert_called_once()
        service._executor.shutdown.assert_called_once()
