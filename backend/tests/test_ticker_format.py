"""Ticker 格式化纯函数单测 (BE-ARCH-01)"""

import pytest

from backend.core.ticker_format import format_ticker, format_yf_ticker


@pytest.mark.parametrize(
    "inp,exp",
    [
        ("TSMC", "US.TSM"),  # 指数映射命中
        ("US.TSMC", "US.TSM"),  # 指数映射命中 (US. 前缀)
        ("700.HK", "HK.00700"),  # .HK 后缀补零
        ("HK.700", "HK.00700"),  # HK. 前缀补零透传
        ("600000.SH", "SH.600000"),  # .SH 后缀
        ("600000.SS", "SH.600000"),  # .SS 后缀等价
        ("000001.SZ", "SZ.000001"),  # .SZ 后缀
        ("AAPL.US", "US.AAPL"),  # .US 后缀
        ("AAPL", "US.AAPL"),  # 裸符号默认 US
        ("US.AAPL", "US.AAPL"),  # US. 前缀透传
    ],
)
def test_format_ticker(inp, exp):
    assert format_ticker(inp) == exp


@pytest.mark.parametrize(
    "inp,exp",
    [
        ("BTCUSD", "BTC-USD"),  # index_map 命中 (BTC-USD)
        ("SOLUSD", "SOL-USD"),  # 加密裸符号 *-USD 防御 (不在 index_map, 走 77-79)
        ("BTC", "BTC-USD"),  # 指数映射命中
        ("SH.600000", "600000.SS"),  # SH. -> .SS
        ("600000.SH", "600000.SS"),  # .SH -> .SS
        ("SZ.000001", "000001.SZ"),  # SZ. -> .SZ
        ("JP.1234", "1234.T"),  # JP. -> .T
        ("SG.X", "X.SI"),  # SG. -> .SI
        ("UK.VOD", "VOD.L"),  # UK. -> .L
        ("LSE.VOD", "VOD.L"),  # LSE. -> .L
        ("700.HK", "0700.HK"),  # .HK 后缀补零 (82-83)
        ("000001.SS", "000001.SS"),  # 已是 YF 格式透传
    ],
)
def test_format_yf_ticker(inp, exp):
    assert format_yf_ticker(inp) == exp
