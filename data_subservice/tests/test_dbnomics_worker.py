"""DBnomics worker 单元测试 (handle_dbnomics 各 action dispatch 分支)。

dbnomics_service 经 mock 替换, 不触真实 DBnomics API。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import dbnomics_worker


@pytest.fixture
def mock_svc(monkeypatch):
    fake = MagicMock()
    fake.get_economic_calendar = AsyncMock(return_value={"ok": True})
    fake.get_em_cpi_series = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(dbnomics_worker, "dbnomics_service", fake)
    return fake


class TestHandleDbnomics:
    @pytest.mark.asyncio
    async def test_economic_calendar(self, mock_svc):
        assert await dbnomics_worker.handle_dbnomics("ECONOMIC_CALENDAR", {"days_ahead": 7}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_em_cpi_series(self, mock_svc):
        assert await dbnomics_worker.handle_dbnomics("EM_CPI_SERIES", {}) == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown(self, mock_svc):
        out = await dbnomics_worker.handle_dbnomics("BOGUS", {})
        assert "unknown dbnomics action" in out["error"]
