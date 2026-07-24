"""
MarketDataService 单元测试
覆盖: backend/app/market_data_app.py
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.adapters.ports.data_source_port import DataSourceResult
from backend.app.market_data_app import MarketDataService


@pytest.fixture
def service():
    """创建 MarketDataService 并 mock 所有适配器"""
    with (
        patch("backend.app.market_data_app.FutuAdapter") as mock_futu_cls,
        patch("backend.app.market_data_app.YFinanceAdapter") as mock_yf_cls,
        patch("backend.app.market_data_app.AkShareAdapter") as mock_ak_cls,
    ):
        mock_futu = MagicMock()
        mock_yf = MagicMock()
        mock_ak = MagicMock()
        mock_futu_cls.return_value = mock_futu
        mock_yf_cls.return_value = mock_yf
        mock_ak_cls.return_value = mock_ak

        svc = MarketDataService()
        svc._futu = mock_futu
        svc._yfinance = mock_yf
        svc._akshare = mock_ak
        yield svc


class TestGetQuote:
    def test_futu_success(self, service):
        service._futu.is_available = True
        service._futu.fetch.return_value = DataSourceResult.success({"price": 150.0}, source="futu")

        result = service.get_quote("US.AAPL")
        assert result.is_success()
        assert result.data["price"] == 150.0
        service._futu.fetch.assert_called_once_with("quote", {"ticker": "US.AAPL"})

    def test_futu_fail_yf_fallback(self, service):
        service._futu.is_available = True
        service._futu.fetch.return_value = DataSourceResult.error("futu down")
        service._yfinance.fetch.return_value = DataSourceResult.success({"price": 149.0}, source="yfinance")

        result = service.get_quote("US.AAPL")
        assert result.is_success()
        assert result.data["price"] == 149.0

    def test_futu_unavailable_yf_direct(self, service):
        service._futu.is_available = False
        service._yfinance.fetch.return_value = DataSourceResult.success({"price": 148.0}, source="yfinance")

        result = service.get_quote("US.AAPL")
        assert result.is_success()
        service._futu.fetch.assert_not_called()

    def test_a_share_akshare_fallback(self, service):
        service._futu.is_available = True
        service._futu.fetch.return_value = DataSourceResult.error("不支持A股")
        service._akshare.fetch.return_value = DataSourceResult.success({"price": 1800.0}, source="akshare")

        result = service.get_quote("SH.600519")
        assert result.is_success()
        assert result.data["price"] == 1800.0

    def test_all_sources_fail(self, service):
        service._futu.is_available = True
        service._futu.fetch.return_value = DataSourceResult.error("fail")
        service._yfinance.fetch.return_value = DataSourceResult.error("yf fail")

        result = service.get_quote("US.AAPL")
        assert result.is_error()


class TestGetKline:
    def test_futu_success(self, service):
        service._futu.is_available = True
        service._futu.supports_action.return_value = True
        service._futu.fetch.return_value = DataSourceResult.success([{"close": 100}], source="futu")

        result = service.get_kline("HK.00700", interval="1d", num=60)
        assert result.is_success()

    def test_futu_unavailable_yf_fallback(self, service):
        service._futu.is_available = False
        service._yfinance.fetch.return_value = DataSourceResult.success([{"close": 99}], source="yfinance")

        result = service.get_kline("US.AAPL", interval="1d", num=30)
        assert result.is_success()

    def test_a_share_akshare_priority(self, service):
        service._futu.is_available = True
        service._futu.supports_action.return_value = True
        service._futu.fetch.return_value = DataSourceResult.error("A股不支持")
        service._akshare.fetch.return_value = DataSourceResult.success([{"close": 10}], source="akshare")

        result = service.get_kline("SH.600519", interval="1d", num=30)
        assert result.is_success()
        assert result.source == "akshare"

    def test_all_fail(self, service):
        service._futu.is_available = True
        service._futu.supports_action.return_value = True
        service._futu.fetch.return_value = DataSourceResult.error("fail")
        service._yfinance.fetch.return_value = DataSourceResult.error("fail")

        result = service.get_kline("US.AAPL")
        assert result.is_error()


class TestGetFundFlow:
    def test_futu_supports(self, service):
        service._futu.is_available = True
        service._futu.supports_action.return_value = True
        service._futu.fetch.return_value = DataSourceResult.success({"net_inflow": 1000}, source="futu")

        result = service.get_fund_flow("HK.00700")
        assert result.is_success()

    def test_futu_not_support_degraded(self, service):
        service._futu.is_available = False
        result = service.get_fund_flow("US.AAPL")
        assert result.status == "degraded"


class TestGetOptionChain:
    def test_futu_supports(self, service):
        service._futu.is_available = True
        service._futu.supports_action.return_value = True
        service._futu.fetch.return_value = DataSourceResult.success([{"strike": 150}], source="futu")

        result = service.get_option_chain("US.AAPL", expire_date="2024-12-20")
        assert result.is_success()

    def test_futu_not_support_degraded(self, service):
        service._futu.is_available = False
        result = service.get_option_chain("US.AAPL")
        assert result.status == "degraded"


class TestGetQuotesBatch:
    def test_batch_success(self, service):
        service._futu.is_available = True
        service._futu.fetch.return_value = DataSourceResult.success({"price": 100}, source="futu")

        result = service.get_quotes_batch(["US.AAPL", "US.GOOG"])
        assert result.is_success()
        assert "quotes" in result.data

    def test_batch_partial_failure(self, service):
        service._futu.is_available = True
        service._futu.fetch.side_effect = [
            DataSourceResult.success({"price": 100}, source="futu"),
            DataSourceResult.error("fail"),
        ]
        service._yfinance.fetch.return_value = DataSourceResult.error("yf fail")

        result = service.get_quotes_batch(["US.AAPL", "US.INVALID"])
        assert result.is_success()
        assert len(result.data["errors"]) == 1


class TestHealthCheck:
    def test_all_healthy(self, service):
        service._futu.is_available = True
        service._futu.health_check.return_value = {"healthy": True}
        service._yfinance.health_check.return_value = {"healthy": True}
        service._akshare.health_check.return_value = {"healthy": True}

        result = service.health_check()
        assert result["healthy"] is True
        assert result["active_source"] == "futu"

    def test_futu_unavailable(self, service):
        service._futu.is_available = False
        service._yfinance.health_check.return_value = {"healthy": True}
        service._akshare.health_check.return_value = {"healthy": False}

        result = service.health_check()
        assert result["healthy"] is True
        assert result["active_source"] == "yfinance"


class TestToYfFormat:
    def test_hk_format(self, service):
        assert service._to_yf_format("00700.HK") == "00700.HK"

    def test_a_share_sh(self, service):
        result = service._to_yf_format("SH.600519")
        assert ".SS" in result or "600519" in result

    def test_a_share_sz(self, service):
        result = service._to_yf_format("SZ.000858")
        assert ".SZ" in result or "000858" in result

    def test_us_format(self, service):
        assert service._to_yf_format("AAPL") == "AAPL"

    def test_crypto_format(self, service):
        assert service._to_yf_format("BTC-USD") == "BTC-USD"


class TestGetFullKline:
    def test_delegates_to_yfinance(self, service):
        service._yfinance.fetch.return_value = DataSourceResult.success([{"close": 1}], source="yfinance")
        result = service.get_full_kline("US.AAPL")
        assert result.is_success()
        service._yfinance.fetch.assert_called_once()
