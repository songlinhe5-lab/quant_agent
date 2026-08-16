"""FinnhubService 单元测试 (_to_finnhub_symbol 纯函数 + 各 get_* 网络分支)。

httpx.AsyncClient 经 mock 替换, 不触真实 finnhub.io。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice._internal import finnhub as finnhub_mod
from data_subservice._internal.finnhub import FinnhubService, _to_finnhub_symbol


def _mock_client(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    client = AsyncMock()
    client.__aenter__.return_value.get = AsyncMock(return_value=resp)
    return client


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)


class TestToFinnhubSymbol:
    @pytest.mark.parametrize(
        "inp,expected",
        [
            ("", ""),
            ("  ", ""),
            ("HK:00700", "HK:00700"),  # 已是前缀格式, 透传
            ("HK.00700", "HK:00700"),
            ("00700.HK", "HK:00700"),
            ("0700.HK", "HK:0700"),
            ("US.AAPL", "AAPL"),
            ("AAPL", "AAPL"),
            ("600519", "600519"),
        ],
    )
    def test_cases(self, inp, expected):
        assert _to_finnhub_symbol(inp) == expected


class TestUnconfigured:
    @pytest.mark.asyncio
    async def test_get_quote(self):
        assert "未配置" in (await FinnhubService().get_quote("AAPL"))["message"]

    @pytest.mark.asyncio
    async def test_get_company_news(self):
        assert "未配置" in (await FinnhubService().get_company_news("AAPL"))["message"]

    @pytest.mark.asyncio
    async def test_get_market_news(self):
        assert "未配置" in (await FinnhubService().get_market_news())["message"]

    @pytest.mark.asyncio
    async def test_get_earnings_calendar(self):
        assert "未配置" in (await FinnhubService().get_earnings_calendar())["message"]

    @pytest.mark.asyncio
    async def test_get_economic_calendar(self):
        assert "未配置" in (await FinnhubService().get_economic_calendar())["message"]

    @pytest.mark.asyncio
    async def test_get_insider_transactions(self):
        assert "未配置" in (await FinnhubService().get_insider_transactions("AAPL"))["message"]

    @pytest.mark.asyncio
    async def test_get_dividend_calendar(self):
        assert "未配置" in (await FinnhubService().get_dividend_calendar())["message"]

    @pytest.mark.asyncio
    async def test_get_ipo_calendar(self):
        assert "未配置" in (await FinnhubService().get_ipo_calendar())["message"]

    @pytest.mark.asyncio
    async def test_get_stock_history(self):
        assert "未配置" in (await FinnhubService().get_stock_history("AAPL"))["message"]


class TestSuccess:
    @pytest.mark.asyncio
    async def test_get_quote(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(
            finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"c": 1.0, "pc": 2.0, "t": 99})
        ):
            out = await FinnhubService().get_quote("AAPL")
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_quote_all_zero_blocked(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"c": 0, "pc": 0, "t": 0})):
            out = await FinnhubService().get_quote("HK.00700")
        assert out["error_category"] == "unsupported_market"

    @pytest.mark.asyncio
    async def test_get_market_news(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(200, [{"x": 1}])):
            out = await FinnhubService().get_market_news()
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_earnings_calendar(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"x": 1})):
            out = await FinnhubService().get_earnings_calendar()
        assert out["status"] == "success"


class TestStatusCodes:
    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await FinnhubService().get_market_news()
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_403_ip_blocked(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(403)):
            out = await FinnhubService().get_market_news()
        assert out["error_category"] == "ip_blocked"

    @pytest.mark.asyncio
    async def test_other(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=_mock_client(500)):
            out = await FinnhubService().get_market_news()
        assert "500" in out["message"]

    @pytest.mark.asyncio
    async def test_exception(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "k")
        client = AsyncMock()
        client.__aenter__.return_value.get = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(finnhub_mod.httpx, "AsyncClient", return_value=client):
            out = await FinnhubService().get_market_news()
        assert "request failed" in out["message"]
