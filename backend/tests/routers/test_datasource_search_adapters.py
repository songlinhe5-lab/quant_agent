"""
搜索 / 网页抓取数据源适配器单测 (BE-ARCH-05)
==========================================

验证:
- Tavily / Bocha / Jina 适配器实现 DataSourceInterface 关键协议 (name/capabilities/
  is_available/health/fetch)
- ensure_search_sources_registered 幂等注册进 DataSourceRegistry（可挂载）
- fetch 经 data_source_router.fetch_search() 远程调用 data_subservice（仅远程，不再直连外部 API）
- /health-overview 看板现包含三源卡片
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

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


def _patch_search_node(monkeypatch, status: str = "healthy"):
    from backend.services.datasource.router import data_source_router

    node = MagicMock()
    node.status = status
    node.url = "http://localhost:8001"
    node.error_count = 0
    monkeypatch.setitem(data_source_router._nodes, "search_master", node)


def _patch_fetch_search(monkeypatch, return_value):
    from backend.services.datasource.router import data_source_router

    fetch = AsyncMock(return_value=return_value)
    monkeypatch.setattr(data_source_router, "fetch_search", fetch)
    return fetch


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
    def test_protocol_attributes(self, monkeypatch):
        _patch_search_node(monkeypatch)
        a = TavilyDataSource()
        assert a.name == "tavily"
        assert a.capabilities == ["WEB_SEARCH"]
        assert a.is_available()

    def test_health_with_node(self, monkeypatch):
        _patch_search_node(monkeypatch, status="healthy")
        info = asyncio.run(TavilyDataSource().health())
        assert info.connected and info.healthy

    def test_health_node_missing(self, monkeypatch):
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        info = asyncio.run(TavilyDataSource().health())
        assert not info.connected
        assert info.last_error == "search_master 节点未配置"

    def test_fetch_unsupported_action(self, monkeypatch):
        _patch_search_node(monkeypatch)
        res = asyncio.run(TavilyDataSource().fetch("quote", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_success(self, monkeypatch):
        _patch_search_node(monkeypatch)
        fetch = _patch_fetch_search(
            monkeypatch, {"status": "success", "data": [{"title": "T", "href": "u", "body": "c"}]}
        )
        res = asyncio.run(TavilyDataSource().fetch("WEB_SEARCH", {"query": "apple", "max_results": 3}))
        assert isinstance(res, Result)
        assert res.is_success
        assert res.data == [{"title": "T", "href": "u", "body": "c"}]
        # source 透传为 tavily
        assert fetch.call_args.args[0] == "tavily"


class TestBochaAdapter:
    def test_protocol_attributes(self, monkeypatch):
        _patch_search_node(monkeypatch)
        a = BochaDataSource()
        assert a.name == "bocha"
        assert a.capabilities == ["WEB_SEARCH"]
        assert a.is_available()

    def test_fetch_success(self, monkeypatch):
        _patch_search_node(monkeypatch)
        fetch = _patch_fetch_search(
            monkeypatch, {"status": "success", "data": [{"title": "N", "href": "u", "body": "s"}]}
        )
        res = asyncio.run(BochaDataSource().fetch("WEB_SEARCH", {"query": "腾讯", "max_results": 2}))
        assert res.is_success
        assert res.data == [{"title": "N", "href": "u", "body": "s"}]
        assert fetch.call_args.args[0] == "bocha"


class TestJinaAdapter:
    def test_protocol_attributes(self, monkeypatch):
        _patch_search_node(monkeypatch)
        a = JinaDataSource()
        assert a.name == "jina"
        assert a.capabilities == ["WEB_SCRAPE"]
        assert a.is_available()

    def test_fetch_unsupported_action(self, monkeypatch):
        _patch_search_node(monkeypatch)
        res = asyncio.run(JinaDataSource().fetch("quote", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_success(self, monkeypatch):
        _patch_search_node(monkeypatch)
        fetch = _patch_fetch_search(monkeypatch, {"status": "success", "data": {"content": "example"}})
        res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {"url": "https://example.com"}))
        assert res.is_success
        assert res.data == {"content": "example"}
        assert fetch.call_args.args[0] == "jina"

    def test_fetch_remote_error(self, monkeypatch):
        _patch_search_node(monkeypatch)
        _patch_fetch_search(monkeypatch, {"status": "error", "message": "boom"})
        res = asyncio.run(JinaDataSource().fetch("WEB_SCRAPE", {"url": "https://x.com"}))
        assert not res.is_success
        assert res.error.code == "JINA_FETCH_FAILED"


# ─────────────────────────────────────────
#  /health-overview 看板集成
# ─────────────────────────────────────────


class TestHealthOverviewIntegration:
    def test_search_sources_appear_in_overview(self, monkeypatch):
        from backend.routers.datasource import get_health_overview

        _patch_search_node(monkeypatch, status="healthy")
        overview = asyncio.run(get_health_overview())
        names = {c["source"] for c in overview["sources"]}
        assert {"tavily", "bocha", "jina"} <= names
        assert overview["total"] >= 3

    def test_all_search_sources_connected_with_node(self, monkeypatch):
        from backend.routers.datasource import get_health_overview

        _patch_search_node(monkeypatch, status="healthy")
        overview = asyncio.run(get_health_overview())
        cards = {c["source"]: c for c in overview["sources"]}
        assert cards["tavily"]["connected"] is True
        assert cards["bocha"]["connected"] is True
        assert cards["jina"]["connected"] is True

    def test_search_sources_not_connected_without_node(self, monkeypatch):
        from backend.routers.datasource import get_health_overview
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        overview = asyncio.run(get_health_overview())
        cards = {c["source"]: c for c in overview["sources"]}
        assert cards["tavily"]["connected"] is False
