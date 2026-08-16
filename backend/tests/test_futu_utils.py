"""
Futu 工具函数单元测试
覆盖 backend/services/futu/utils.py 的 ticker 格式化与动态不支持集合逻辑。
纯函数无外部依赖，全部可直接断言。
"""

import pytest

from backend.services.futu.utils import (
    format_ticker,
    is_futu_unsupported,
    mark_futu_unsupported,
)


class TestFormatTicker:
    """format_ticker 各市场格式映射"""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("HSI", "HK.800000"),
            ("HSTECH", "HK.800700"),
            ("SPX", "US.SPX"),
            ("NDX", "US.NDX"),
            ("TSMC", "US.TSM"),
            ("US.TSMC", "US.TSM"),
            ("00700.HK", "HK.00700"),
            ("HK.00700", "HK.00700"),
            ("600519.SH", "SH.600519"),
            ("600519.SS", "SH.600519"),
            ("000001.SZ", "SZ.000001"),
            ("AAPL.US", "US.AAPL"),
            ("US.AAPL", "US.AAPL"),
            ("JP.1234", "JP.1234"),
            ("SG.X", "SG.X"),
            ("UK.X", "UK.X"),
            ("LSE.X", "LSE.X"),
            ("aapl", "US.AAPL"),  # 默认补 US. 前缀 + 大写
        ],
    )
    def test_format_ticker_cases(self, raw, expected):
        assert format_ticker(raw) == expected


class TestIsFutuUnsupported:
    """is_futu_unsupported 静态规则 + 动态集合"""

    def test_static_symbols(self):
        # 雅虎专用符号 → 不支持
        assert is_futu_unsupported("ES=F")
        assert is_futu_unsupported("BTC-USD")
        assert is_futu_unsupported("^VIX")

    def test_static_special_macro(self):
        assert is_futu_unsupported("DX-Y.NYB")
        assert is_futu_unsupported("DGS10")
        assert is_futu_unsupported("GC=F")
        assert is_futu_unsupported("CL=F")
        assert is_futu_unsupported("HG=F")

    def test_supported_normal_ticker(self):
        assert not is_futu_unsupported("AAPL")
        assert not is_futu_unsupported("HK.00700")
        assert not is_futu_unsupported("US.AAPL")

    def test_dynamic_set(self):
        # 运行时探测标记
        assert mark_futu_unsupported("US.VIX") is True
        assert is_futu_unsupported("US.VIX") is True
        # 幂等：重复标记返回 False
        assert mark_futu_unsupported("US.VIX") is False
        assert is_futu_unsupported("US.VIX") is True

    def test_mark_empty(self):
        assert mark_futu_unsupported("") is False
        assert mark_futu_unsupported(None) is False
