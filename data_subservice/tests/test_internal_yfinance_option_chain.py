"""
yfinance 期权链（fetch_option_chain）单元测试。

覆盖 2026-08-30 S1 实战回归：无期权链标的（港股 / 无期权品种）的
chain.calls / chain.puts 为 None，旧代码兜底后直接 iterrows() →
'NoneType' object has no attribute 'iterrows' → 被主服务判为「源级失败」
计入 throttler，累积后触发 yfinance 全节点 300s 退避
（0772.HK 触发，consecutive=15 / wait=300.4s），连累所有走 yfinance
的请求，表现为工具长时间无响应。
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_subservice._internal.yfinance import quote as quote_mod


class _FakeChain:
    """模拟 yfinance OptionsChain：迭代产出到期日列表。"""

    def __init__(self, expirations, calls, puts):
        self._expirations = expirations
        self.calls = calls
        self.puts = puts

    def __iter__(self):
        return iter(self._expirations)


def _patch_ticker(chain):
    ticker = MagicMock()
    ticker.option_chain.return_value = chain
    return patch.object(quote_mod.yf, "Ticker", return_value=ticker)


def _opts_df(rows):
    return pd.DataFrame(
        [
            {
                "strike": r[0],
                "bid": 1.0,
                "ask": 1.2,
                "lastPrice": r[1],
                "volume": 10,
                "openInterest": 20,
                "impliedVolatility": 0.35,
                "expirationDate": "2026-09-18",
            }
            for r in rows
        ]
    )


def test_calls_and_puts_none_returns_empty_not_error():
    """回归核心：calls/puts 为 None 时不得抛 AttributeError，应返回空结果。"""
    chain = _FakeChain(["2026-09-18"], None, None)

    with _patch_ticker(chain):
        res = quote_mod.fetch_option_chain("0772.HK")

    assert "error" not in res, f"不应产生错误响应: {res.get('error')}"
    assert res["count"] == 0
    assert res["calls"] == []
    assert res["puts"] == []
    assert res["options"] == []


def test_chain_none_returns_empty():
    """option_chain() 直接返回 None 时同样安全。"""
    with _patch_ticker(None):
        res = quote_mod.fetch_option_chain("0772.HK")

    assert "error" not in res
    assert res["count"] == 0


def test_partial_none_is_tolerated():
    """仅有 puts 为 None（calls 正常）时不崩溃，calls 仍被解析。"""
    chain = _FakeChain(["2026-09-18"], _opts_df([(100.0, 3.5)]), None)

    with _patch_ticker(chain):
        res = quote_mod.fetch_option_chain("AAPL")

    assert res["count"] == 1
    assert res["calls"][0]["strike"] == 100.0
    assert res["calls"][0]["option_type"] == "CALL"
    assert res["puts"] == []


def test_normal_chain_parsed():
    """正常期权链：calls/puts 均解析，IV 字段归一化。"""
    chain = _FakeChain(
        ["2026-09-18"],
        _opts_df([(100.0, 3.5)]),
        _opts_df([(105.0, 1.5)]),
    )

    with _patch_ticker(chain):
        res = quote_mod.fetch_option_chain("AAPL")

    assert res["count"] == 2
    assert res["calls"][0]["option_type"] == "CALL"
    assert res["puts"][0]["option_type"] == "PUT"
    assert res["calls"][0]["implied_volatility"] == 0.35


def test_empty_dataframe_returns_empty():
    """空 DataFrame（有列无行）不应报错。"""
    chain = _FakeChain(["2026-09-18"], pd.DataFrame(columns=["strike"]), pd.DataFrame(columns=["strike"]))

    with _patch_ticker(chain):
        res = quote_mod.fetch_option_chain("AAPL")

    assert res["count"] == 0


@pytest.mark.parametrize("calls_value", [None, "not-a-dataframe", 123])
def test_non_dataframe_calls_skipped(calls_value):
    """calls 为非 DataFrame 的异常形态一律跳过，不抛异常。"""
    chain = _FakeChain(["2026-09-18"], calls_value, _opts_df([(105.0, 1.5)]))

    with _patch_ticker(chain):
        res = quote_mod.fetch_option_chain("AAPL")

    assert res["calls"] == []
    assert res["count"] == 1  # puts 仍正常解析
