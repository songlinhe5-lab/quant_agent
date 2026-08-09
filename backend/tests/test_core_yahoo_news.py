"""backend.core.yahoo_news 测试（07j: 直连 Yahoo 收口为 Router 远程代理）。

架构背景：港股新闻兜底从主服务直连 query2.finance.yahoo.com 收口为
经 DataSourceRouter 联邦 US-YF-A/B 子服务 yfinance NEWS action（BE-ARCH-07j）。
本测试验证：
1. 不再直连外部域名，而是经 router.fetch_yfinance 代理；
2. 字段归一化与 Finnhub 对齐（category/datetime/headline/summary/source/url/related）；
3. 异常与空返回优雅降级为 []。
"""

import pytest

from backend.core import yahoo_news


class _FakeRouter:
    """记录调用参数并返回预置新闻列表。"""

    def __init__(self, data):
        self._data = data
        self.calls = []

    async def fetch_yfinance(self, action, symbol=None, limit=15):
        self.calls.append((action, symbol, limit))
        return {"status": "success", "data": self._data}


@pytest.mark.asyncio
async def test_fetch_yahoo_news_routes_via_router(monkeypatch):
    # 子服务 yfinance NEWS 返回归一化后的 snake_case 字段
    fake = _FakeRouter(
        [
            {
                "title": "Tencent beats estimates",
                "publisher": "Reuters",
                "provider_publish_time": 1700000000,
                "link": "https://example.com/1",
            }
        ]
    )
    monkeypatch.setattr(yahoo_news, "data_source_router", fake)

    out = await yahoo_news.fetch_yahoo_news("HK.00700")
    # 必须走 router，而非直连外部域名
    assert fake.calls and fake.calls[0][0] == "NEWS"
    # HK.00700 -> Yahoo 后缀式 0700.HK（去前导 0 补 4 位）
    assert fake.calls[0][1] == "0700.HK"
    assert len(out) == 1
    item = out[0]
    assert item["headline"] == "Tencent beats estimates"
    assert item["source"] == "Reuters"
    assert item["summary"] == "Reuters"
    assert item["datetime"] == 1700000000
    assert item["url"] == "https://example.com/1"
    assert item["related"] == "HK.00700"
    assert item["category"] == "company"


@pytest.mark.asyncio
async def test_fetch_yahoo_news_dot_hk_form(monkeypatch):
    fake = _FakeRouter([])
    monkeypatch.setattr(yahoo_news, "data_source_router", fake)
    await yahoo_news.fetch_yahoo_news("00700.HK")
    assert fake.calls[0][1] == "0700.HK"


@pytest.mark.asyncio
async def test_fetch_yahoo_news_handles_router_error(monkeypatch):
    class _ErrRouter:
        async def fetch_yfinance(self, action, symbol=None, limit=15):
            raise RuntimeError("yfinance subservice down")

    monkeypatch.setattr(yahoo_news, "data_source_router", _ErrRouter())
    # 失败应优雅返回空列表，不抛异常
    assert await yahoo_news.fetch_yahoo_news("AAPL") == []


@pytest.mark.asyncio
async def test_fetch_yahoo_news_empty(monkeypatch):
    fake = _FakeRouter([])
    monkeypatch.setattr(yahoo_news, "data_source_router", fake)
    assert await yahoo_news.fetch_yahoo_news("AAPL") == []


@pytest.mark.asyncio
async def test_fetch_yahoo_news_unsuccessful_status(monkeypatch):
    class _FailRouter:
        async def fetch_yfinance(self, action, symbol=None, limit=15):
            return {"status": "error", "message": "source unavailable"}

    monkeypatch.setattr(yahoo_news, "data_source_router", _FailRouter())
    assert await yahoo_news.fetch_yahoo_news("AAPL") == []
