"""
宏观数据源适配器单测 (BE-ARCH-05)
=================================

验证:
- FRED / DBnomics / RBI 适配器实现 DataSourceInterface 关键协议 (name/capabilities/
  is_available/health/fetch)
- ensure_macro_sources_registered 幂等注册进 DataSourceRegistry（可挂载）
- fetch 在成功 / 失败时正确返回 Result；health 返回 HealthInfo（可感知）
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


def _mock_fred(key: str = "KEY"):
    svc = MagicMock()
    svc.api_key = key
    svc.get_series_observations = AsyncMock(return_value={"status": "success", "data": [{"v": 1.0}]})
    svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": [{"event": "CPI"}]})
    return svc


def _mock_calendar():
    svc = MagicMock()
    svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": [{"event": "X"}]})
    return svc


class TestFREDAdapter:
    def test_protocol_attributes(self):
        a = FREDDataSource(service=_mock_fred())
        assert a.name == "fred"
        assert "macro_series" in a.capabilities
        assert "economic_calendar" in a.capabilities

    def test_fetch_macro_series_success(self):
        a = FREDDataSource(service=_mock_fred())
        res = asyncio.run(a.fetch("macro_series", {"series_id": "DGS10", "limit": 10}))
        assert isinstance(res, Result)
        assert res.is_success
        assert res.data == [{"v": 1.0}]

    def test_fetch_unsupported_action(self):
        a = FREDDataSource(service=_mock_fred())
        res = asyncio.run(a.fetch("quote", {}))
        assert not res.is_success
        assert res.error.code == "UNSUPPORTED_ACTION"

    def test_fetch_no_api_key(self):
        a = FREDDataSource(service=_mock_fred(key=""))
        res = asyncio.run(a.fetch("macro_series", {"series_id": "DGS10"}))
        assert not res.is_success
        assert res.error.code == "FRED_NO_KEY"

    def test_health_with_key(self):
        a = FREDDataSource(service=_mock_fred())
        info = asyncio.run(a.health())
        assert info.connected and info.healthy

    def test_health_without_key(self):
        a = FREDDataSource(service=_mock_fred(key=""))
        info = asyncio.run(a.health())
        assert not info.connected
        assert info.last_error == "FRED_API_KEY 未配置"


class TestDbnomicsAndRBIAdapter:
    def test_dbnomics_protocol(self):
        a = DbnomicsDataSource(service=_mock_calendar())
        assert a.name == "dbnomics"
        assert a.capabilities == ["economic_calendar"]
        assert a.is_available()

    def test_rbi_protocol(self):
        a = RBIDataSource(service=_mock_calendar())
        assert a.name == "rbi"
        assert a.capabilities == ["economic_calendar"]
        assert a.is_available()

    def test_dbnomics_fetch_success(self):
        a = DbnomicsDataSource(service=_mock_calendar())
        res = asyncio.run(a.fetch("economic_calendar", {"days_ahead": 7}))
        assert res.is_success
        assert res.data == [{"event": "X"}]

    def test_rbi_fetch_success(self):
        a = RBIDataSource(service=_mock_calendar())
        res = asyncio.run(a.fetch("economic_calendar", {"days_ahead": 7}))
        assert res.is_success

    def test_health_no_key_required(self):
        info = asyncio.run(DbnomicsDataSource(service=_mock_calendar()).health())
        assert info.connected and info.healthy


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
    def test_macro_sources_in_connected_with_labels(self):
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
