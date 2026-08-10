"""
BE-ARCH-05: Finnhub DataSource 接入 DataSourceInterface + DataSourceRegistry。

- FinnhubDataSource 满足 DataSourceInterface Protocol
- ensure_finnhub_registered 幂等注册
- fetch 经 data_source_router.fetch_finnhub() 远程调用 data_subservice（仅远程，无本地 SDK）
- 不支持 action 返回不可重试错误
- health 返回 HealthInfo（基于 router 节点健康）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.datasource import (
    DataSourceInterface,
    ResultStatus,
    datasource_registry,
    rate_limit_registry,
)
from backend.services.datasource.adapters.finnhub import (
    FinnhubDataSource,
    ensure_finnhub_registered,
)


@pytest.fixture(autouse=True)
def _clean():
    datasource_registry.clear()
    rate_limit_registry.clear()
    yield
    datasource_registry.clear()
    rate_limit_registry.clear()


def _patch_finnhub_node(monkeypatch, status: str = "healthy"):
    """注入一个可控的 finnhub_master 节点到 router。"""
    from backend.services.datasource.router import data_source_router

    node = MagicMock()
    node.status = status
    node.url = "http://localhost:8001"
    node.error_count = 0
    monkeypatch.setitem(data_source_router._nodes, "finnhub_master", node)
    return node


class TestFinnhubDataSourceProtocol:
    def test_satisfies_interface(self):
        assert isinstance(FinnhubDataSource(), DataSourceInterface)

    def test_name_and_capabilities(self):
        src = FinnhubDataSource()
        assert src.name == "finnhub"
        assert set(src.capabilities) == {
            "quote",
            "earnings",
            "company_news",
            "market_news",
            "economic_calendar",
            "insider_trading",
            "stock_history",
        }
        assert src.version == "2.0.0"

    def test_mode_is_remote(self):
        assert FinnhubDataSource().mode == "remote"


class TestFinnhubRegistration:
    def test_idempotent_register(self):
        iid1 = ensure_finnhub_registered()
        iid2 = ensure_finnhub_registered()
        assert iid1 == iid2 == "finnhub-default"
        assert datasource_registry.has("finnhub")
        # 仅一个实例
        assert len(datasource_registry.list_names()) == 1


class TestFinnhubFetchRouting:
    @pytest.mark.asyncio
    async def test_fetch_routes_to_router(self, monkeypatch):
        _patch_finnhub_node(monkeypatch)
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "success", "data": [{"symbol": "AAPL"}]})
        monkeypatch.setattr(data_source_router, "fetch_finnhub", fetch)
        src = FinnhubDataSource()
        result = await src.fetch("earnings", {"days_ahead": 14})
        assert result.is_success
        assert result.data == [{"symbol": "AAPL"}]
        fetch.assert_awaited_once()
        # action 归一化为大写 EARNINGS
        assert fetch.call_args.args[0] == "earnings"

    @pytest.mark.asyncio
    async def test_fetch_remote_error_is_error(self, monkeypatch):
        _patch_finnhub_node(monkeypatch)
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "error", "message": "boom"})
        monkeypatch.setattr(data_source_router, "fetch_finnhub", fetch)
        src = FinnhubDataSource()
        result = await src.fetch("company_news", {"ticker": "TSLA"})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "FINNHUB_FETCH_FAILED"

    @pytest.mark.asyncio
    async def test_fetch_unsupported_action(self):
        src = FinnhubDataSource()
        result = await src.fetch("foo", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "UNSUPPORTED_ACTION"
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_fetch_node_unavailable_is_error(self, monkeypatch):
        # finnhub_master 节点不存在
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        src = FinnhubDataSource()
        result = await src.fetch("earnings", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "FINNHUB_FETCH_FAILED"


class TestFinnhubHealth:
    @pytest.mark.asyncio
    async def test_health_healthy_node(self, monkeypatch):
        _patch_finnhub_node(monkeypatch, status="healthy")
        src = FinnhubDataSource()
        info = await src.health()
        assert info.healthy is True
        assert info.connected is True
        assert info.mode == "remote"

    @pytest.mark.asyncio
    async def test_health_node_missing(self, monkeypatch):
        from backend.services.datasource.router import data_source_router

        monkeypatch.setattr(data_source_router, "_nodes", {})
        src = FinnhubDataSource()
        info = await src.health()
        assert info.healthy is False
        assert info.connected is False
        assert info.last_error == "finnhub_master 节点未配置"


class TestFinnhubViaRegistry:
    @pytest.mark.asyncio
    async def test_registry_fetch_routes_to_finnhub(self, monkeypatch):
        _patch_finnhub_node(monkeypatch)
        from backend.services.datasource.router import data_source_router

        fetch = AsyncMock(return_value={"status": "success", "data": [{"h": "x"}]})
        monkeypatch.setattr(data_source_router, "fetch_finnhub", fetch)
        ensure_finnhub_registered()
        result = await datasource_registry.fetch("finnhub", "company_news", {"ticker": "AAPL"})
        assert result.is_success
        assert result.data == [{"h": "x"}]

    @pytest.mark.asyncio
    async def test_registry_unknown_source(self):
        result = await datasource_registry.fetch("finnhub", "company_news", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "SOURCE_NOT_FOUND"
