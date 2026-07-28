"""补充 services/akshare/quote.py (QuoteMixin) 遗漏分支的覆盖率测试。

QuoteMixin 为 mixin, 无法独立实例化, 故用一个 dummy 子类提供其依赖的
实例属性 (_circuit_breaker_until / _cache_mode / _error_count / _max_errors)
与异步上下文管理器 _acquire_lock_with_timeout。

方法内部 `import akshare as ak` 并调用 ak.stock_news_em / ak.stock_zh_a_hist,
直接 patch akshare 模块对应函数即可; redis 仅 patch 本模块导入的
backend.services.akshare.quote.redis_client。
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
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


def _news_df():
    return pd.DataFrame(
        [
            {
                "发布时间": "2026-01-02 09:30:00",
                "新闻标题": "利好",
                "新闻内容": "公司签大单",
                "新闻链接": "http://x/1",
                "文章来源": "东方财富",
            }
        ]
    )


def _hist_df():
    return pd.DataFrame(
        [
            {
                "日期": "2026-01-01",
                "开盘": 10.0,
                "最高": 11.0,
                "最低": 9.5,
                "收盘": 10.5,
                "成交量": 1000,
                "成交额": 10500.0,
                "振幅": 5.0,
            },
            {
                "日期": "2026-01-02",
                "开盘": 10.5,
                "最高": 12.0,
                "最低": 10.2,
                "收盘": 11.8,
                "成交量": 2000,
                "成交额": 23600.0,
                "振幅": 7.0,
            },
        ]
    )


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
            "backend.services.finnhub.service.finnhub_service._fallback_yahoo_news",
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
            "backend.services.finnhub.service.finnhub_service._fallback_yahoo_news",
            new=AsyncMock(return_value=[]),
        ),
    ):
        res = await h.get_company_news("HK.00700")
    assert res["status"] == "success"
    assert res["data"] == []


@pytest.mark.asyncio
async def test_news_ashare_success():
    r = _mem_redis()
    h = _QuoteHarness()
    with (
        patch("backend.services.akshare.quote.redis_client", r),
        patch("akshare.stock_news_em", new=MagicMock(return_value=_news_df())),
    ):
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
        patch("akshare.stock_news_em", new=MagicMock(side_effect=ValueError("boom"))),
    ):
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
        patch("akshare.stock_zh_a_hist", new=MagicMock(return_value=_hist_df())),
    ):
        res = await h.get_stock_quote("SH.600519")
    assert res["status"] == "success"
    assert res["data"]["last_price"] == 11.8

    # 空 df -> 异常分支 + 熔断
    r2 = _mem_redis()
    h2 = _QuoteHarness(max_errors=1)
    empty = pd.DataFrame()
    with (
        patch("backend.services.akshare.quote.redis_client", r2),
        patch("akshare.stock_zh_a_hist", new=MagicMock(return_value=empty)),
    ):
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
        patch("akshare.stock_zh_a_hist", new=MagicMock(return_value=_hist_df())),
    ):
        res = await h.get_stock_history("SH.600519", num=1)
    assert res["status"] == "success"
    assert len(res["data"]) == 1

    r2 = _mem_redis()
    h2 = _QuoteHarness(max_errors=1)
    with (
        patch("backend.services.akshare.quote.redis_client", r2),
        patch("akshare.stock_zh_a_hist", new=MagicMock(return_value=pd.DataFrame())),
    ):
        res2 = await h2.get_stock_history("SH.600519")
    assert res2["status"] == "error"
    assert h2._circuit_breaker_until > 0
