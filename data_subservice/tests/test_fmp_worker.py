"""FMP worker 单元测试 (_to_fmp_symbol 格式适配 + 全 action 路由)。

fmp_service 整体替换为 MagicMock, 不触真实 FMP REST。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import fmp_worker


class TestToFmpSymbol:
    @pytest.mark.parametrize(
        "inp,expected",
        [
            ("", ""),
            ("  ", "  "),
            ("HK.00772", "772.HK"),
            ("HK.00001", "1.HK"),
            ("SH.600000", "600000.sh"),
            ("SZ.000001", "000001.sz"),
            ("BJ.830799", "830799.bj"),
            ("AAPL", "AAPL"),
            ("US.AAPL", "US.AAPL"),
        ],
    )
    def test_cases(self, inp, expected):
        assert fmp_worker._to_fmp_symbol(inp) == expected


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    fake.get_quote = AsyncMock(return_value={"ok": True})
    fake.get_profile = AsyncMock(return_value={"data": {"name": "X"}})
    fake.get_income_statement = AsyncMock(return_value={"data": {"rev": 1}})
    monkeypatch.setattr(fmp_worker, "fmp_service", fake)
    return fake


class TestHandleFmp:
    @pytest.mark.asyncio
    async def test_quote(self, mock_svc):
        assert await fmp_worker.handle_fmp("QUOTE", {"symbol": "HK.00772"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_profile(self, mock_svc):
        assert await fmp_worker.handle_fmp("PROFILE", {"symbol": "HK.00772"}) == {"data": {"name": "X"}}

    @pytest.mark.asyncio
    async def test_income(self, mock_svc):
        assert await fmp_worker.handle_fmp("INCOME_STATEMENT", {"symbol": "HK.00772"}) == {"data": {"rev": 1}}

    @pytest.mark.asyncio
    async def test_info(self, mock_svc):
        assert await fmp_worker.handle_fmp("INFO", {"symbol": "HK.00772"}) == {"data": {"name": "X"}}

    @pytest.mark.asyncio
    async def test_fundamental_combo(self, mock_svc):
        out = await fmp_worker.handle_fmp("FUNDAMENTAL", {"symbol": "HK.00772"})
        assert out["status"] == "success"
        assert out["data"]["symbol"] == "772.HK"

    @pytest.mark.asyncio
    async def test_credit(self, mock_svc, monkeypatch):
        from data_subservice._internal import fmp as fmp_mod

        monkeypatch.setattr(fmp_mod, "credit_snapshot", MagicMock(return_value={"daily_limit": 10}))
        out = await fmp_worker.handle_fmp("CREDIT", {})
        assert out["status"] == "success"
        assert "data" in out

    @pytest.mark.asyncio
    async def test_unknown(self, mock_svc):
        out = await fmp_worker.handle_fmp("BOGUS", {})
        assert "未知 fmp action" in out["error"]
