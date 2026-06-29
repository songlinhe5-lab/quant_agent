import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

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


@pytest.mark.no_mock_external
class TestYFinanceServiceBatch:
    """yfinance_service 微批处理/限流器/熔断/降级等高阶路径补强测试"""

    @pytest.fixture
    def service(self):
        from backend.services.yfinance_service import YFinanceService
        svc = YFinanceService()
        yield svc
        svc.close()

    # ─── RateLimitedSession ──────────────────────────────────────
    def test_rate_limited_session_request_injects_timeout_and_tracks_metrics(self):
        from backend.services.yfinance_service import RateLimitedSession
        s = RateLimitedSession(max_requests=5, per_seconds=0.01)
        captured = {}

        def fake_request(method, url, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return MagicMock(status_code=200)

        with patch("backend.services.yfinance_service.requests.Session.request", side_effect=fake_request), \
             patch("backend.core.middleware.EXTERNAL_API_COUNT") as m_cnt, \
             patch("backend.core.middleware.EXTERNAL_API_LATENCY") as m_lat:
            res = s.request("GET", "http://x")
        assert captured["timeout"] == 15.0
        assert res.status_code == 200
        m_cnt.labels.assert_called_with(service_name="yfinance", method="GET", http_status=200)
        m_cnt.labels.return_value.inc.assert_called_once()
        m_lat.labels.assert_called_with(service_name="yfinance", method="GET")

    def test_rate_limited_session_request_exception_increments_500_metric(self):
        from backend.services.yfinance_service import RateLimitedSession
        s = RateLimitedSession(max_requests=5, per_seconds=0.01)
        with patch("backend.services.yfinance_service.requests.Session.request", side_effect=RuntimeError("boom")), \
             patch("backend.core.middleware.EXTERNAL_API_COUNT") as m_cnt, \
             patch("backend.core.middleware.EXTERNAL_API_LATENCY") as m_lat:
            with pytest.raises(RuntimeError):
                s.request("POST", "http://x")
        m_cnt.labels.assert_called_with(service_name="yfinance", method="POST", http_status=500)

    def test_rate_limited_session_request_sleeps_when_over_capacity(self):
        from backend.services.yfinance_service import RateLimitedSession
        s = RateLimitedSession(max_requests=1, per_seconds=2.0)
        s._request_times.append(time.time())
        with patch("backend.services.yfinance_service.time.sleep") as m_sleep, \
             patch("backend.services.yfinance_service.requests.Session.request", return_value=MagicMock(status_code=200)), \
             patch("backend.core.middleware.EXTERNAL_API_COUNT"), \
             patch("backend.core.middleware.EXTERNAL_API_LATENCY"):
            s.request("GET", "http://x")
        m_sleep.assert_called_once()
        assert m_sleep.call_args[0][0] > 0

    # ─── fetch_yf_data 错误路径 ──────────────────────────────────
    @pytest.mark.asyncio
    async def test_fetch_yf_data_yf_shared_429_triggers_circuit_breaker(self, service):
        errors_dict = {}

        def _populate_errors(*a, **kw):
            errors_dict["AAPL"] = "YFRateLimitError: 429 Too Many Requests"
            return {"symbol": "AAPL"}

        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = errors_dict
        mock_info = PropertyMock(side_effect=_populate_errors)
        type(mock_yf.Ticker.return_value).info = mock_info
        with patch("backend.services.yfinance_service.yf", mock_yf), \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            ok, _, msg = await service.fetch_yf_data("AAPL", "info", 60)
        assert not ok and "限流" in msg
        assert service._circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_fetch_yf_data_yf_shared_ticker_error_returns_error(self, service):
        errors_dict = {}

        def _populate_errors(*a, **kw):
            errors_dict["AAPL"] = "Delisted"
            return {"symbol": "AAPL"}

        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = errors_dict
        mock_info = PropertyMock(side_effect=_populate_errors)
        type(mock_yf.Ticker.return_value).info = mock_info
        with patch("backend.services.yfinance_service.yf", mock_yf), \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            ok, _, msg = await service.fetch_yf_data("AAPL", "info", 60)
        assert not ok and "无效" in msg

    @pytest.mark.asyncio
    async def test_fetch_yf_data_soft_limit_retries_then_fails(self, service):
        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = {}
        mock_yf.download.return_value = pd.DataFrame()
        with patch("backend.services.yfinance_service.yf", mock_yf), \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            ok, _, msg = await service.fetch_yf_data("AAPL", "history", 60, period="5d")
        assert not ok and "无效" in msg

    @pytest.mark.asyncio
    async def test_fetch_yf_data_dev_mode_returns_mock(self):
        from backend.services.yfinance_service import YFinanceService
        with patch.dict(os.environ, {"QUANT_ENV": "development"}), \
             patch("backend.services.yfinance_service.yf", None):
            svc = YFinanceService()
            ok, _, msg = await svc.fetch_yf_data("AAPL", "info", 60)
            svc.close()
        assert not ok and msg == "development_mock"

    @pytest.mark.asyncio
    async def test_fetch_yf_data_no_yfinance_dep_returns_error(self):
        from backend.services.yfinance_service import YFinanceService
        with patch("backend.services.yfinance_service.yf", None):
            svc = YFinanceService()
            ok, _, msg = await svc.fetch_yf_data("AAPL", "info", 60)
            svc.close()
        assert not ok and "依赖" in msg

    # ─── _dispatch_batch_quotes ──────────────────────────────────
    @pytest.mark.asyncio
    async def test_get_batched_quote_dispatch_returns_quote(self, service):
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        df = pd.DataFrame({"Open": [1, 2, 3, 4, 5], "High": [2, 3, 4, 5, 6],
                           "Low": [0, 1, 2, 3, 4], "Close": [1.5, 2.5, 3.5, 4.5, 5.5],
                           "Volume": [100] * 5}, index=dates)
        with patch("backend.services.yfinance_service.yf") as m_yf, \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            m_yf.shared._ERRORS = {}
            m_yf.download.return_value = df
            r = await service.get_batched_quote("AAPL")
        assert r["status"] == "success" and r["last_price"] == 5.5

    @pytest.mark.asyncio
    async def test_get_batched_quote_dispatch_tech_invokes_tech_indicators(self, service):
        dates = pd.date_range("2026-05-01", periods=30, freq="D")
        df = pd.DataFrame({"Open": range(30), "High": range(1, 31), "Low": range(30),
                           "Close": range(30), "Volume": [10000] * 30}, index=dates)
        with patch("backend.services.yfinance_service.yf") as m_yf, \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            m_yf.shared._ERRORS = {}
            m_yf.download.return_value = df
            r = await service.get_batched_quote("AAPL", req_type="tech", lookback_days=2)
        assert r["status"] == "success" and len(r["data"]["trend"]) == 2

    @pytest.mark.asyncio
    async def test_get_batched_quote_dispatch_429_triggers_circuit_breaker(self, service):
        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = {}
        mock_yf.download = MagicMock(side_effect=Exception("YFRateLimitError: 429 Too Many Requests"))
        with patch("backend.services.yfinance_service.yf", mock_yf), \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            r = await service.get_batched_quote("AAPL")
        assert r["status"] == "error"
        assert service._circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_get_batched_quote_dispatch_empty_df_returns_error(self, service):
        mock_yf = MagicMock()
        mock_yf.shared._ERRORS = {}
        mock_yf.download.return_value = pd.DataFrame()
        with patch("backend.services.yfinance_service.yf", mock_yf), \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            r = await service.get_batched_quote("AAPL")
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_batched_quote_dispatch_missing_close_returns_error(self, service):
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        df = pd.DataFrame({"Open": [1, 2, 3, 4, 5], "High": [2, 3, 4, 5, 6],
                           "Low": [0, 1, 2, 3, 4], "Volume": [100] * 5}, index=dates)
        with patch("backend.services.yfinance_service.yf") as m_yf, \
             patch("backend.services.yfinance_service.asyncio.sleep", new=AsyncMock()):
            m_yf.shared._ERRORS = {}
            m_yf.download.return_value = df
            r = await service.get_batched_quote("AAPL")
        assert r["status"] == "error"

    # ─── get_tech_indicators 错误路径 ────────────────────────────
    @pytest.mark.asyncio
    async def test_get_tech_indicators_dev_mode_returns_mock(self):
        from backend.services.yfinance_service import YFinanceService
        svc = YFinanceService()
        with patch.dict(os.environ, {"QUANT_ENV": "development"}), \
             patch.object(svc, "fetch_yf_data", new=AsyncMock(return_value=(False, None, "development_mock"))):
            r = await svc.get_tech_indicators("AAPL")
        svc.close()
        assert r["status"] == "success" and "降级" in r["message"]

    @pytest.mark.asyncio
    async def test_get_tech_indicators_rate_limit_returns_mock(self, service):
        with patch.object(service, "fetch_yf_data", new=AsyncMock(return_value=(False, None, "限流冷却中"))):
            r = await service.get_tech_indicators("AAPL")
        assert r["status"] == "success" and "降级" in r["message"]

    @pytest.mark.asyncio
    async def test_get_tech_indicators_other_error_returns_error(self, service):
        with patch.object(service, "fetch_yf_data", new=AsyncMock(return_value=(False, None, "网络异常"))):
            r = await service.get_tech_indicators("AAPL")
        assert r["status"] == "error" and "网络异常" in r["message"]

    # ─── search_tickers 细节分支 ─────────────────────────────────
    @pytest.mark.asyncio
    async def test_search_tickers_redis_error_swallowed_continues_to_network(self, service):
        service.session.get = MagicMock(side_effect=RuntimeError("network boom"))
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(side_effect=RuntimeError("redis down"))
            r = await service.search_tickers("AAPL")
        assert r["status"] == "error" and "network boom" in r["message"]

    @pytest.mark.asyncio
    async def test_search_tickers_non_429_exception_returns_error(self, service):
        service.session.get = MagicMock(side_effect=RuntimeError("403 Forbidden"))
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(return_value=None)
            r = await service.search_tickers("AAPL")
        assert r["status"] == "error" and "403" in r["message"]

    @pytest.mark.asyncio
    async def test_search_tickers_writes_cache_on_success(self, service):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"quotes": [{"symbol": "AAPL", "quoteType": "EQUITY", "shortname": "Apple"}]}
        mock_resp.raise_for_status = MagicMock()
        service.session.get = MagicMock(return_value=mock_resp)
        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(return_value=None)
            m.setex = AsyncMock()
            r = await service.search_tickers("AAPL")
        assert r["status"] == "success"
        m.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_tickers_double_check_cache_returns_cached(self, service):
        cached = json.dumps([{"symbol": "US.AAPL"}])
        call_count = {"n": 0}

        async def fake_get(key):
            call_count["n"] += 1
            return cached if call_count["n"] >= 2 else None

        with patch("backend.core.redis_client.redis_client") as m:
            m.get = AsyncMock(side_effect=fake_get)
            r = await service.search_tickers("AAPL")
        assert r["status"] == "success" and len(r["data"]) == 1
