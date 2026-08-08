"""backend.core.yahoo_news 测试（原 FinnhubService._get_proxy / _fallback_yahoo_news 迁移）。

架构背景：港股新闻兜底从 FinnhubService 抽出为独立模块，彻底与 FinnhubService 解耦
（BE-ARCH-01 边界约束）。本测试验证代理轮换逻辑与字段归一化（与 Finnhub 字段对齐）。
"""

import pytest

from backend.core import yahoo_news


def test_get_proxy_empty_pool(monkeypatch):
    monkeypatch.delenv("PROXY_POOL", raising=False)
    assert yahoo_news._get_proxy() is None


def test_get_proxy_random_rotation(monkeypatch):
    monkeypatch.setenv("PROXY_POOL", "http://a:1, http://b:2 ,http://c:3")
    seen = set()
    for _ in range(20):
        seen.add(yahoo_news._get_proxy())
    # 随机轮换应至少命中多个代理
    assert len(seen) >= 2


def test_get_proxy_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv("PROXY_POOL", ",, http://a:1 ,,")
    assert yahoo_news._get_proxy() == "http://a:1"


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload, **kwargs):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return _FakeResp(self._payload)


@pytest.mark.asyncio
async def test_fetch_yahoo_news_normalizes_fields(monkeypatch):
    payload = {
        "news": [
            {
                "title": "Tencent beats estimates",
                "publisher": "Reuters",
                "providerPublishTime": 1700000000,
                "link": "https://example.com/1",
            }
        ]
    }
    monkeypatch.setattr(yahoo_news.httpx, "AsyncClient", lambda **k: _FakeClient(payload, **k))

    out = await yahoo_news.fetch_yahoo_news("HK.00700")
    assert len(out) == 1
    item = out[0]
    assert item["headline"] == "Tencent beats estimates"
    assert item["source"] == "Reuters"
    assert item["datetime"] == 1700000000
    assert item["url"] == "https://example.com/1"
    assert item["related"] == "HK.00700"
    assert item["category"] == "company"


@pytest.mark.asyncio
async def test_fetch_yahoo_news_hk_ticker_format(monkeypatch):
    captured = {}

    class _CaptureClient:
        def __init__(self, payload, **kwargs):
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            return _FakeResp({"news": []})

    monkeypatch.setattr(yahoo_news.httpx, "AsyncClient", lambda **k: _CaptureClient({}, **k))
    await yahoo_news.fetch_yahoo_news("HK.00700")
    # HK.00700 -> Yahoo 格式 0700.HK（去掉前导 0 并补 4 位）
    assert "0700.HK" in captured["url"]


@pytest.mark.asyncio
async def test_fetch_yahoo_news_handles_error(monkeypatch):
    class _ErrClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            raise RuntimeError("network down")

    monkeypatch.setattr(yahoo_news.httpx, "AsyncClient", _ErrClient)
    # 失败应优雅返回空列表，不抛异常
    assert await yahoo_news.fetch_yahoo_news("AAPL") == []


@pytest.mark.asyncio
async def test_fetch_yahoo_news_empty(monkeypatch):
    monkeypatch.setattr(yahoo_news.httpx, "AsyncClient", lambda **k: _FakeClient({"news": []}, **k))
    assert await yahoo_news.fetch_yahoo_news("AAPL") == []
