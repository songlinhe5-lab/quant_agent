"""
搜索 / 网页抓取数据源适配器单测 (BE-ARCH-05)
==========================================

验证:
- Tavily / Bocha / Jina 适配器实现 DataSourceInterface 关键协议 (name/capabilities/
  is_available/health/fetch)
- ensure_search_sources_registered 幂等注册进 DataSourceRegistry（可挂载）
- fetch 在成功 / 失败 / 无 key / 参数缺失时正确返回 Result（可感知）
- /health-overview 看板现包含三源卡片
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.datasource import Result
from backend.services.datasource.adapters.search import (
    BochaDataSource,
    JinaDataSource,
    TavilyDataSource,
    ensure_search_sources_registered,
)
from backend.services.datasource.source_registry import datasource_registry


@pytest.fixture(autouse=True)
def clean_source_registry():
    datasource_registry.clear()
    yield
    datasource_registry.clear()


def _mock_async_client(json_data=None, text=None):
    """构造一个支持 async with 的 httpx.AsyncClient mock。"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    if text is not None:
        resp.text = text
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.get = AsyncMock(return_value=resp)
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    return cm


# ─────────────────────────────────────────
#  注册（可挂载）
# ─────────────────────────────────────────


class TestSearchRegistration:
    def test_register_three_sources(self):
        registered = ensure_search_sources_registered()
        assert set(registered) == {"tavily", "bocha", "jina"}
        for n in ("tavily", "bocha", "jina"):
            assert datasource_registry.has(n)

    def test_idempotent(self):
        ensure_search_sources_registered()
        ensure_search_sources_registered()
        assert len(datasource_registry.list_names()) == 3


# ─────────────────────────────────────────
#  适配器协议与 health
# ─────────────────────────────────────────


