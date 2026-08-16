"""Futu worker handle_futu 路由测试 (全 action 分支 + _as_enum 还原逻辑)。

futu_service 整体替换为 MagicMock, 不触真实 OpenD / 远程。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from futu import TrdMarket, TrdSide

from data_subservice import futu_worker


class TestAsEnum:
    def test_none(self):
        assert futu_worker._as_enum(TrdSide, None) is None

    def test_already_enum(self):
        v = TrdSide.BUY
        assert futu_worker._as_enum(TrdSide, v) is v

    def test_by_value(self):
        # TrdSide 没有明确字符串 value 时, 走成员名构造
        assert futu_worker._as_enum(TrdSide, "BUY") == TrdSide.BUY

    def test_by_member_name(self):
        assert futu_worker._as_enum(TrdMarket, "HK") == TrdMarket.HK

    def test_fallback_on_bad(self):
        assert futu_worker._as_enum(TrdSide, "NOPE") == "NOPE"


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    for name in [
        "get_quote",
        "get_history",
        "get_order_book",
        "get_option_chain",
        "get_fund_flow",
        "get_fundamental",
        "get_financials",
        "get_valuation",
        "get_short_selling_rank",
        "get_daily_short_volume",
        "get_option_strategy",
        "get_option_volatility",
        "get_capital_distribution",
        "get_research_analyst_consensus",
        "get_fed_watch",
        "get_heat_map",
        "get_warrant_chain",
        "get_market_snapshots",
        "get_stock_basicinfo",
        "get_account_info",
        "place_order",
        "screen_stocks",
        "modify_order",
        "query_order",
        "emergency_liquidation",
        "subscribe_quote",
        "unsubscribe_quote",
        "get_search_news",
    ]:
        setattr(fake, name, AsyncMock(return_value={"ok": True}))
    fake.status = "CONNECTED"
    monkeypatch.setattr(futu_worker, "futu_service", fake)
    return fake


class TestHandleFutu:
    @pytest.mark.asyncio
    async def test_quote(self, mock_svc):
        assert await futu_worker.handle_futu("QUOTE", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_history(self, mock_svc):
        assert await futu_worker.handle_futu("HISTORY", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_order_book(self, mock_svc):
        assert await futu_worker.handle_futu("ORDER_BOOK", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_option_chain(self, mock_svc):
        assert await futu_worker.handle_futu("OPTION_CHAIN", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_fund_flow(self, mock_svc):
        assert await futu_worker.handle_futu("FUND_FLOW", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_fundamental(self, mock_svc):
        assert await futu_worker.handle_futu("FUNDAMENTAL", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_financials(self, mock_svc):
        assert await futu_worker.handle_futu("FINANCIALS", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_valuation(self, mock_svc):
        assert await futu_worker.handle_futu("VALUATION", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_short_selling_rank(self, mock_svc):
        assert await futu_worker.handle_futu("SHORT_SELLING", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_short_selling_daily(self, mock_svc):
        assert await futu_worker.handle_futu("SHORT_SELLING", {"sub_action": "daily", "symbol": "HK.00700"}) == {
            "ok": True
        }

    @pytest.mark.asyncio
    async def test_option_strategy(self, mock_svc):
        assert await futu_worker.handle_futu("OPTION_STRATEGY", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_option_volatility(self, mock_svc):
        assert await futu_worker.handle_futu("OPTION_VOLATILITY", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_capital_distribution(self, mock_svc):
        assert await futu_worker.handle_futu("CAPITAL_DISTRIBUTION", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_analyst_consensus(self, mock_svc):
        assert await futu_worker.handle_futu("ANALYST_CONSENSUS", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_fed_watch(self, mock_svc):
        assert await futu_worker.handle_futu("FED_WATCH", {}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_heat_map(self, mock_svc):
        assert await futu_worker.handle_futu("HEAT_MAP", {"market": "HK"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_warrant_chain(self, mock_svc):
        assert await futu_worker.handle_futu("WARRANT_CHAIN", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_snapshot(self, mock_svc):
        assert await futu_worker.handle_futu("SNAPSHOT", {"symbols": ["HK.00700"]}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_stock_basicinfo(self, mock_svc):
        assert await futu_worker.handle_futu("STOCK_BASICINFO", {"market": "HK"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_subscribe(self, mock_svc):
        assert await futu_worker.handle_futu("SUBSCRIBE", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_unsubscribe(self, mock_svc):
        assert await futu_worker.handle_futu("UNSUBSCRIBE", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_company_news(self, mock_svc):
        assert await futu_worker.handle_futu("COMPANY_NEWS", {"symbol": "HK.00700"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_health(self, mock_svc):
        out = await futu_worker.handle_futu("HEALTH", {})
        assert out["available"] is True

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_svc):
        out = await futu_worker.handle_futu("BOGUS", {})
        assert "未知 futu action" in out["error"]


class TestAccountInfoLocked:
    @pytest.mark.asyncio
    async def test_locked_returns_empty_success(self, monkeypatch):
        fake = MagicMock()
        fake.get_account_info = AsyncMock(return_value={"locked": True})
        fake.status = "CONNECTED"
        monkeypatch.setattr(futu_worker, "futu_service", fake)
        out = await futu_worker.handle_futu("ACCOUNT_INFO", {"market": "HK"})
        assert out["status"] == "success"
        assert out["trade_unlocked"] is False
        assert out["data"]["accounts"] == []
