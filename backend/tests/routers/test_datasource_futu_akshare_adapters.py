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
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.datasource import Result
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
        # akshare 必定注册；futu 仅在 SDK/OpenD 可用时注册(否则静默跳过)
        assert datasource_registry.has("akshare")
        if datasource_registry.has("futu"):
            assert datasource_registry.get("futu").name == "futu"

    def test_idempotent(self):
        ensure_futu_registered()
        ensure_futu_registered()
        ensure_akshare_registered()
        ensure_akshare_registered()
        names = datasource_registry.list_names()
        assert names.count("akshare") == 1
        # futu 若已注册则只应有一个实例
        assert names.count("futu") in (0, 1)


# ─────────────────────────────────────────
#  Futu 适配器协议
# ─────────────────────────────────────────


def _mock_futu(connected: bool = True):
    svc = MagicMock()
    svc.status = "CONNECTED" if connected else "DISCONNECTED"
    svc.error_msg = "" if connected else "OpenD 未连接"
    svc.get_quote = AsyncMock(return_value={"status": "success", "data": {"price": 1.0}})
    svc.get_history = AsyncMock(return_value={"status": "success", "data": [{"c": 1}]})
    svc.get_fund_flow = AsyncMock(return_value={"status": "success", "data": {"net": 1}})
    svc.get_option_chain = AsyncMock(return_value={"status": "success", "data": [{"o": 1}]})
    svc.get_fundamental = AsyncMock(return_value={"status": "success", "data": {"pe": 1}})
    return svc


class TestFutuAdapter:
    def test_protocol_attributes(self):
        a = FutuDataSource(service=_mock_futu())
        assert a.name == "futu"
        assert "QUOTE" in a.capabilities
        assert "OPTION_CHAIN" in a.capabilities
        assert a.is_available()

    def test_is_available_when_disconnected(self):
        a = FutuDataSource(service=_mock_futu(connected=False))
        assert not a.is_available()

    def test_health_connected(self):
        info = asyncio.run(FutuDataSource(service=_mock_futu()).health())
        assert info.connected and info.healthy

    def test_health_disconnected(self):
        info = asyncio.run(FutuDataSource(service=_mock_futu(connected=False)).health())
        assert not info.connected
        assert info.last_error == "OpenD 未连接"

    def test_fetch_quote_success(self):
        a = FutuDataSource(service=_mock_futu())
        res = asyncio.run(a.fetch("QUOTE", {"ticker": "00700"}))
        assert isinstance(res, Result)
        assert res.is_success
        assert res.data == {"price": 1.0}

    def test_fetch_unsupported_action(self):
        a = FutuDataSource(service=_mock_futu())
        res = asyncio.run(a.fetch("NOPE", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_when_disconnected(self):
        a = FutuDataSource(service=_mock_futu(connected=False))
        res = asyncio.run(a.fetch("QUOTE", {"ticker": "00700"}))
        assert not res.is_success
        assert res.error.code == "FUTU_DISCONNECTED"

    def test_fetch_service_error(self):
        svc = _mock_futu()
        svc.get_quote = AsyncMock(side_effect=RuntimeError("boom"))
        a = FutuDataSource(service=svc)
        res = asyncio.run(a.fetch("QUOTE", {"ticker": "00700"}))
        assert not res.is_success
        assert res.error.code == "FUTU_ERROR"


# ─────────────────────────────────────────
#  AKShare 适配器协议
# ─────────────────────────────────────────


def _mock_akshare(status: str = "healthy", open_cb: bool = False):
    svc = MagicMock()
    svc.get_health_status = MagicMock(return_value={"status": status, "mode": "direct", "message": "ok"})
    cb_state = MagicMock()
    cb_state.value = "open" if open_cb else "closed"
    svc.cb = MagicMock()
    svc.cb.get_state = MagicMock(return_value=cb_state)
    svc.get_southbound_flow = AsyncMock(return_value={"status": "success", "data": {"net_inflow": 12.8}})
    svc.get_northbound_flow = AsyncMock(return_value={"status": "success", "data": {"net_inflow": -5.3}})
    svc.get_hk_stock_connect_flow = AsyncMock(return_value={"status": "success", "data": {"channels": []}})
    svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": [{"event": "FOMC"}]})
    return svc


class TestAKShareAdapter:
    def test_protocol_attributes(self):
        a = AKShareDataSource(service=_mock_akshare())
        assert a.name == "akshare"
        assert "FUND_FLOW" in a.capabilities
        assert "ECONOMIC_CALENDAR" in a.capabilities
        assert a.is_available()

    def test_is_available_when_circuit_open(self):
        a = AKShareDataSource(service=_mock_akshare(status="circuit_open"))
        assert not a.is_available()

    def test_health_healthy(self):
        info = asyncio.run(AKShareDataSource(service=_mock_akshare()).health())
        assert info.connected and info.healthy

    def test_health_throttled_reflected(self):
        info = asyncio.run(AKShareDataSource(service=_mock_akshare(open_cb=True)).health())
        assert info.rate_limit_status.is_throttled

    def test_fetch_fund_flow_southbound(self):
        a = AKShareDataSource(service=_mock_akshare())
        res = asyncio.run(a.fetch("FUND_FLOW", {"direction": "southbound"}))
        assert res.is_success
        assert res.data == {"net_inflow": 12.8}

    def test_fetch_economic_calendar(self):
        a = AKShareDataSource(service=_mock_akshare())
        res = asyncio.run(a.fetch("ECONOMIC_CALENDAR", {"days_ahead": 7}))
        assert res.is_success
        assert res.data == [{"event": "FOMC"}]

    def test_fetch_unsupported_action(self):
        a = AKShareDataSource(service=_mock_akshare())
        res = asyncio.run(a.fetch("QUOTE", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"


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
        # akshare 必然出现; futu 在 SDK/OpenD 不可用环境会跳过注册
        assert "akshare" in names
        if datasource_registry.has("futu"):
            assert "futu" in names
