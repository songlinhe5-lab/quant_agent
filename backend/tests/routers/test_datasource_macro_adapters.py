"""
宏观数据源适配器单测 (BE-ARCH-05)
=================================

验证:
- FRED / DBnomics / RBI 适配器实现 DataSourceInterface 关键协议 (name/capabilities/
  is_available/health/fetch)
- ensure_macro_sources_registered 幂等注册进 DataSourceRegistry（可挂载）
- fetch 经 data_source_router 远程调用 data_subservice（仅远程，无本地服务）
- 投票看板 connected 现包含三源并带中文标签
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.datasource import Result
from backend.services.datasource.adapters.macro import (
    DbnomicsDataSource,
    FREDDataSource,
    RBIDataSource,
    ensure_macro_sources_registered,
)
from backend.services.datasource.source_registry import datasource_registry


@pytest.fixture(autouse=True)
def clean_source_registry():
    datasource_registry.clear()
    yield
    datasource_registry.clear()


def _patch_node(monkeypatch, node_name: str, status: str = "healthy"):
    from backend.services.datasource.router import data_source_router

    node = MagicMock()
    node.status = status
    node.url = "http://localhost:8001"
    node.error_count = 0
    monkeypatch.setitem(data_source_router._nodes, node_name, node)


# ─────────────────────────────────────────
#  注册（可挂载）
# ─────────────────────────────────────────


class TestMacroRegistration:
    def test_register_three_sources(self):
        registered = ensure_macro_sources_registered()
        assert set(registered) == {"fred", "dbnomics", "rbi"}
        for n in ("fred", "dbnomics", "rbi"):
            assert datasource_registry.has(n)

    def test_idempotent(self):
        ensure_macro_sources_registered()
        ensure_macro_sources_registered()
        # 多次注册不应产生重复实例
        assert len(datasource_registry.list_names()) == 3


# ─────────────────────────────────────────
#  适配器协议
# ─────────────────────────────────────────


class TestFREDAdapter:
    def test_protocol_attributes(self, monkeypatch):
        _patch_node(monkeypatch, "fred_master")
        a = FREDDataSource()
        assert a.name == "fred"
        assert "macro_series" in a.capabilities
        assert "economic_calendar" in a.capabilities

    @pytest.mark.asyncio
    async def test_fetch_macro_series_success(self, monkeypatch):
        _patch_node(monkeypatch, "fred_master")
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "success", "data": [{"v": 1.0}]})
        monkeypatch.setattr(data_source_router, "fetch_fred", fetch)
        a = FREDDataSource()
        res = await a.fetch("macro_series", {"series_id": "DGS10", "limit": 10})
        assert isinstance(res, Result)
        assert res.is_success
        assert res.data == [{"v": 1.0}]

    def test_fetch_unsupported_action(self, monkeypatch):
        _patch_node(monkeypatch, "fred_master")
        a = FREDDataSource()
        res = asyncio.run(a.fetch("quote", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    @pytest.mark.asyncio
    async def test_fetch_remote_error(self, monkeypatch):
        _patch_node(monkeypatch, "fred_master")
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "error", "message": "boom"})
        monkeypatch.setattr(data_source_router, "fetch_fred", fetch)
        a = FREDDataSource()
        res = await a.fetch("macro_series", {"series_id": "DGS10"})
        assert not res.is_success
        assert res.error.code == "FRED_FETCH_FAILED"

    def test_health_healthy_node(self, monkeypatch):
        _patch_node(monkeypatch, "fred_master", status="healthy")
        a = FREDDataSource()
        info = asyncio.run(a.health())
        assert info.connected and info.healthy

    def test_health_node_missing(self, monkeypatch):
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        a = FREDDataSource()
        info = asyncio.run(a.health())
        assert not info.connected
        assert info.last_error == "fred_master 节点未配置"


class TestDbnomicsAndRBIAdapter:
    def test_dbnomics_protocol(self, monkeypatch):
        _patch_node(monkeypatch, "dbnomics_master")
        a = DbnomicsDataSource()
        assert a.name == "dbnomics"
        assert a.capabilities == ["economic_calendar"]
        assert a.is_available()

    def test_rbi_protocol(self, monkeypatch):
        _patch_node(monkeypatch, "rbi_master")
        a = RBIDataSource()
        assert a.name == "rbi"
        assert a.capabilities == ["economic_calendar"]
        assert a.is_available()

    @pytest.mark.asyncio
    async def test_dbnomics_fetch_success(self, monkeypatch):
        _patch_node(monkeypatch, "dbnomics_master")
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "success", "data": [{"event": "X"}]})
        monkeypatch.setattr(data_source_router, "fetch_dbnomics", fetch)
        a = DbnomicsDataSource()
        res = await a.fetch("economic_calendar", {"days_ahead": 7})
        assert res.is_success
        assert res.data == [{"event": "X"}]

    @pytest.mark.asyncio
    async def test_rbi_fetch_success(self, monkeypatch):
        _patch_node(monkeypatch, "rbi_master")
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "success", "data": [{"event": "Y"}]})
        monkeypatch.setattr(data_source_router, "fetch_rbi", fetch)
        a = RBIDataSource()
        res = await a.fetch("economic_calendar", {"days_ahead": 7})
        assert res.is_success


# ─────────────────────────────────────────
#  投票看板分类
# ─────────────────────────────────────────


class _FakePipe:
    def get(self, *a, **k):
        return None

    async def execute(self):
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeRedis:
    def pipeline(self):
        return _FakePipe()

    async def get(self, *a, **k):
        return None


class TestVoteBoardConnected:
    def test_macro_sources_in_connected_with_labels(self, monkeypatch):
        from backend.services.datasource.router import data_source_router

        for n in ("fred_master", "dbnomics_master", "rbi_master"):
            node = MagicMock()
            node.status = "healthy"
            node.url = "http://localhost:8001"
            node.error_count = 0
            monkeypatch.setitem(data_source_router._nodes, n, node)

        from backend.routers import datasource_vote

        datasource_vote.redis_client = _FakeRedis()
        board = asyncio.run(datasource_vote.get_vote_board(current_user=MagicMock(username="tester")))

        connected_names = {c["name"] for c in board["connected"]}
        assert {"fred", "dbnomics", "rbi"} <= connected_names

        fred_card = next(c for c in board["connected"] if c["name"] == "fred")
        assert fred_card["label"] == "FRED 宏观经济"
        assert fred_card["desc"]

        developing_names = {d["name"] for d in board["developing"]}
        assert "fred" not in developing_names
        assert "dbnomics" not in developing_names
        assert "rbi" not in developing_names
        assert "polygon" in developing_names
