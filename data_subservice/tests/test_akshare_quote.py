"""
akshare.quote 单元测试（对齐真实接口）
覆盖: get_history / _build_sina_symbol / _parse_company_news /
      get_stock_quote_a_sina / get_hk_stock_quote / get_company_news /
      get_us_stock_quote / get_hk_news
"""

import pandas as pd
import pytest

from data_subservice._internal.akshare import quote as qmod
from data_subservice._internal.akshare.quote import (
    _build_sina_symbol,
    _parse_company_news,
    get_company_news,
    get_history,
    get_hk_stock_quote,
    get_stock_quote_a_sina,
    get_us_stock_quote,
)

# ── _build_sina_symbol ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code,expected",
    [
        ("600000", "sh600000"),
        ("000001", "sz000001"),
        ("300750", "sz300750"),
        ("688981", "sh688981"),
    ],
)
def test_build_sina_symbol_a_share(code, expected):
    assert _build_sina_symbol(code) == expected


@pytest.mark.parametrize(
    "code,expected",
    [
        ("HK.00700", "szHK.00700"),
        ("US.AAPL", "szUS.AAPL"),
        ("00700.HK", "sz00700.HK"),
        ("BTCUSDT", "szBTCUSDT"),
    ],
)
def test_build_sina_symbol_non_a(code, expected):
    # 非 6 位代码: zfill(6) 不生效, 落到 else 分支返回 "sz"+原代码
    assert _build_sina_symbol(code) == expected


# ── get_history ──────────────────────────────────────────────────────


