"""YFinance search_tickers 单元测试 (成功分支 + 异常兜底分支)。

yfinance.Tickers 经 mock 替换, 不触真实 Yahoo 网络。
"""

from unittest.mock import MagicMock, patch

from data_subservice._internal.yfinance import search as yf_search


class _FakeFastInfo:
    def __init__(self, name, currency, exchange):
        self.short_name = name
        self.currency = currency
        self.exchange = exchange


class _FakeTicker:
    def __init__(self, name, currency, exchange):
        self.fast_info = _FakeFastInfo(name, currency, exchange)


class _BadTicker:
    """fast_info 访问即抛 AttributeError, 触发真实代码中的 except 跳过。"""

    @property
    def fast_info(self):
        raise AttributeError("no fast_info available")


class TestSearchTickers:
    def test_success(self):
        fake = MagicMock()
        fake.tickers = {
            "AAPL": _FakeTicker("Apple", "USD", "NASDAQ"),
            "MSFT": _FakeTicker("Microsoft", "USD", "NASDAQ"),
        }
        with patch.object(yf_search.yf, "Tickers", return_value=fake):
            items = yf_search.search_tickers("app", limit=10)
        assert len(items) == 2
        assert items[0]["symbol"] == "AAPL"
        assert items[0]["name"] == "Apple"

    def test_limit(self):
        fake = MagicMock()
        fake.tickers = {
            "AAPL": _FakeTicker("Apple", "USD", "NASDAQ"),
            "MSFT": _FakeTicker("Microsoft", "USD", "NASDAQ"),
            "GOOG": _FakeTicker("Alphabet", "USD", "NASDAQ"),
        }
        with patch.object(yf_search.yf, "Tickers", return_value=fake):
            items = yf_search.search_tickers("a", limit=2)
        assert len(items) == 2

    def test_fast_info_exception_skipped(self):
        good = _FakeTicker("Apple", "USD", "NASDAQ")
        bad = _BadTicker()
        fake = MagicMock()
        fake.tickers = {"AAPL": good, "BAD": bad}
        with patch.object(yf_search.yf, "Tickers", return_value=fake):
            items = yf_search.search_tickers("a")
        assert [i["symbol"] for i in items] == ["AAPL"]

    def test_top_level_exception_returns_empty(self):
        with patch.object(yf_search.yf, "Tickers", side_effect=RuntimeError("network")):
            items = yf_search.search_tickers("a")
        assert items == []
