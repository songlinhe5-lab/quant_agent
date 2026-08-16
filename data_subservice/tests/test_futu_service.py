"""FutuService 单元测试 (路由转发 / 订阅前置校验 / status 代理)。

source_router.route 经 mock 替换, 不触真实 OpenD / 远程节点。
"""

from unittest.mock import AsyncMock

import pytest

from data_subservice.futu_src.service import futu_service


class TestStatusProxy:
    def test_property(self):
        # 默认 conn_mgr.status 为 DISCONNECTED
        assert futu_service.status == futu_service.conn_mgr.status

    def test_setter(self):
        old = futu_service.conn_mgr.status
        futu_service.status = "CONNECTED"
        assert futu_service.conn_mgr.status == "CONNECTED"
        futu_service.status = old  # 还原


class TestSubscribePrecheck:
    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self):
        futu_service.conn_mgr.status = "DISCONNECTED"
        res = await futu_service.subscribe_quote("HK.00700")
        assert res["status"] == "error"
        assert "未连接" in res["message"]

    @pytest.mark.asyncio
    async def test_unsubscribe_not_connected(self):
        futu_service.conn_mgr.status = "DISCONNECTED"
        res = await futu_service.unsubscribe_quote("HK.00700")
        assert res["status"] == "error"


class TestHelpers:
    def test_is_futu_unsupported(self):
        assert futu_service.is_futu_unsupported("EURUSD=X") is True
        assert futu_service.is_futu_unsupported("BTCUSDT.CCX") is False

    def test_format_ticker(self):
        assert isinstance(futu_service.format_ticker("hk.00700"), str)

    def test_unavailable(self):
        assert futu_service._unavailable()["status"] == "error"


class TestRouteForwarding:
    @pytest.fixture
    def mock_route(self, monkeypatch):
        fake = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(futu_service.source_router, "route", fake)
        return fake

    @pytest.mark.asyncio
    async def test_get_quote(self, mock_route):
        assert await futu_service.get_quote("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_history(self, mock_route):
        assert await futu_service.get_history("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_order_book(self, mock_route):
        assert await futu_service.get_order_book("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_option_chain(self, mock_route):
        assert await futu_service.get_option_chain("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_fund_flow(self, mock_route):
        assert await futu_service.get_fund_flow("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_fundamental(self, mock_route):
        assert await futu_service.get_fundamental("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_financials(self, mock_route):
        assert await futu_service.get_financials("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_valuation(self, mock_route):
        assert await futu_service.get_valuation("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_short_selling_rank(self, mock_route):
        assert await futu_service.get_short_selling_rank("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_daily_short_volume(self, mock_route):
        assert await futu_service.get_daily_short_volume("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_option_strategy(self, mock_route):
        assert await futu_service.get_option_strategy("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_option_volatility(self, mock_route):
        assert await futu_service.get_option_volatility("US.AAPL260918C150") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_capital_distribution(self, mock_route):
        assert await futu_service.get_capital_distribution("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_research_analyst_consensus(self, mock_route):
        assert await futu_service.get_research_analyst_consensus("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_fed_watch(self, mock_route):
        assert await futu_service.get_fed_watch() == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_heat_map(self, mock_route):
        assert await futu_service.get_heat_map("HK") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_warrant_chain(self, mock_route):
        assert await futu_service.get_warrant_chain("HK.00700") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_market_snapshots(self, mock_route):
        assert await futu_service.get_market_snapshots(["HK.00700"]) == {"ok": True}

    @pytest.mark.asyncio
    async def test_screen_stocks(self, mock_route):
        assert await futu_service.screen_stocks("HK", []) == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_stock_basicinfo(self, mock_route):
        assert await futu_service.get_stock_basicinfo("HK", "STOCK") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_account_info(self, mock_route):
        assert await futu_service.get_account_info("HK") == {"ok": True}

    @pytest.mark.asyncio
    async def test_emergency_liquidation(self, mock_route):
        assert await futu_service.emergency_liquidation("HK") == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_search_news(self, mock_route):
        assert await futu_service.get_search_news("HK.00700") == {"ok": True}


class TestConnectClose:
    def test_connect(self, monkeypatch):
        fake = lambda self: None
        monkeypatch.setattr(futu_service.conn_mgr, "connect", lambda: None)
        monkeypatch.setattr(futu_service.conn_mgr, "close", lambda: None)
        monkeypatch.setattr(futu_service.cache_mgr, "clear_all_subscriptions", lambda: None)
        futu_service.connect()
        futu_service.close()
        assert futu_service.quote_ctx is None
