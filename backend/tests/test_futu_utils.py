"""
Futu 子系统工具函数与缓存管理器单元测试
覆盖:
- backend/services/futu/utils.py
- backend/services/futu/cache_manager.py
- backend/services/futu/mock_provider.py
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


from backend.services.futu.cache_manager import CacheManager
from backend.services.futu.mock_provider import MockProvider
from backend.services.futu.utils import format_ticker, is_futu_unsupported


# ─── utils.py ──────────────────────────────────────────────────────────
class TestFutuUtils:
    """Futu 工具函数单元测试"""

    def test_is_futu_unsupported_forex_ticker_returns_true(self):
        """外汇类（含 =）应被识别为不支持"""
        assert is_futu_unsupported("USDJPY=X") is True
        assert is_futu_unsupported("JPY=X") is True

    def test_is_futu_unsupported_index_ticker_returns_true(self):
        """指数类（含 ^）应被识别为不支持"""
        assert is_futu_unsupported("^VIX") is True
        assert is_futu_unsupported("^GSPC") is True

    def test_is_futu_unsupported_special_ticker_returns_true(self):
        """特定大宗商品代码（如 GC=F, CL=F, DX-Y.NYB, DGS10）应被识别为不支持"""
        for ticker in ["GC=F", "CL=F", "HG=F", "DX-Y.NYB", "DGS10"]:
            assert is_futu_unsupported(ticker) is True, f"{ticker} 应被识别为不支持"

    def test_is_futu_unsupported_normal_stock_returns_false(self):
        """普通股票代码应不被识别为不支持"""
        assert is_futu_unsupported("HK.00700") is False
        assert is_futu_unsupported("US.AAPL") is False
        assert is_futu_unsupported("00700") is False

    def test_is_futu_unsupported_case_insensitive(self):
        """大小写不敏感"""
        assert is_futu_unsupported("usdjpy=x") is True
        assert is_futu_unsupported("gc=f") is True

    def test_format_ticker_index_mapping(self):
        """指数代码应映射为富途标准代码"""
        assert format_ticker("HSI") == "HK.800000"
        assert format_ticker("HSTECH") == "HK.800700"
        assert format_ticker("SPX") == "US.SPX"
        assert format_ticker("NDX") == "US.NDX"
        assert format_ticker("TSMC") == "US.TSM"
        assert format_ticker("US.TSMC") == "US.TSM"

    def test_format_ticker_hk_padding(self):
        """港股代码应自动补 0 至 5 位"""
        assert format_ticker("HK.700") == "HK.00700"
        assert format_ticker("00700.HK") == "HK.00700"
        # 非纯数字代码不补 0
        assert format_ticker("HK.HSTECH") == "HK.HSTECH"

    def test_format_ticker_sh_sz_us_prefix(self):
        """沪深美股后缀应转换为前缀格式"""
        assert format_ticker("600000.SH") == "SH.600000"
        assert format_ticker("000001.SS") == "SH.000001"
        assert format_ticker("000001.SZ") == "SZ.000001"
        assert format_ticker("AAPL.US") == "US.AAPL"

    def test_format_ticker_already_prefixed_pass_through(self):
        """已带市场前缀的应原样返回"""
        for ticker in ["US.AAPL", "SH.600000", "SZ.000001", "JP.7203", "SG.A17U", "LSE.BP"]:
            assert format_ticker(ticker) == ticker.upper()

    def test_format_ticker_bare_us_default(self):
        """裸代码默认按美股处理"""
        assert format_ticker("AAPL") == "US.AAPL"
        assert format_ticker("nvda") == "US.NVDA"


# ─── cache_manager.py ──────────────────────────────────────────────────
class TestCacheManager:
    """CacheManager 单元测试"""

    @pytest.fixture
    def cache(self):
        return CacheManager()

    def test_initial_state(self, cache):
        """初始化时所有缓存应为空"""
        assert cache.subscribed_topics == set()
        assert cache._quote_cache == {}
        assert cache._history_cache == {}
        assert cache._option_chain_cache == {}
        assert cache._fund_flow_cache == {}
        assert cache._order_book_cache == {}
        assert cache._fundamental_cache == {}
        assert cache.ff_lock is None
        assert cache.last_ff_time == 0.0
        assert cache.ff_circuit_breaker_until == 0.0

    def test_quote_cache_get_set(self, cache):
        """quote 缓存读写应正常"""
        assert cache.get_quote_cache("HK.00700") is None
        data = {"last_price": 400.0}
        cache.set_quote_cache("HK.00700", 1000.0, data)
        result = cache.get_quote_cache("HK.00700")
        assert result == (1000.0, data)

    def test_history_cache_get_set(self, cache):
        """history 缓存读写应正常"""
        assert cache.get_history_cache("key_1") is None
        cache.set_history_cache("key_1", 2000.0, {"data": []})
        ts, data = cache.get_history_cache("key_1")
        assert ts == 2000.0
        assert data == {"data": []}

    def test_option_chain_cache_get_set(self, cache):
        assert cache.get_option_chain_cache("opt_1") is None
        cache.set_option_chain_cache("opt_1", 3000.0, {"options": []})
        assert cache.get_option_chain_cache("opt_1") == (3000.0, {"options": []})

    def test_fund_flow_cache_get_set(self, cache):
        assert cache.get_fund_flow_cache("ff_1") is None
        cache.set_fund_flow_cache("ff_1", 4000.0, {"net_inflow": 100})
        assert cache.get_fund_flow_cache("ff_1") == (4000.0, {"net_inflow": 100})

    def test_order_book_cache_get_set(self, cache):
        assert cache.get_order_book_cache("ob_1") is None
        cache.set_order_book_cache("ob_1", 5000.0, {"bids": []})
        assert cache.get_order_book_cache("ob_1") == (5000.0, {"bids": []})

    def test_fundamental_cache_get_set(self, cache):
        assert cache.get_fundamental_cache("fd_1") is None
        cache.set_fundamental_cache("fd_1", 6000.0, {"pe": 15.0})
        assert cache.get_fundamental_cache("fd_1") == (6000.0, {"pe": 15.0})

    def test_compress_chain_data_truncates_to_60_rows(self, cache):
        """compress_chain_data 应截断至前 60 行"""
        rows = [{"code": f"OPT{i}", "option_type": "CALL", "strike_price": 100.0 + i} for i in range(100)]
        df = pd.DataFrame(rows)
        result = cache.compress_chain_data(df, "2024-01-19")
        assert result["status"] == "success"
        assert result["expiration_date"] == "2024-01-19"
        assert result["count"] == 60
        assert len(result["options"]) == 60
        assert result["options"][0]["option_code"] == "OPT0"
        assert result["options"][-1]["option_code"] == "OPT59"

    def test_compress_chain_data_handles_missing_fields(self, cache):
        """字段缺失时应使用兜底空值/0.0"""
        df = pd.DataFrame([{"code": "X"}])  # 缺 option_type, strike_price
        result = cache.compress_chain_data(df, "2024-01-19")
        assert result["count"] == 1
        assert result["options"][0]["option_code"] == "X"
        assert result["options"][0]["option_type"] == ""
        assert result["options"][0]["strike_price"] == 0.0

    def test_compress_quote_data_basic_fields(self, cache):
        """compress_quote_data 应正确提取基础行情字段"""
        row = {
            "code": "HK.00700",
            "last_price": 400.0,
            "prev_close_price": 397.0,
            "volume": 1500000,
            "turnover_rate": 1.5,
        }
        result = cache.compress_quote_data(row)
        assert result["status"] == "success"
        assert result["source"] == "futu"
        assert result["ticker"] == "HK.00700"
        assert result["last_price"] == 400.0
        assert result["change_pct"] == "+0.76%"
        assert result["volume"] == 1500000
        assert result["volume_str"] == "1.50M"

    def test_compress_quote_data_volume_formats(self, cache):
        """volume_str 应根据数量级格式化"""
        # 1B 级
        row = {"code": "X", "last_price": 1.0, "prev_close_price": 1.0, "volume": 1.5e9}
        assert cache.compress_quote_data(row)["volume_str"] == "1.50B"
        # 1M 级
        row["volume"] = 1.5e6
        assert cache.compress_quote_data(row)["volume_str"] == "1.50M"
        # 1K 级
        row["volume"] = 1.5e3
        assert cache.compress_quote_data(row)["volume_str"] == "1.50K"
        # 小于 1K (safe_float 会转为浮点，str 输出 "999.0")
        row["volume"] = 999
        assert cache.compress_quote_data(row)["volume_str"] == "999.0"

    def test_compress_quote_data_zero_prev_close_safe(self, cache):
        """prev_close 为 0 时 change_pct 应安全返回 0%"""
        row = {"code": "X", "last_price": 100.0, "prev_close_price": 0, "volume": 1000}
        result = cache.compress_quote_data(row)
        assert result["change_pct"] == "+0.00%"

    def test_compress_quote_data_extracts_option_fields(self, cache):
        """期权特有字段（strike、iv、delta 等）应被动态提取"""
        row = {
            "code": "OPT",
            "last_price": 3.5,
            "prev_close_price": 3.0,
            "volume": 1000,
            "strike_price": 150.0,
            "option_implied_volatility": 0.35,
            "option_delta": 0.45,
            "option_gamma": 0.05,
            "option_vega": 0.20,
            "option_theta": -0.1,
        }
        result = cache.compress_quote_data(row)
        assert result["strike_price"] == 150.0
        assert result["implied_volatility"] == 0.35
        assert result["delta"] == 0.45
        assert result["gamma"] == 0.05
        assert result["vega"] == 0.20
        assert result["theta"] == -0.1

    def test_compress_quote_data_skips_nan_option_fields(self, cache):
        """期权字段值为 'nan' / 'none' 时应被跳过"""
        row = {
            "code": "OPT",
            "last_price": 3.5,
            "prev_close_price": 3.0,
            "volume": 1000,
            "strike_price": "nan",
            "option_delta": "none",
        }
        result = cache.compress_quote_data(row)
        assert "strike_price" not in result
        assert "delta" not in result


# ─── mock_provider.py ──────────────────────────────────────────────────
class TestMockProvider:
    """MockProvider 单元测试"""

    def test_mock_quote_normal_stock(self):
        """普通股票 mock 行情应包含必要字段"""
        result = MockProvider.mock_quote("HK.00700")
        assert result["status"] == "success"
        assert result["ticker"] == "HK.00700"
        assert result["last_price"] == 150.0
        assert result["source"] == "mock"
        assert "change_pct" in result

    def test_mock_quote_option_contract(self):
        """期权合约代码（含 C0/P0）应返回期权特有字段"""
        result = MockProvider.mock_quote("US.AAPL240119C00150000")
        assert result["last_price"] == 3.50
        assert result["strike_price"] == 150.0
        assert result["implied_volatility"] == 0.35
        assert result["delta"] == 0.45

    def test_mock_history_uses_0700_base(self):
        """包含 0700 的 ticker 应使用 370 的 base price"""
        result = MockProvider.mock_history("HK.00700", 5)
        assert result["status"] == "success"
        assert result["ticker"] == "HK.00700"
        assert len(result["data"]) == 5
        # 腾讯基准价 370，sin 振幅 370*0.02=7.4，所有价格应在 370±7.4*1.01 范围
        assert all(abs(kl["close"] - 370.0) < 8.0 for kl in result["data"])

    def test_mock_history_uses_btc_base(self):
        """包含 BTC 的 ticker 应使用 65000 的 base price"""
        result = MockProvider.mock_history("US.BTC", 3)
        assert len(result["data"]) == 3
        assert all(abs(kl["close"] - 65000.0) < 1500.0 for kl in result["data"])

    def test_mock_history_default_base(self):
        """其他 ticker 应使用默认 150 的 base price"""
        result = MockProvider.mock_history("US.AAPL", 2)
        assert len(result["data"]) == 2
        assert all(abs(kl["close"] - 150.0) < 5.0 for kl in result["data"])

    def test_mock_option_chain_structure(self):
        """期权链 mock 应包含 CALL 和 PUT 各一条"""
        result = MockProvider.mock_option_chain("US.AAPL", "2024-01-19")
        assert result["status"] == "success"
        assert result["expiration_date"] == "2024-01-19"
        assert result["count"] == 2
        types = [opt["option_type"] for opt in result["options"]]
        assert "CALL" in types
        assert "PUT" in types

    def test_mock_option_chain_default_date(self):
        """未提供 expiration_date 时应使用默认 2024-01-19"""
        result = MockProvider.mock_option_chain("US.AAPL", "")
        assert result["expiration_date"] == "2024-01-19"

    def test_mock_fund_flow_hk_includes_broker_queue(self):
        """HK 标的 mock 资金流应包含经纪商队列"""
        result = MockProvider.mock_fund_flow("HK.00700")
        assert result["status"] == "success"
        assert result["broker_queue"] is not None
        assert "bid_brokers_queue_str" in result["broker_queue"]
        assert result["order_book_level_1"] is not None

    def test_mock_fund_flow_non_hk_no_broker_queue(self):
        """非 HK 标的 mock 资金流不应包含经纪商队列"""
        result = MockProvider.mock_fund_flow("US.AAPL")
        assert result["broker_queue"] is None
        assert result["order_book_level_1"] is None

    def test_mock_fundamental_structure(self):
        result = MockProvider.mock_fundamental("HK.00700")
        assert result["status"] == "success"
        assert result["data"]["ticker"] == "HK.00700"
        assert result["data"]["trailing_PE"] == 15.5
        assert result["data"]["market_cap"] == 50000000000.0

    def test_mock_order_book_structure(self):
        """盘口 mock 应有 10 档买卖"""
        result = MockProvider.mock_order_book("HK.00700")
        assert result["status"] == "success"
        assert len(result["bids"]) == 10
        assert len(result["asks"]) == 10
        # 0700 应使用 370 的基准价，bids[0]=370.0，asks[0]=370.1
        assert result["bids"][0]["price"] == 370.0
        assert result["asks"][0]["price"] == 370.1
        # 买卖价差应正向递增/递减
        assert result["bids"][1]["price"] < result["bids"][0]["price"]
        assert result["asks"][1]["price"] > result["asks"][0]["price"]

    def test_mock_account_info_hk(self):
        result = MockProvider.mock_account_info("HK", "SIMULATE")
        assert result["status"] == "success"
        assert result["market"] == "HK"
        assert result["currency"] == "HKD"
        assert result["positions"][0]["code"] == "HK.00700"

    def test_mock_account_info_us(self):
        result = MockProvider.mock_account_info("US", "REAL")
        assert result["market"] == "US"
        assert result["currency"] == "USD"
        assert result["positions"][0]["code"] == "US.AAPL"
