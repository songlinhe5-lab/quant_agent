"""
BE-ARCH-04: DataSource 双 Registry 澄清守门。

- RateLimitRegistry：只管理 Throttler/Analyzer
- DataSourceRegistry：只管理 DataSourceInterface 实例 + fetch 主路径
- 命名不得再混淆
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.datasource import (
    DataSourceInterface,
    DataSourceRegistry,
    ErrorInfo,
    RateLimitRegistry,
    ResultStatus,
    datasource_registry,
    rate_limit_registry,
)
from backend.services.datasource.adapters.legacy_yfinance import (
    LegacyYFinanceDataSource,
    ensure_yfinance_registered,
)
from backend.services.datasource.protocol import DataSourceInterface as Proto
from backend.services.datasource.source_registry import DataSourceRegistry as SrcReg

ROOT = Path(__file__).resolve().parents[1]
DS_PKG = ROOT / "services" / "datasource"


class TestDualRegistryNaming:
    def test_rate_limit_and_source_are_distinct_singletons(self):
        assert rate_limit_registry is not datasource_registry
        assert isinstance(rate_limit_registry, RateLimitRegistry)
        assert isinstance(datasource_registry, DataSourceRegistry)
        assert not isinstance(rate_limit_registry, DataSourceRegistry)
        assert not isinstance(datasource_registry, RateLimitRegistry)

    def test_exports_match_docs14_roles(self):
        assert SrcReg is DataSourceRegistry
        assert Proto is DataSourceInterface

    def test_rate_limit_registry_module_doc_mentions_split(self):
        text = (DS_PKG / "registry.py").read_text(encoding="utf-8")
        assert "RateLimitRegistry" in text
        assert "限流" in text
        assert "DataSourceInterface" in text or "源实例" in text


class TestSourceRegistryFetchPath:
    @pytest.fixture(autouse=True)
    def _clean(self):
        datasource_registry.clear()
        rate_limit_registry.clear()
        yield
        datasource_registry.clear()
        rate_limit_registry.clear()

    def test_legacy_yfinance_satisfies_protocol(self):
        src = LegacyYFinanceDataSource(service=MagicMock())
        assert isinstance(src, DataSourceInterface)

    @pytest.mark.asyncio
    async def test_fetch_requires_registration(self):
        result = await datasource_registry.fetch("yfinance", "history", {"ticker": "AAPL"})
        assert result.status == ResultStatus.ERROR
        assert result.error and result.error.code == "SOURCE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_fetch_goes_through_interface(self):
        mock_svc = MagicMock()
        mock_svc.fetch_yf_data = AsyncMock(return_value=(True, {"Close": [1]}, ""))
        ensure_yfinance_registered(mock_svc)

        result = await datasource_registry.fetch(
            "yfinance", "history", {"ticker": "AAPL", "period": "5d"}
        )
        assert result.is_success
        assert result.data == {"Close": [1]}
        mock_svc.fetch_yf_data.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_respects_rate_limit_throttle(self):
        mock_svc = MagicMock()
        mock_svc.fetch_yf_data = AsyncMock(return_value=(True, {"ok": 1}, ""))
        ensure_yfinance_registered(mock_svc)

        throttler = rate_limit_registry.get_throttler("yfinance")
        # force throttle window
        throttler.on_rate_limit(ErrorInfo.rate_limited(retry_after=60))
        # adaptive/linear may need strategy not NONE — default may be adaptive
        if not throttler.should_throttle():
            # force via internal if strategy is NONE
            from backend.services.datasource.throttler import BackoffStrategy

            throttler._strategy = BackoffStrategy.EXPONENTIAL  # noqa: SLF001
            throttler.on_rate_limit(ErrorInfo.rate_limited(retry_after=60))

        result = await datasource_registry.fetch("yfinance", "history", {"ticker": "AAPL"})
        assert result.status == ResultStatus.RATE_LIMITED
        mock_svc.fetch_yf_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unregister(self):
        ensure_yfinance_registered(MagicMock())
        assert datasource_registry.has("yfinance")
        assert datasource_registry.unregister("yfinance")
        assert not datasource_registry.has("yfinance")


class TestMarketDataUsesSourceRegistry:
    @pytest.mark.asyncio
    async def test_fetch_yf_data_via_registry(self):
        from backend.services.adapters.legacy_market_data import MarketDataGateway

        datasource_registry.clear()
        mock_svc = MagicMock()
        mock_svc.fetch_yf_data = AsyncMock(return_value=(True, "FRAME", ""))

        # Build gateway but swap yf after init registration
        with pytest.MonkeyPatch.context() as mp:
            # Avoid real service imports where possible by patching modules used in __init__
            MagicMock()
            mp.setattr(
                "backend.services.adapters.legacy_market_data.MarketDataGateway.__init__",
                lambda self: None,
            )
            gw = MarketDataGateway()
            gw._yf = mock_svc
            ensure_yfinance_registered(mock_svc)
            ok, data, msg = await gw.fetch_yf_data("AAPL", "history", period="5d")
            assert ok is True
            assert data == "FRAME"
            assert msg == ""
            mock_svc.fetch_yf_data.assert_awaited()
        datasource_registry.clear()
