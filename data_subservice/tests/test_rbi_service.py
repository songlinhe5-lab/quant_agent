"""RBIService 单元测试 (RBI 公告快照 + World Bank 印度 CPI 各分支)。

httpx.AsyncClient 经 mock 替换, 不触真实 rbi.org.in / worldbank.org。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice._internal import rbi as rbi_mod
from data_subservice._internal.rbi import RBIService


def _mock_client(status_code=200, json_data=None, text="ok"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    resp.url = "https://www.rbi.org.in/x"
    client = AsyncMock()
    client.__aenter__.return_value.get = AsyncMock(return_value=resp)
    return client


class TestEconomicCalendar:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(200, text="press release")):
            out = await RBIService().get_economic_calendar()
        assert out["status"] == "success"
        assert out["data"]["length"] == len("press release")

    @pytest.mark.asyncio
    async def test_429(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await RBIService().get_economic_calendar()
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(404)):
            out = await RBIService().get_economic_calendar()
        assert "404" in out["message"]

    @pytest.mark.asyncio
    async def test_exception(self):
        client = AsyncMock()
        client.__aenter__.return_value.get = AsyncMock(side_effect=RuntimeError("net"))
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=client):
            out = await RBIService().get_economic_calendar()
        assert "request failed" in out["message"]


class TestIndiaCpiSeries:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(200, [{"cpi": 6.0}])):
            out = await RBIService().get_india_cpi_series()
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_429(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await RBIService().get_india_cpi_series()
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self):
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=_mock_client(500)):
            out = await RBIService().get_india_cpi_series()
        assert "500" in out["message"]

    @pytest.mark.asyncio
    async def test_exception(self):
        client = AsyncMock()
        client.__aenter__.return_value.get = AsyncMock(side_effect=RuntimeError("net"))
        with patch.object(rbi_mod.httpx, "AsyncClient", return_value=client):
            out = await RBIService().get_india_cpi_series()
        assert "request failed" in out["message"]
