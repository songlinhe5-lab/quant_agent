"""
BE-ARCH-05: Finnhub DataSource 接入 DataSourceInterface + DataSourceRegistry。

- FinnhubDataSource 满足 DataSourceInterface Protocol
- ensure_finnhub_registered 幂等注册
- fetch 按 action 路由到 FinnhubService 对应方法并返回标准 Result
- 不支持 action / 缺 API Key 返回不可重试错误
- health 返回 HealthInfo（含 rate_limit_status）
- DATASOURCE_FINNHUB_MODE 环境变量控制 mode
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


class TestFinnhubDataSourceProtocol:
    def test_satisfies_interface(self):
        assert isinstance(FinnhubDataSource(service=MagicMock()), DataSourceInterface)

    def test_name_and_capabilities(self):
        src = FinnhubDataSource(service=MagicMock())
        assert src.name == "finnhub"
        assert set(src.capabilities) == {
            "earnings",
            "company_news",
            "market_news",
            "economic_calendar",
            "insider_trading",
            "stock_history",
        }
        assert src.version == "1.0.0"

    def test_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("DATASOURCE_FINNHUB_MODE", "external")
        assert FinnhubDataSource(service=MagicMock()).mode == "external"
        monkeypatch.delenv("DATASOURCE_FINNHUB_MODE", raising=False)
        assert FinnhubDataSource(service=MagicMock()).mode == "internal"


class TestFinnhubRegistration:
    def test_idempotent_register(self):
        iid1 = ensure_finnhub_registered(MagicMock())
        iid2 = ensure_finnhub_registered(MagicMock())
        assert iid1 == iid2 == "finnhub-default"
        assert datasource_registry.has("finnhub")
        # 仅一个实例
        assert len(datasource_registry.list_names()) == 1


class TestFinnhubFetchRouting:
    @pytest.mark.asyncio
    async def test_fetch_earnings(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_earnings_calendar = AsyncMock(return_value={"status": "success", "data": [{"symbol": "AAPL"}]})
        src = FinnhubDataSource(service=svc)
        result = await src.fetch("earnings", {"days_ahead": 14})
        assert result.is_success
        assert result.data == [{"symbol": "AAPL"}]
        svc.get_earnings_calendar.assert_awaited_once_with(days_ahead=14, days_back=0, skip_cache=False)

    @pytest.mark.asyncio
    async def test_fetch_company_news(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_company_news = AsyncMock(return_value={"status": "success", "data": [{"headline": "x"}]})
        src = FinnhubDataSource(service=svc)
        result = await src.fetch("company_news", {"ticker": "TSLA", "days_back": 5})
        assert result.is_success
        svc.get_company_news.assert_awaited_once_with(ticker="TSLA", days_back=5, skip_cache=False)

    @pytest.mark.asyncio
    async def test_fetch_market_news(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_market_news = AsyncMock(return_value={"status": "success", "data": []})
        src = FinnhubDataSource(service=svc)
        await src.fetch("market_news", {"category": "forex"})
        svc.get_market_news.assert_awaited_once_with(category="forex")

    @pytest.mark.asyncio
    async def test_fetch_economic_calendar(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": []})
        src = FinnhubDataSource(service=svc)
        await src.fetch("economic_calendar", {"days_ahead": 30})
        svc.get_economic_calendar.assert_awaited_once_with(days_ahead=30, days_back=0, skip_cache=False)

    @pytest.mark.asyncio
    async def test_fetch_insider_trading(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_insider_transactions = AsyncMock(return_value={"status": "success", "data": []})
        src = FinnhubDataSource(service=svc)
        await src.fetch("insider_trading", {"ticker": "AAPL", "limit": 10})
        svc.get_insider_transactions.assert_awaited_once_with(ticker="AAPL", limit=10)

    @pytest.mark.asyncio
    async def test_fetch_stock_history(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_stock_history = AsyncMock(return_value={"status": "success", "data": {}})
        src = FinnhubDataSource(service=svc)
        await src.fetch("stock_history", {"ticker": "MSFT", "days_back": 100})
        svc.get_stock_history.assert_awaited_once_with(ticker="MSFT", days_back=100)

    @pytest.mark.asyncio
    async def test_fetch_unsupported_action(self):
        src = FinnhubDataSource(service=MagicMock())
        result = await src.fetch("quote", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "UNSUPPORTED_ACTION"
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_fetch_no_api_key(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="")
        src = FinnhubDataSource(service=svc)
        result = await src.fetch("earnings", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "FINNHUB_NO_KEY"
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_fetch_rate_limited_semantics(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_earnings_calendar = AsyncMock(
            return_value={"status": "error", "message": "Finnhub 免费版 API 触发 429 Too Many Requests"}
        )
        src = FinnhubDataSource(service=svc)
        result = await src.fetch("earnings", {})
        assert result.status == ResultStatus.RATE_LIMITED
        assert result.error.category.value == "rate_limit"

    @pytest.mark.asyncio
    async def test_fetch_skipped_is_error(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="")
        svc.get_economic_calendar = AsyncMock(
            return_value={"status": "skipped", "message": "系统未配置 FINNHUB_API_KEY", "data": []}
        )
        src = FinnhubDataSource(service=svc)
        # 该 action 内部会先查 key；这里直接绕过 key 校验测 skipped 分支
        svc._get_api_key.return_value = "k"
        result = await src.fetch("economic_calendar", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "FINNHUB_UNAVAILABLE"


class TestFinnhubHealth:
    @pytest.mark.asyncio
    async def test_health_with_key(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        src = FinnhubDataSource(service=svc)
        info = await src.health()
        assert info.healthy is True
        assert info.connected is True
        assert info.mode == "internal"
        assert info.rate_limit_status is not None

    @pytest.mark.asyncio
    async def test_health_without_key(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="")
        src = FinnhubDataSource(service=svc)
        info = await src.health()
        assert info.healthy is False
        assert info.connected is False
        assert info.last_error == "FINNHUB_API_KEY 未配置"


class TestFinnhubViaRegistry:
    @pytest.mark.asyncio
    async def test_registry_fetch_routes_to_finnhub(self):
        svc = MagicMock()
        svc._get_api_key = MagicMock(return_value="k")
        svc.get_company_news = AsyncMock(return_value={"status": "success", "data": [{"h": "x"}]})
        ensure_finnhub_registered(svc)
        result = await datasource_registry.fetch("finnhub", "company_news", {"ticker": "AAPL"})
        assert result.is_success
        assert result.data == [{"h": "x"}]

    @pytest.mark.asyncio
    async def test_registry_unknown_source(self):
        result = await datasource_registry.fetch("finnhub", "company_news", {})
        assert result.status == ResultStatus.ERROR
        assert result.error.code == "SOURCE_NOT_FOUND"
