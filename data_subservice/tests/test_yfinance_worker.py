"""YFinance worker 单元测试 (_annotate_error_category 限流标注 + 全 action 路由)。

yfinance_service 整体替换为 MagicMock, 不触真实 Yahoo 网络。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import yfinance_worker


class TestAnnotateErrorCategory:
    def test_non_dict_passthrough(self):
        assert yfinance_worker._annotate_error_category("x") == "x"

    def test_already_has_category(self):
        res = {"error": "boom", "error_category": "ip_blocked"}
        assert yfinance_worker._annotate_error_category(res)["error_category"] == "ip_blocked"

    def test_no_error_passthrough(self):
        assert yfinance_worker._annotate_error_category({"data": 1}) == {"data": 1}

    def test_rate_limit_detected(self):
        res = yfinance_worker._annotate_error_category({"error": "Too Many Requests from Yahoo"})
        assert res["error_category"] == "rate_limit"

    def test_throttle_detected(self):
        res = yfinance_worker._annotate_error_category({"error": "throttled by server"})
        assert res["error_category"] == "rate_limit"

    def test_normal_error_untouched(self):
        res = yfinance_worker._annotate_error_category({"error": "some other failure"})
        assert "error_category" not in res


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    for name in [
        "get_quote",
        "get_history",
        "get_fund_flow",
        "get_option_chain",
        "get_financials",
        "search",
        "get_tech_indicators",
        "get_batched_quote",
        "get_news",
    ]:
        setattr(fake, name, AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(yfinance_worker, "yfinance_service", fake)
    return fake


class TestHandleYfinance:
    @pytest.mark.asyncio
    async def test_quote(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("QUOTE", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_history(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("HISTORY", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_fund_flow(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("FUND_FLOW", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_option_chain(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("OPTION_CHAIN", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_financials(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("FINANCIALS", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_search(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("SEARCH", {"query": "apple"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_tech(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("TECH", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_batch_quote(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("BATCH_QUOTE", {"symbols": ["AAPL"]}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_news(self, mock_svc):
        assert await yfinance_worker.handle_yfinance("NEWS", {"symbol": "AAPL"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_svc):
        out = await yfinance_worker.handle_yfinance("BOGUS", {})
        assert "未知 yfinance action" in out["error"]

    @pytest.mark.asyncio
    async def test_rate_limit_annotation(self, mock_svc):
        mock_svc.get_quote = AsyncMock(return_value={"error": "Too Many Requests"})
        out = await yfinance_worker.handle_yfinance("QUOTE", {"symbol": "AAPL"})
        assert out["error_category"] == "rate_limit"
