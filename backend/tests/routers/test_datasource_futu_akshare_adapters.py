"""
Futu / AKShare 数据源适配器单测 (BE-ARCH-05)
============================================

验证:
- Futu / AKShare 适配器实现 DataSourceInterface 关键协议 (name/capabilities/
  is_available/health/fetch)
- ensure_futu_registered / ensure_akshare_registered 幂等注册进 DataSourceRegistry
  （可挂载）
- fetch 在成功 / 失败时正确返回 Result；health 返回 HealthInfo（可感知）
- COMM-01 健康度看板 (health-overview) 现包含 futu / akshare 两张卡片
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.datasource.adapters.akshare import (
    AKShareDataSource,
    ensure_akshare_registered,
)
from backend.services.datasource.adapters.futu import (
    FutuDataSource,
    ensure_futu_registered,
)
from backend.services.datasource.source_registry import datasource_registry


@pytest.fixture(autouse=True)
def clean_source_registry():
    datasource_registry.clear()
    yield
    datasource_registry.clear()


# ─────────────────────────────────────────
#  注册（可挂载）
# ─────────────────────────────────────────


class TestFutuAkshareRegistration:
    def test_register_two_sources(self):
        ensure_futu_registered()
        ensure_akshare_registered()
        # 两者均无条件注册（Futu 经 router HTTP，不依赖本地 SDK）
        assert datasource_registry.has("akshare")
        assert datasource_registry.has("futu")
        assert datasource_registry.get("futu").name == "futu"

    def test_idempotent(self):
        ensure_futu_registered()
        ensure_futu_registered()
        ensure_akshare_registered()
        ensure_akshare_registered()
        names = datasource_registry.list_names()
        assert names.count("akshare") == 1
        assert names.count("futu") == 1


# ─────────────────────────────────────────
#  Futu 适配器协议
# ─────────────────────────────────────────


class TestFutuAdapter:
    def test_protocol_attributes(self):
        a = FutuDataSource()
        assert a.name == "futu"
        assert "QUOTE" in a.capabilities
        assert "OPTION_CHAIN" in a.capabilities
        # is_available 取决于 router 中 futu_master 节点是否存在
        assert a.is_available()

    def test_health_reports_remote_node(self):
        info = asyncio.run(FutuDataSource().health())
        assert info.mode == "remote"
        # futu_master 节点默认存在
        assert "node_url" in info.stats

    def test_fetch_quote_via_router(self):
        a = FutuDataSource()
        fake_resp = {"status": "success", "data": {"last_price": 10.0}}
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_futu",
            new=AsyncMock(return_value=fake_resp),
        ):
            res = asyncio.run(a.fetch("QUOTE", {"ticker": "HK.00700"}))
        assert res.is_success
        assert res.data == {"last_price": 10.0}

    def test_fetch_unsupported_action(self):
        a = FutuDataSource()
        res = asyncio.run(a.fetch("NOPE", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_router_error(self):
        a = FutuDataSource()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_futu",
            new=AsyncMock(return_value={"status": "error", "message": "node down"}),
        ):
            res = asyncio.run(a.fetch("QUOTE", {"ticker": "HK.00700"}))
        assert not res.is_success
        assert res.error.code == "FUTU_FETCH_FAILED"

    def test_fetch_router_exception(self):
        a = FutuDataSource()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_futu",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            res = asyncio.run(a.fetch("QUOTE", {"ticker": "HK.00700"}))
        assert not res.is_success
        assert res.error.code == "FUTU_ROUTER_ERROR"


# ─────────────────────────────────────────
#  AKShare 适配器协议
# ─────────────────────────────────────────


def _patch_akshare_node(monkeypatch, status: str = "healthy"):
    from backend.services.datasource.router import data_source_router

    node = MagicMock()
    node.status = status
    node.url = "http://bj:8001"
    node.error_count = 0
    monkeypatch.setitem(data_source_router._nodes, "akshare_remote", node)


def _patch_fetch_akshare(monkeypatch, return_value):
    from backend.services.datasource.router import data_source_router

    fetch = AsyncMock(return_value=return_value)
    monkeypatch.setattr(data_source_router, "fetch_akshare", fetch)
    return fetch


class TestAKShareAdapter:
    def test_protocol_attributes(self, monkeypatch):
        _patch_akshare_node(monkeypatch)
        a = AKShareDataSource()
        assert a.name == "akshare"
        assert "FUND_FLOW" in a.capabilities
        assert "ECONOMIC_CALENDAR" in a.capabilities
        assert a.is_available()

    def test_health_healthy(self, monkeypatch):
        _patch_akshare_node(monkeypatch, status="healthy")
        info = asyncio.run(AKShareDataSource().health())
        assert info.connected and info.healthy

    def test_health_node_missing(self, monkeypatch):
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        info = asyncio.run(AKShareDataSource().health())
        assert not info.connected
        assert info.last_error == "akshare_remote 节点未配置"

    def test_fetch_fund_flow_success(self, monkeypatch):
        _patch_akshare_node(monkeypatch)
        fetch = _patch_fetch_akshare(monkeypatch, {"status": "success", "data": {"net_inflow": 12.8}})
        res = asyncio.run(AKShareDataSource().fetch("FUND_FLOW", {"direction": "southbound"}))
        assert res.is_success
        assert res.data == {"net_inflow": 12.8}
        assert fetch.call_args.args[0] == "FUND_FLOW"

    def test_fetch_economic_calendar_success(self, monkeypatch):
        _patch_akshare_node(monkeypatch)
        _patch_fetch_akshare(monkeypatch, {"status": "success", "data": [{"event": "FOMC"}]})
        res = asyncio.run(AKShareDataSource().fetch("ECONOMIC_CALENDAR", {"days_ahead": 7}))
        assert res.is_success
        assert res.data == [{"event": "FOMC"}]

    def test_fetch_unsupported_action(self, monkeypatch):
        _patch_akshare_node(monkeypatch)
        res = asyncio.run(AKShareDataSource().fetch("QUOTE", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_remote_error(self, monkeypatch):
        _patch_akshare_node(monkeypatch)
        _patch_fetch_akshare(monkeypatch, {"status": "error", "message": "boom"})
        res = asyncio.run(AKShareDataSource().fetch("FUND_FLOW", {}))
        assert not res.is_success
        assert res.error.code == "AKSHARE_FETCH_FAILED"


# ─────────────────────────────────────────
#  COMM-01 健康度看板集成
# ─────────────────────────────────────────


class TestHealthOverviewIntegration:
    def test_cards_include_futu_and_akshare(self):
        from backend.routers.datasource import get_health_overview

        ensure_futu_registered()
        ensure_akshare_registered()
        board = asyncio.run(get_health_overview())
        names = {c["source"] for c in board["sources"]}
        # futu / akshare 均无条件注册
        assert "futu" in names
        assert "akshare" in names