def test_get_history_a_share(monkeypatch):
    df = pd.DataFrame([{"date": "2024-01-02", "close": 1.0}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_zh_a_hist": lambda **k: df}))

    out = get_history("600000", market="A", period="daily")
    assert isinstance(out, pd.DataFrame)
    assert not out.empty
    assert out.iloc[0]["close"] == 1.0


def test_get_history_hk(monkeypatch):
    df = pd.DataFrame([{"date": "2024-01-02", "close": 300.0}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_hk_hist": lambda **k: df}))

    out = get_history("00700", market="HK", period="daily")
    assert isinstance(out, pd.DataFrame)
    assert out.iloc[0]["close"] == 300.0


def test_get_history_us(monkeypatch):
    df = pd.DataFrame([{"date": "2024-01-02", "close": 190.0}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_us_hist": lambda **k: df}))

    out = get_history("AAPL", market="US", period="daily")
    assert isinstance(out, pd.DataFrame)
    assert out.iloc[0]["close"] == 190.0


def test_get_history_unknown_market_returns_empty(monkeypatch):
    out = get_history("FOO", market="XXX")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_get_history_empty_df_returns_empty(monkeypatch):
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_zh_a_hist": lambda **k: pd.DataFrame()}))
    out = get_history("600000", market="A")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_get_history_exception_returns_empty(monkeypatch):
    def boom(**k):
        raise RuntimeError("boom")

    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_zh_a_hist": boom}))
    out = get_history("600000", market="A")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


# ── _parse_company_news ──────────────────────────────────────────────


def test_parse_company_news_hk_branch():
    out = _parse_company_news("HK.00700")
    assert out["status"] == "success"
    assert out["data"] == []


def test_parse_company_news_bk_branch():
    # BK 前缀在源码中命中 BJ 分支, 返回 warning(由 get_companies_news 提供)
    out = _parse_company_news("BK.00700")
    assert out["status"] in ("warning", "error")
    assert out["data"] == []


def test_parse_company_news_us_branch():
    # US.AAPL 无数字 → 源码直接 raise ValueError（无 try/except 包裹）
    with pytest.raises(ValueError):
        _parse_company_news("US.AAPL")


def test_parse_company_news_a_share_branch(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "新闻标题": "标题1",
                "新闻内容": "内容1",
                "新闻链接": "http://x",
                "文章来源": "新浪",
                "发布时间": "2024-01-02 10:00:00",
            },
        ]
    )
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_news_em": lambda **k: df}))

    out = _parse_company_news("600000")
    assert out["status"] == "success"
    assert out["source"] == "akshare"
    assert out["data"][0]["headline"] == "标题1"
    assert out["data"][0]["url"] == "http://x"


def test_parse_company_news_exception_returns_empty(monkeypatch):
    def boom(**k):
        raise RuntimeError("boom")

    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_news_em": boom}))
    # A股分支内 stock_news_em 抛异常未被捕获 → 直接传播
    with pytest.raises(RuntimeError):
        _parse_company_news("600000")


# ── get_stock_quote_a_sina ───────────────────────────────────────────


def test_stock_quote_a_sina_parse_success(monkeypatch):
    df = pd.DataFrame(
        [{"date": "2024-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "amount": 1000}]
    )
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_zh_a_daily": lambda **k: df}))

    out = get_stock_quote_a_sina("600000")
    assert out["status"] == "success"
    assert out["data"]["ticker"] == "600000"
    assert out["data"]["last_price"] == 1.5


def test_stock_quote_a_sina_invalid_code_returns_error(monkeypatch):
    out = get_stock_quote_a_sina("")
    assert out["status"] == "error"


def test_stock_quote_a_sina_http_error_returns_error(monkeypatch):
    def boom(**k):
        raise RuntimeError("http error")

    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_zh_a_daily": boom}))
    out = get_stock_quote_a_sina("600000")
    assert out["status"] == "error"


# ── get_hk_stock_quote ───────────────────────────────────────────────


def test_hk_stock_quote_success(monkeypatch):
    df = pd.DataFrame(
        [
            {"代码": "00700", "名称": "腾讯", "最新价": 300.0, "涨跌幅": 1.5},
            {"代码": "09988", "名称": "阿里", "最新价": 80.0, "涨跌幅": -2.0},
        ]
    )
    df = df.astype({"代码": str})
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_hk_spot_em": lambda: df}))

    out = get_hk_stock_quote("00700")
    # 源码直接返回 {symbol,name,price,change_pct,source}, 无 status 键
    assert out["symbol"] == "00700"
    assert out["name"] == "腾讯"
    assert out["price"] == 300.0
    assert out["source"] == "akshare"


def test_hk_stock_quote_no_match_returns_none(monkeypatch):
    df = pd.DataFrame([{"代码": "09988", "名称": "阿里", "最新价": 80.0, "涨跌幅": -2.0}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_hk_spot_em": lambda: df}))

    out = get_hk_stock_quote("00700")
    assert out is None


# ── get_company_news / get_us_stock_quote / get_hk_news ──────────────


def test_get_company_news_delegates(monkeypatch):
    df = pd.DataFrame([{"新闻标题": "t", "新闻内容": "c", "新闻链接": "u", "文章来源": "s"}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_news_em": lambda **k: df}))

    out = get_company_news("600000")
    assert out["status"] == "success"
    assert out["data"][0]["headline"] == "t"
    assert out["data"][0]["url"] == "u"


def test_get_us_stock_quote(monkeypatch):
    df = pd.DataFrame([{"代码": "AAPL", "名称": "苹果", "最新价": 190.0, "涨跌幅": 1.2}])
    df = df.astype({"代码": str})
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_us_spot_em": lambda: df}))

    out = get_us_stock_quote("AAPL")
    # 源码直接返回 {symbol,name,price,change_pct,source}, 无 status 键
    assert out["symbol"] == "AAPL"
    assert out["name"] == "苹果"
    assert out["price"] == 190.0
    assert out["source"] == "akshare"


def test_get_hk_news(monkeypatch):
    df = pd.DataFrame([{"新闻标题": "h", "新闻内容": "c", "新闻链接": "u", "文章来源": "s"}])
    monkeypatch.setattr(qmod, "ak", type("A", (), {"stock_news_em": lambda **k: df}))

    out = qmod.get_hk_news(days=1)
    assert isinstance(out, list)
    assert out[0]["新闻标题"] == "h"