class TestTavilyAdapter:
    def test_protocol_attributes(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv-key"}):
            a = TavilyDataSource()
            assert a.name == "tavily"
            assert a.capabilities == ["WEB_SEARCH"]
            assert a.is_available()

    def test_health_with_key(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv-key"}):
            info = asyncio.run(TavilyDataSource().health())
            assert info.connected and info.healthy

    def test_health_without_key(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("TAVILY_API_KEY", None)
            info = asyncio.run(TavilyDataSource().health())
            assert not info.connected
            assert info.last_error == "TAVILY_API_KEY 未配置"

    def test_fetch_unsupported_action(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv-key"}):
            res = asyncio.run(TavilyDataSource().fetch("quote", {}))
            assert not res.is_success
            assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_no_key(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("TAVILY_API_KEY", None)
            res = asyncio.run(TavilyDataSource().fetch("WEB_SEARCH", {"query": "x"}))
            assert not res.is_success
            assert res.error.code == "TAVILY_NO_KEY"

    def test_fetch_empty_query(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv-key"}):
            res = asyncio.run(TavilyDataSource().fetch("WEB_SEARCH", {}))
            assert not res.is_success
            assert res.error.code == "TAVILY_EMPTY_QUERY"

    def test_fetch_success(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv-key"}):
            cm = _mock_async_client(json_data={"results": [{"title": "T", "url": "u", "content": "c"}]})
            with patch("backend.services.datasource.adapters.search.httpx.AsyncClient", return_value=cm):
                res = asyncio.run(TavilyDataSource().fetch("WEB_SEARCH", {"query": "apple", "max_results": 3}))
            assert isinstance(res, Result)
            assert res.is_success
            assert res.data == [{"title": "T", "href": "u", "body": "c"}]


class TestBochaAdapter:
    def test_protocol_attributes(self):
        with patch.dict("os.environ", {"BOCHA_API_KEY": "bocha-key"}):
            a = BochaDataSource()
            assert a.name == "bocha"
            assert a.capabilities == ["WEB_SEARCH"]
            assert a.is_available()

    def test_health_without_key(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("BOCHA_API_KEY", None)
            info = asyncio.run(BochaDataSource().health())
            assert not info.connected

    def test_fetch_success(self):
        with patch.dict("os.environ", {"BOCHA_API_KEY": "bocha-key"}):
            cm = _mock_async_client(
                json_data={"data": {"webPages": {"value": [{"name": "N", "url": "u", "snippet": "s"}]}}}
            )
            with patch("backend.services.datasource.adapters.search.httpx.AsyncClient", return_value=cm):
                res = asyncio.run(BochaDataSource().fetch("WEB_SEARCH", {"query": "腾讯", "max_results": 2}))
            assert res.is_success
            assert res.data == [{"title": "N", "href": "u", "body": "s"}]


class TestJinaAdapter:
    def test_protocol_attributes(self):
        a = JinaDataSource()
        assert a.name == "jina"
        assert a.capabilities == ["WEB_SCRAPE"]
        # Jina Reader 公网可用，无需 key 即 available
        assert a.is_available()

    def test_health_always_connected(self):
        info = asyncio.run(JinaDataSource().health())
        assert info.connected and info.healthy
        assert info.stats["api_key_configured"] is False

    def test_health_reports_key_configured(self):
        with patch.dict("os.environ", {"JINA_API_KEY": "jina-key"}):
            info = asyncio.run(JinaDataSource().health())
            assert info.stats["api_key_configured"] is True

    def test_fetch_unsupported_action(self):
        res = asyncio.run(JinaDataSource().fetch("quote", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_empty_url(self):
        res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {}))
        assert not res.is_success
        assert res.error.code == "JINA_EMPTY_URL"

    def test_fetch_invalid_url(self):
        res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {"url": "ftp://x"}))
        assert not res.is_success
        assert res.error.code == "JINA_INVALID_URL"

    def test_fetch_success(self):
        long_text = "# Example Domain\n\nThis domain is for use in illustrative examples in documents. " * 10
        cm = _mock_async_client(text=long_text)
        with patch("backend.services.datasource.adapters.search.httpx.AsyncClient", return_value=cm):
            res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {"url": "https://example.com"}))
        assert res.is_success
        assert res.data["content"] == long_text

    def test_fetch_blocked(self):
        cm = _mock_async_client(text="Just a moment")
        with patch("backend.services.datasource.adapters.search.httpx.AsyncClient", return_value=cm):
            res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {"url": "https://cf-protected.com"}))
        assert not res.is_success
        assert res.error.code == "JINA_BLOCKED"


# ─────────────────────────────────────────
#  /health-overview 看板集成
# ─────────────────────────────────────────


class TestHealthOverviewIntegration:
    def test_search_sources_appear_in_overview(self):
        from backend.routers.datasource import get_health_overview

        # 确保双 key 配置以让 tavily/bocha 标记为 connected
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv", "BOCHA_API_KEY": "bocha"}, clear=False):
            overview = asyncio.run(get_health_overview())
        names = {c["source"] for c in overview["sources"]}
        assert {"tavily", "bocha", "jina"} <= names
        assert overview["total"] >= 3

    def test_all_search_sources_connected_with_keys(self):
        from backend.routers.datasource import get_health_overview

        # 配置有效 key 后，三源 mounted AND health.connected 均应 True
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tv", "BOCHA_API_KEY": "bocha"}, clear=False):
            overview = asyncio.run(get_health_overview())
        cards = {c["source"]: c for c in overview["sources"]}
        assert cards["tavily"]["connected"] is True
        assert cards["bocha"]["connected"] is True
        assert cards["jina"]["connected"] is True

    def test_tavily_not_connected_without_key(self):
        from backend.routers.datasource import get_health_overview

        # BE-ARCH-05 可感知：tavily 无 key 时 mounted 但 health.connected=False
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}, clear=False):
            overview = asyncio.run(get_health_overview())
        cards = {c["source"]: c for c in overview["sources"]}
        assert cards["tavily"]["connected"] is False
        assert cards["tavily"]["health_error"] is not None
        # jina 无需 key，仍应 connected
        assert cards["jina"]["connected"] is True
