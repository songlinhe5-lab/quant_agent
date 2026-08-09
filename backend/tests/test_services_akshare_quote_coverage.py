"""补充 services/akshare/quote.py (QuoteMixin) 遗漏分支的覆盖率测试。

QuoteMixin 为 mixin, 无法独立实例化, 故用一个 dummy 子类提供其依赖的
实例属性 (_circuit_breaker_until / _cache_mode / _error_count / _max_errors)
与异步上下文管理器 _acquire_lock_with_timeout。

连接层已下沉 data_subservice，故直接 mock 本模块导入的
backend.services.akshare.quote.data_source_router；redis 仅 patch
backend.services.akshare.quote.redis_client。
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.akshare.quote import QuoteMixin


class _QuoteHarness(QuoteMixin):
    def __init__(self, cache_mode=False, circuit_until=0.0, max_errors=3):
        self._circuit_breaker_until = circuit_until
        self._cache_mode = cache_mode
        self._error_count = 0
        self._max_errors = max_errors

    @asynccontextmanager
    async def _acquire_lock_with_timeout(self, timeout):
        yield


def _mem_redis(get_return=None):
    m = MagicMock()
    m.get = AsyncMock(return_value=get_return)
    m.set = AsyncMock(return_value=True)
    m.delete = AsyncMock(return_value=1)
    return m


def _news_remote():
    return {
        "status": "success",
        "data": [
            {
                "datetime": 1.0,
                "date": "2026-01-02 09:30:00",
                "headline": "利好",
                "summary": "公司签大单",
                "url": "http://x/1",
                "source": "东方财富",
            }
        ],
        "source": "akshare",
    }


def _quote_remote():
    return {
        "status": "success",
        "data": {
            "ticker": "SH.600519",
            "last_price": 11.8,
            "open": 10.5,
            "high": 12.0,
            "low": 10.2,
            "prev_close": 10.5,
            "volume": 2000,
            "turnover": 23600.0,
            "change_val": 1.3,
            "change_pct": 12.38,
            "amplitude": 7.62,
            "volume_str": "2.00K",
        },
        "source": "akshare_sina",
    }


def _history_remote(num=1):
    rows = [{"time": "2026-01-02 00:00:00", "open": 10.5, "high": 12.0, "low": 10.2, "close": 11.8, "volume": 2000}]
    return {"status": "success", "data": rows[:num], "source": "akshare_fallback"}


# ── get_company_news ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_news_cache_hit():
    cached = {"status": "success", "data": [{"headline": "cached"}], "source": "akshare"}
    r = _mem_redis(get_return=json.dumps(cached))
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_company_news("SH.600519")
    assert res["status"] == "success"
    assert res["data"][0]["headline"] == "cached"


@pytest.mark.asyncio
async def test_news_circuit_breaker_shortcut():
    r = _mem_redis()
    h = _QuoteHarness(circuit_until=1e18)
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_company_news("SH.600519")
    assert res["status"] == "error"
    assert "熔断" in res["message"]


@pytest.mark.asyncio
async def test_news_cache_mode():
    r = _mem_redis()
    h = _QuoteHarness(cache_mode=True)
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_company_news("SH.600519")
    assert res["status"] == "no_data"


@pytest.mark.asyncio
async def test_news_hk_fallback_with_news():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch(
            "backend.core.yahoo_news.fetch_yahoo_news",
            new=AsyncMock(return_value=[{"title": "hk news"}]),
        ),
    ):
        res = await h.get_company_news("HK.00700")
    assert res["status"] == "success"
    assert res["source"] == "yahoo_fallback"


@pytest.mark.asyncio
async def test_news_hk_fallback_empty_uses_short_ttl():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch(
            "backend.core.yahoo_news.fetch_yahoo_news",
            new=AsyncMock(return_value=[]),
        ),
    ):
        res = await h.get_company_news("HK.00700")
    assert res["status"] == "success"
    assert res["data"] == []


@pytest.mark.asyncio
async def test_news_block_index_warning():
    r = _mem_redis()
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_company_news("HK.BK1118")
    assert res["status"] == "warning"


@pytest.mark.asyncio
async def test_news_invalid_code_error():
    r = _mem_redis()
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_company_news("INVALID")
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_news_ashare_success():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch("backend.services.akshare.quote.data_source_router") as mock_router,
    ):
        mock_router.fetch_akshare = AsyncMock(return_value=_news_remote())
        res = await h.get_company_news("SH.600519")
    assert res["status"] == "success"
    assert res["data"][0]["headline"] == "利好"
    r.set.assert_awaited()


@pytest.mark.asyncio
async def test_news_ashare_error_triggers_circuit():
    r = _mem_redis()
    h = _QuoteHarness(max_errors=1)
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch("backend.services.akshare.quote.data_source_router") as mock_router,
    ):
        mock_router.fetch_akshare = AsyncMock(side_effect=ValueError("boom"))
        res = await h.get_company_news("SH.600519")
    assert res["status"] == "error"
    assert h._circuit_breaker_until > 0  # 触发熔断休眠


# ── get_stock_quote ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quote_cache_hit():
    cached = {"status": "success", "data": {"last_price": 1.0}, "source": "akshare_fallback"}
    r = _mem_redis(get_return=json.dumps(cached))
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_quote("SH.600519")
    assert res["data"]["last_price"] == 1.0


@pytest.mark.asyncio
async def test_quote_circuit_breaker_shortcut():
    r = _mem_redis()
    h = _QuoteHarness(circuit_until=1e18)
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_quote("SH.600519")
    assert res["status"] == "error"
    assert "熔断" in res["message"]


@pytest.mark.asyncio
async def test_quote_invalid_code():
    r = _mem_redis()
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_quote("ABC")
    assert res["status"] == "error"
    assert "无效" in res["message"]


@pytest.mark.asyncio
async def test_quote_success_and_error_branch():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch("backend.services.akshare.quote.data_source_router") as mock_router,
    ):
        mock_router.fetch_akshare = AsyncMock(return_value=_quote_remote())
        res = await h.get_stock_quote("SH.600519")
    assert res["status"] == "success"
    assert res["data"]["last_price"] == 11.8

    # 远程非成功 -> 异常分支 + 熔断
    r2 = _mem_redis()
    h2 = _QuoteHarness(max_errors=1)
    with (
        patch("backend.services.akshare.quote.redis_client", r2),
        patch("backend.services.akshare.quote.data_source_router") as mock_router2,
    ):
        mock_router2.fetch_akshare = AsyncMock(side_effect=RuntimeError("remote boom"))
        res2 = await h2.get_stock_quote("SH.600519")
    assert res2["status"] == "error"
    assert h2._circuit_breaker_until > 0


# ── get_stock_history ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_history_cache_hit():
    cached = {"status": "success", "data": [{"close": 1.0}], "source": "akshare_fallback"}
    r = _mem_redis(get_return=json.dumps(cached))
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_history("SH.600519")
    assert res["data"][0]["close"] == 1.0


@pytest.mark.asyncio
async def test_history_circuit_breaker_shortcut():
    r = _mem_redis()
    h = _QuoteHarness(circuit_until=1e18)
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_history("SH.600519")
    assert res["status"] == "error"
    assert "熔断" in res["message"]


@pytest.mark.asyncio
async def test_history_invalid_code():
    r = _mem_redis()
    h = _QuoteHarness()
    with patch("backend.services.akshare.quote.redis_client", r):
        res = await h.get_stock_history("ABC")
    assert res["status"] == "error"
    assert "无效" in res["message"]


@pytest.mark.asyncio
async def test_history_success_and_error_branch():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch("backend.services.akshare.quote.data_source_router") as mock_router,
    ):
        mock_router.fetch_akshare = AsyncMock(return_value=_history_remote(num=1))
        res = await h.get_stock_history("SH.600519", num=1)
    assert res["status"] == "success"
    assert len(res["data"]) == 1

    r2 = _mem_redis()
    h2 = _QuoteHarness(max_errors=1)
    with (
        patch("backend.services.akshare.quote.redis_client", r2),
        patch("backend.services.akshare.quote.data_source_router") as mock_router2,
    ):
        mock_router2.fetch_akshare = AsyncMock(side_effect=RuntimeError("boom"))
        res2 = await h2.get_stock_history("SH.600519")
    assert res2["status"] == "error"
    assert h2._circuit_breaker_until > 0
