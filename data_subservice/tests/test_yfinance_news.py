"""yfinance 子服务 NEWS action 测试（BE-ARCH-07j: 主服务 Yahoo 直连收口底层）。

验证 fetch_news 调用 yfinance Ticker.news 并归一化为统一字段结构，
异常时优雅返回空列表（不向上抛）。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 允许以脚本方式运行（子服务独立 pytest 入口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_subservice._internal.yfinance import quote as yf_quote  # noqa: E402


class _FakeNewsItem(dict):
    pass


def _make_ticker(news):
    ticker = MagicMock()
    ticker.news = news
    return ticker


@pytest.mark.asyncio
async def test_fetch_news_normalizes_fields():
    raw = [
        {
            "uuid": 1,
            "title": "Apple unveils new chip",
            "publisher": "Bloomberg",
            "link": "https://bloomberg.com/1",
            "providerPublishTime": 1700000000,
            "type": "STORY",
            "relatedTickers": ["MSFT"],
        }
    ]

    class _FakeYf:
        def Ticker(self, code):
            return _make_ticker(raw)

    with patch.object(yf_quote, "yf", _FakeYf()):
        out = yf_quote.fetch_news("AAPL", limit=15)

    assert len(out) == 1
    item = out[0]
    assert item["title"] == "Apple unveils new chip"
    assert item["publisher"] == "Bloomberg"
    assert item["link"] == "https://bloomberg.com/1"
    assert item["provider_publish_time"] == 1700000000
    assert item["related_tickers"] == ["MSFT"]


@pytest.mark.asyncio
async def test_fetch_news_empty_on_error():
    class _BoomYf:
        def Ticker(self, code):
            raise RuntimeError("yahoo down")

    with patch.object(yf_quote, "yf", _BoomYf()):
        out = yf_quote.fetch_news("AAPL")

    assert out == []


@pytest.mark.asyncio
async def test_fetch_news_limits_count():
    raw = [{"title": f"n{i}", "publisher": "X"} for i in range(30)]
    with patch.object(yf_quote, "yf", type("Y", (), {"Ticker": lambda self, c: _make_ticker(raw)})()):
        out = yf_quote.fetch_news("AAPL", limit=5)
    assert len(out) == 5
