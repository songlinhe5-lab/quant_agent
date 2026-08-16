"""RBI worker 单元测试 (handle_rbi 各 action dispatch 分支)。

rbi_service 经 mock 替换, 不触真实 RBI / World Bank API。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import rbi_worker


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    fake.get_economic_calendar = AsyncMock(return_value={"ok": True})
    fake.get_india_cpi_series = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(rbi_worker, "rbi_service", fake)
    return fake


class TestHandleRbi:
    @pytest.mark.asyncio
    async def test_economic_calendar(self, mock_svc):
        assert await rbi_worker.handle_rbi("ECONOMIC_CALENDAR", {"days_ahead": 7}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_india_cpi_series(self, mock_svc):
        assert await rbi_worker.handle_rbi("INDIA_CPI_SERIES", {"date_range": "5y"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown(self, mock_svc):
        out = await rbi_worker.handle_rbi("BOGUS", {})
        assert "unknown rbi action" in out["error"]
