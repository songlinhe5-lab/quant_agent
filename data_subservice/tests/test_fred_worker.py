"""FRED worker 单元测试 (handle_fred 各 action dispatch 分支)。

fred_service 整体替换为 MagicMock, 不触真实 FRED REST。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import fred_worker


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    fake.get_series_observations = AsyncMock(return_value={"ok": True})
    fake.get_releases_dates = AsyncMock(return_value={"ok": True})
    fake.get_economic_calendar = AsyncMock(return_value={"ok": True})
    fake.credit_snapshot = MagicMock(return_value={"daily_limit": 10})
    monkeypatch.setattr(fred_worker, "fred_service", fake)
    return fake


class TestHandleFred:
    @pytest.mark.asyncio
    async def test_macro_series(self, mock_svc):
        assert await fred_worker.handle_fred("MACRO_SERIES", {"symbol": "DGS10"}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_releases(self, mock_svc):
        assert await fred_worker.handle_fred("RELEASES_DATES", {}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_calendar(self, mock_svc):
        assert await fred_worker.handle_fred("ECONOMIC_CALENDAR", {}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown(self, mock_svc):
        out = await fred_worker.handle_fred("BOGUS", {})
        assert "unknown fred action" in out["error"]
