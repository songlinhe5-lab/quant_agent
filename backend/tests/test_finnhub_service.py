import json
import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _resp(json_data=None, err_code=None):
    r = MagicMock()
    r.json.return_value = json_data or {}
    if err_code:
        err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=err_code))
        r.raise_for_status = MagicMock(side_effect=err)
    else:
        r.raise_for_status = MagicMock()
    return r


@asynccontextmanager
async def _client_cm(response=None, side_effect=None):
    c = AsyncMock()
    c.get = AsyncMock(side_effect=side_effect) if side_effect else AsyncMock(return_value=response)
    yield c


class TestFinnhubService:
    @pytest.fixture
    def service(self):
        from backend.services.finnhub_service import FinnhubService

        return FinnhubService()

    @pytest.mark.asyncio
    async def test_get_earnings_calendar_no_api_key_returns_error(self, service):
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            result = await service.get_earnings_calendar()
            assert result["status"] == "error"
            assert "FINNHUB_API_KEY" in result["message"]

    @pytest.mark.asyncio
    async def test_get_earnings_calendar_cache_hit_returns_cached(self, service):
        with patch("backend.services.finnhub_service.redis_client") as m:
            m.get = AsyncMock(return_value=json.dumps([{"symbol": "AAPL"}]))
            result = await service.get_earnings_calendar()
            assert result["status"] == "success"
            assert result["source"] == "redis_cache"

    @pytest.mark.asyncio
    async def test_get_earnings_calendar_success_filters_empty_symbol(self, service):
        data = {"earningsCalendar": [{"symbol": "AAPL", "date": "2026-06-30"}, {"symbol": ""}]}
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch("backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(data))),
        ):
            m.get, m.setex = AsyncMock(return_value=None), AsyncMock()
            result = await service.get_earnings_calendar()
            assert result["status"] == "success"
            assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_earnings_calendar_http_error_returns_error(self, service):
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch(
                "backend.services.finnhub_service.httpx.AsyncClient",
                return_value=_client_cm(response=_resp(err_code=500)),
            ),
        ):
            m.get = AsyncMock(return_value=None)
            result = await service.get_earnings_calendar()
            assert result["status"] == "error"
            assert "HTTP 500" in result["message"]

    @pytest.mark.asyncio
    async def test_get_stock_history_cache_hit_returns_cached(self, service):
        with patch("backend.services.finnhub_service.redis_client") as m:
            m.get = AsyncMock(return_value=json.dumps([{"close": 100.0}]))
            assert (await service.get_stock_history("AAPL"))["source"] == "redis_cache"

    @pytest.mark.asyncio
    async def test_get_stock_history_success_returns_klines(self, service):
        data = {"s": "ok", "t": [1719500000], "o": [100.0], "h": [102.0], "l": [99.0], "c": [101.0], "v": [10000]}
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch("backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(data))),
        ):
            m.get, m.setex = AsyncMock(return_value=None), AsyncMock()
            result = await service.get_stock_history("US.AAPL", days_back=1)
            assert result["source"] == "finnhub"
            assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_stock_history_status_not_ok_returns_error(self, service):
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch(
                "backend.services.finnhub_service.httpx.AsyncClient",
                return_value=_client_cm(response=_resp({"s": "no_data"})),
            ),
        ):
            m.get = AsyncMock(return_value=None)
            assert (await service.get_stock_history("AAPL"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_insider_transactions_cache_hit_returns_cached(self, service):
        with patch("backend.services.finnhub_service.redis_client") as m:
            m.get = AsyncMock(return_value=json.dumps([{"name": "CEO"}]))
            assert (await service.get_insider_transactions("AAPL"))["source"] == "redis_cache"

    @pytest.mark.asyncio
    async def test_get_insider_transactions_success_marks_buy_sell(self, service):
        data = {
            "data": [
                {"name": "CEO", "change": 1000, "transactionDate": "2026-06-29", "transactionPrice": 100.0},
                {"name": "CFO", "change": -500, "transactionDate": "2026-06-28", "transactionPrice": 101.0},
            ]
        }
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch("backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(data))),
        ):
            m.get, m.setex = AsyncMock(return_value=None), AsyncMock()
            result = await service.get_insider_transactions("US.AAPL", limit=10)
            assert result["data"][0]["action"] == "BUY"
            assert result["data"][1]["action"] == "SELL"

    @pytest.mark.asyncio
    async def test_get_market_news_invalid_category_resets_to_general(self, service):
        with patch(
            "backend.services.finnhub_service.httpx.AsyncClient",
            return_value=_client_cm(response=_resp([{"headline": "n"}])),
        ):
            assert (await service.get_market_news("invalid"))["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_market_news_429_returns_rate_limit_error(self, service):
        with patch(
            "backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(err_code=429))
        ):
            result = await service.get_market_news()
            assert result["status"] == "error"
            assert "429" in result["message"]

    @pytest.mark.asyncio
    async def test_get_market_news_500_returns_error(self, service):
        with patch(
            "backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(err_code=500))
        ):
            result = await service.get_market_news()
            assert "HTTP 500" in result["message"]

    @pytest.mark.asyncio
    async def test_get_company_news_cache_hit_returns_cached(self, service):
        with patch("backend.services.finnhub_service.redis_client") as m:
            m.get = AsyncMock(return_value=json.dumps([{"headline": "cached"}]))
            assert (await service.get_company_news("AAPL"))["source"] == "redis_cache"

    @pytest.mark.asyncio
    async def test_get_company_news_success_returns_data(self, service):
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch(
                "backend.services.finnhub_service.httpx.AsyncClient",
                return_value=_client_cm(response=_resp([{"headline": "n"}])),
            ),
        ):
            m.get, m.set = AsyncMock(return_value=None), AsyncMock()
            result = await service.get_company_news("US.AAPL")
            assert result["source"] == "http_api"

    @pytest.mark.asyncio
    async def test_get_company_news_403_fallback_yahoo_success(self, service):
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch(
                "backend.services.finnhub_service.httpx.AsyncClient",
                return_value=_client_cm(response=_resp(err_code=403)),
            ),
            patch.object(service, "_fallback_yahoo_news", new=AsyncMock(return_value=[{"headline": "y"}])),
        ):
            m.get, m.set = AsyncMock(return_value=None), AsyncMock()
            result = await service.get_company_news("HK.00700")
            assert result["source"] == "yahoo_fallback"

    @pytest.mark.asyncio
    async def test_get_company_news_429_fallback_failure_returns_error(self, service):
        with (
            patch("backend.services.finnhub_service.redis_client") as m,
            patch(
                "backend.services.finnhub_service.httpx.AsyncClient",
                return_value=_client_cm(response=_resp(err_code=429)),
            ),
            patch.object(service, "_fallback_yahoo_news", new=AsyncMock(return_value=[])),
        ):
            m.get = AsyncMock(return_value=None)
            assert (await service.get_company_news("AAPL"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_fallback_yahoo_news_success_returns_formatted(self, service):
        data = {"news": [{"title": "t1", "publisher": "Yahoo", "link": "u1", "providerPublishTime": 1719500000}]}
        with patch("backend.services.finnhub_service.httpx.AsyncClient", return_value=_client_cm(response=_resp(data))):
            result = await service._fallback_yahoo_news("0700.HK")
            assert len(result) == 1
            assert result[0]["related"] == "0700.HK"

    @pytest.mark.asyncio
    async def test_fallback_yahoo_news_exception_returns_empty(self, service):
        with patch(
            "backend.services.finnhub_service.httpx.AsyncClient",
            return_value=_client_cm(side_effect=RuntimeError("boom")),
        ):
            assert await service._fallback_yahoo_news("AAPL") == []

    @pytest.mark.asyncio
    async def test_get_news_tags_rules_cache_hit_returns_cached(self, service):
        rules = {"FED": r"\bfed\b"}
        with patch("backend.services.finnhub_service.l1_cached_redis") as m:
            m.get = AsyncMock(return_value=json.dumps(rules))
            assert await service._get_news_tags_rules() == rules

    @pytest.mark.asyncio
    async def test_get_news_tags_rules_default_returns_default(self, service):
        with patch("backend.services.finnhub_service.l1_cached_redis") as m:
            m.get = AsyncMock(return_value=None)
            result = await service._get_news_tags_rules()
            assert "FED" in result and "ECB" in result

    def test_generate_news_tags_matches_rules_and_skips_invalid_regex(self, service):
        rules = {"FED": r"\bfed\b", "CRYPTO": r"\bbitcoin\b", "BAD": "[invalid"}
        tags = service._generate_news_tags("the fed cut rates. bitcoin soared.", rules)
        assert "FED" in tags and "CRYPTO" in tags and "BAD" not in tags
