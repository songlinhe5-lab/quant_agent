"""
AkShareAdapter 单元测试
覆盖: backend/adapters/akshare/akshare_adapter.py
"""

import time
from unittest.mock import patch

import pandas as pd
import pytest

from backend.adapters.akshare.akshare_adapter import AkShareAdapter


@pytest.fixture
def adapter():
    return AkShareAdapter(enable_cache=True, cache_ttl=300)


@pytest.fixture
def no_cache_adapter():
    return AkShareAdapter(enable_cache=False)


class TestProtocolProperties:
    def test_name(self, adapter):
        assert adapter.name == "akshare"

    def test_version(self, adapter):
        assert adapter.version == "1.0.0"

    def test_capabilities(self, adapter):
        caps = adapter.capabilities
        assert "stock_quote" in caps
        assert "stock_history" in caps
        assert "hsgt_holders" in caps
        assert "hsgt_top10" in caps

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_is_available_true(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame({"代码": ["600519"]})
        assert adapter.is_available is True

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_is_available_false_exception(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.side_effect = Exception("network")
        assert adapter.is_available is False

    def test_is_available_rate_limited(self, adapter):
        adapter._rate_limited_until = time.time() + 100
        assert adapter.is_available is False


class TestFetch:
    def test_unsupported_action(self, adapter):
        result = adapter.fetch("invalid", {})
        assert result.is_error()
        assert "Unsupported action" in result.error

    def test_rate_limited(self, adapter):
        adapter._rate_limited_until = time.time() + 100
        result = adapter.fetch("stock_quote", {"ticker": "SH.600519"})
        assert result.is_rate_limited()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_quote_a_share(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame(
            {
                "代码": ["SH600519"],
                "最新价": [1800.0],
                "涨跌幅": [2.5],
                "振幅": [3.0],
                "成交量": [50000],
                "成交额": [9000000000.0],
                "最高": [1820.0],
                "最低": [1780.0],
                "今开": [1790.0],
                "昨收": [1755.0],
            }
        )
        result = adapter.fetch("stock_quote", {"ticker": "SH.600519"})
        assert result.is_success()
        assert result.source == "akshare"

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_quote_hk(self, mock_ak, adapter):
        mock_ak.stock_hk_spot_em.return_value = pd.DataFrame(
            {
                "代码": ["00700"],
                "最新价": [350.0],
                "涨跌幅": [1.2],
                "振幅": [2.0],
                "成交量": [20000000],
                "成交额": [7000000000.0],
                "最高": [355.0],
                "最低": [345.0],
                "今开": [348.0],
                "昨收": [346.0],
            }
        )
        result = adapter.fetch("stock_quote", {"ticker": "00700.HK"})
        assert result.is_success()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_quote_empty(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame(
            {
                "代码": [],
                "最新价": [],
                "涨跌幅": [],
                "振幅": [],
                "成交量": [],
                "成交额": [],
                "最高": [],
                "最低": [],
                "今开": [],
                "昨收": [],
            }
        )
        result = adapter.fetch("stock_quote", {"ticker": "SH.999999"})
        assert result.is_error()

    def test_fetch_stock_quote_unsupported_format(self, adapter):
        result = adapter.fetch("stock_quote", {"ticker": "AAPL"})
        assert result.is_error()
        assert "Unsupported ticker format" in result.error

    def test_fetch_stock_quote_missing_ticker(self, adapter):
        result = adapter.fetch("stock_quote", {})
        assert result.is_error()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_history_a_share(self, mock_ak, adapter):
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame(
            {
                "日期": ["2024-01-01", "2024-01-02"],
                "开盘": [100.0, 101.0],
                "高": [110.0, 112.0],
                "低": [95.0, 96.0],
                "收盘": [105.0, 108.0],
                "成交量": [10000, 12000],
            }
        )
        result = adapter.fetch("stock_history", {"ticker": "SH.600519", "num": 10})
        assert result.is_success()
        assert len(result.data) == 2

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_history_hk(self, mock_ak, adapter):
        mock_ak.stock_hk_hist.return_value = pd.DataFrame(
            {
                "日期": ["2024-01-01"],
                "开盘": [350.0],
                "高": [360.0],
                "低": [340.0],
                "收盘": [355.0],
                "成交量": [5000000],
            }
        )
        result = adapter.fetch("stock_history", {"ticker": "00700.HK"})
        assert result.is_success()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_stock_history_empty(self, mock_ak, adapter):
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        result = adapter.fetch("stock_history", {"ticker": "SH.600519"})
        assert result.is_success()
        assert result.data == []

    def test_fetch_stock_history_unsupported_format(self, adapter):
        result = adapter.fetch("stock_history", {"ticker": "AAPL"})
        assert result.is_error()

    def test_fetch_stock_history_missing_ticker(self, adapter):
        result = adapter.fetch("stock_history", {})
        assert result.is_error()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_hsgt_holders_north(self, mock_ak, adapter):
        mock_ak.stock_nh_top_holder_em.return_value = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "股票简称": ["贵州茅台"],
                "持有数量": [100000],
                "占流通股比例": [0.8],
                "较上期变化数量": [5000],
            }
        )
        result = adapter.fetch("hsgt_holders", {"symbol": "north_bound"})
        assert result.is_success()
        assert len(result.data) == 1

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_hsgt_holders_south(self, mock_ak, adapter):
        mock_ak.stock_hsgt_north_holder_em.return_value = pd.DataFrame(
            {
                "股票代码": ["00700"],
                "股票简称": ["腾讯控股"],
                "持有数量": [200000],
                "占流通股比例": [1.2],
                "较上期变化数量": [-3000],
            }
        )
        result = adapter.fetch("hsgt_holders", {"symbol": "south_bound"})
        assert result.is_success()

    def test_fetch_hsgt_holders_invalid_type(self, adapter):
        result = adapter.fetch("hsgt_holders", {"symbol": "invalid"})
        assert result.is_error()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_hsgt_top10(self, mock_ak, adapter):
        mock_ak.stock_hsgt_top10_em.return_value = pd.DataFrame(
            {
                "排名": range(1, 11),
                "股票代码": [f"60000{i}" for i in range(10)],
                "股票简称": [f"股票{i}" for i in range(10)],
                "占市值比例": [0.5 * i for i in range(10)],
                "较昨日变化": [0.1 * i for i in range(10)],
            }
        )
        result = adapter.fetch("hsgt_top10", {})
        assert result.is_success()
        assert len(result.data) == 10

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_hsgt_top10_exception(self, mock_ak, adapter):
        mock_ak.stock_hsgt_top10_em.side_effect = Exception("API down")
        result = adapter.fetch("hsgt_top10", {})
        assert result.is_error()

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_fetch_exception_handling(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.side_effect = Exception("unexpected")
        result = adapter.fetch("stock_quote", {"ticker": "SH.600519"})
        assert result.is_error()


class TestRateLimiting:
    def test_is_rate_limited_false(self, adapter):
        assert adapter._is_rate_limited is False

    def test_is_rate_limited_expired(self, adapter):
        adapter._rate_limited_until = time.time() - 1
        assert adapter._is_rate_limited is False

    def test_is_rate_limited_active(self, adapter):
        adapter._rate_limited_until = time.time() + 100
        assert adapter._is_rate_limited is True

    def test_record_request_triggers_limit(self, adapter):
        adapter._request_count = 19  # 再来一次就触发
        adapter._record_request()
        assert adapter._request_count == 20
        assert adapter._rate_limited_until is not None


class TestCaching:
    def test_get_cached_disabled(self, no_cache_adapter):
        assert no_cache_adapter._get_cached("key") is None

    def test_set_cache_disabled(self, no_cache_adapter):
        no_cache_adapter._set_cache("key", "data")
        assert len(no_cache_adapter._cache) == 0

    def test_get_cached_valid(self, adapter):
        adapter._cache["k"] = {"data": "v", "expires_at": time.time() + 100}
        assert adapter._get_cached("k") == "v"

    def test_get_cached_expired(self, adapter):
        adapter._cache["k"] = {"data": "v", "expires_at": time.time() - 1}
        assert adapter._get_cached("k") is None
        assert "k" not in adapter._cache


class TestHealthCheck:
    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_healthy(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.return_value = pd.DataFrame({"代码": ["600519"]})
        result = adapter.health_check()
        assert result["healthy"] is True

    @patch("backend.adapters.akshare.akshare_adapter.ak")
    def test_unhealthy(self, mock_ak, adapter):
        mock_ak.stock_zh_a_spot_em.side_effect = Exception("down")
        result = adapter.health_check()
        assert result["healthy"] is False
        assert "error" in result
