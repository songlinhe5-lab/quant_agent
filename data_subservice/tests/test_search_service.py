"""搜索/抓取数据源单元测试 (Tavily/Bocha/Jina 各分支)。

httpx.AsyncClient 经 mock 替换, 不触真实外部 API。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice._internal import search as search_mod
from data_subservice._internal.search import (
    BochaService,
    JinaService,
    TavilyService,
    bocha_service,
    jina_service,
    tavily_service,
)


def _mock_client(status_code=200, json_data=None, text="ok content"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    client = AsyncMock()
    enter = client.__aenter__.return_value
    enter.get = AsyncMock(return_value=resp)
    enter.post = AsyncMock(return_value=resp)
    return client


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    monkeypatch.delenv("JINA_API_KEY", raising=False)


class TestTavily:
    @pytest.mark.asyncio
    async def test_no_key(self):
        assert "未配置" in (await TavilyService().search("q"))["message"]

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        with patch.object(
            search_mod.httpx,
            "AsyncClient",
            return_value=_mock_client(200, {"results": [{"title": "t", "url": "u", "content": "c"}]}),
        ):
            out = await TavilyService().search("q")
        assert out["status"] == "success"
        assert out["data"][0]["title"] == "t"

    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await TavilyService().search("q")
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(500)):
            out = await TavilyService().search("q")
        assert "500" in out["message"]

    @pytest.mark.asyncio
    async def test_exception(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        client = AsyncMock()
        client.__aenter__.return_value.post = AsyncMock(side_effect=RuntimeError("net"))
        with patch.object(search_mod.httpx, "AsyncClient", return_value=client):
            out = await TavilyService().search("q")
        assert "request failed" in out["message"]


class TestBocha:
    @pytest.mark.asyncio
    async def test_no_key(self):
        assert "未配置" in (await BochaService().search("q"))["message"]

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("BOCHA_API_KEY", "k")
        payload = {"data": {"webPages": {"value": [{"name": "n", "url": "u", "snippet": "s"}]}}}
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(200, payload)):
            out = await BochaService().search("q")
        assert out["status"] == "success"
        assert out["data"][0]["title"] == "n"

    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("BOCHA_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await BochaService().search("q")
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self, monkeypatch):
        monkeypatch.setenv("BOCHA_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(403)):
            out = await BochaService().search("q")
        assert "403" in out["message"]


class TestJina:
    @pytest.mark.asyncio
    async def test_no_key_still_requests(self, monkeypatch):
        # 真实 JinaService 无「未配置」拦截分支，无 key 仍走协议校验与请求
        long_text = "x" * 60
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(200, text=long_text)):
            out = await JinaService().scrape("https://example.com")
        assert out["status"] == "success"
        assert out["data"]["content"] == long_text

    @pytest.mark.asyncio
    async def test_bad_protocol(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        assert "http(s)" in (await JinaService().scrape("ftp://x"))["message"]

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        long_text = "x" * 60
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(200, text=long_text)):
            out = await JinaService().scrape("https://example.com")
        assert out["status"] == "success"
        assert out["data"]["content"] == long_text

    @pytest.mark.asyncio
    async def test_short_content(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(200, text="too short")):
            out = await JinaService().scrape("https://example.com")
        assert "过短" in out["message"]

    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await JinaService().scrape("https://example.com")
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        with patch.object(search_mod.httpx, "AsyncClient", return_value=_mock_client(500)):
            out = await JinaService().scrape("https://example.com")
        assert "500" in out["message"]

    @pytest.mark.asyncio
    async def test_exception(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        client = AsyncMock()
        client.__aenter__.return_value.get = AsyncMock(side_effect=RuntimeError("net"))
        with patch.object(search_mod.httpx, "AsyncClient", return_value=client):
            out = await JinaService().scrape("https://example.com")
        assert "request failed" in out["message"]


def test_module_singletons():
    assert isinstance(tavily_service, TavilyService)
    assert isinstance(bocha_service, BochaService)
    assert isinstance(jina_service, JinaService)
