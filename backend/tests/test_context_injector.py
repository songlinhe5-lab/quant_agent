"""MRKT-05: 判因上下文注入器单元测试 (context_injector.py, 覆盖 0% → 全绿)"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.market_review.context_injector import (
    build_market_context,
    detect_market_from_text,
    detect_market_from_ticker,
    try_inject_market_context,
)
from backend.services.market_review.models import (
    CapitalFlow,
    IndexSnapshot,
    MarketDailyReview,
    MarketStyle,
    MarketType,
    SentimentLevel,
)


# ── detect_market_from_ticker ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("00700.HK", MarketType.HK),
        ("HK.00700", MarketType.HK),
        ("600519.SH", MarketType.A_SHARE),
        ("SH.600519", MarketType.A_SHARE),
        ("SZ.300750", MarketType.A_SHARE),
        ("600519", MarketType.A_SHARE),  # 6 位纯数字
        ("300750", MarketType.A_SHARE),
        ("00700", MarketType.HK),  # 5 位纯数字
        ("AAPL", MarketType.US),  # 白名单
        ("AAPL.US", MarketType.US),
        ("US.AAPL", MarketType.US),
        ("MSFT", MarketType.US),
        ("XYZ", None),  # 未知标的不误判
        ("303", None),  # 3 位数字非 5/6
    ],
)
def test_detect_market_from_ticker(ticker, expected):
    assert detect_market_from_ticker(ticker) == expected


# ── detect_market_from_text ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("看看 00700.HK 今天怎么走", MarketType.HK),
        ("分析一下 600519.SH 的回调", MarketType.A_SHARE),
        ("300750 宁德时代还能拿吗", MarketType.A_SHARE),
        ("AAPL 盘后异动了吗", MarketType.US),
        ("TSLA 财报前要不要减仓", MarketType.US),
        ("今天天气不错，大盘如何", None),
    ],
)
def test_detect_market_from_text(text, expected):
    assert detect_market_from_text(text) == expected


# ── build_market_context ───────────────────────────────────────────────────
def _sample_review(date: str) -> MarketDailyReview:
    return MarketDailyReview(
        date=date,
        market=MarketType.A_SHARE,
        indices=[IndexSnapshot(name="上证指数", code="000001.SH", close=3200.0, change_pct=-1.23)],
        style=MarketStyle.DEFENSIVE,
        style_reasoning="避险情绪升温",
        capital_flow=CapitalFlow(conclusion="北向净流出 45 亿"),
        sentiment_score=28,
        sentiment_level=SentimentLevel.FEAR,
        risk_tags=["系统性回调", "板块轮动"],
        summary="权重拖累，题材退潮。",
    )


@pytest.mark.asyncio
async def test_build_market_context_formats_review():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new_callable=AsyncMock,
        return_value=[_sample_review("2026-07-24")],
    ):
        ctx = await build_market_context(MarketType.A_SHARE, days=3)
    assert ctx is not None
    assert "2026-07-24" in ctx
    assert "上证指数" in ctx
    assert "系统性回调" in ctx  # 风险标签透传
    assert "28/100" in ctx  # 情绪分


@pytest.mark.asyncio
async def test_build_market_context_none_when_empty():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new_callable=AsyncMock,
        return_value=[],
    ):
        assert await build_market_context(MarketType.HK, days=3) is None


# ── try_inject_market_context ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_try_inject_detects_and_builds():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new_callable=AsyncMock,
        return_value=[_sample_review("2026-07-24")],
    ):
        ctx = await try_inject_market_context("AAPL 今天为什么跌")
    assert ctx is not None
    assert "美股" in ctx


@pytest.mark.asyncio
async def test_try_inject_returns_none_without_ticker():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new_callable=AsyncMock,
    ) as mock_get:
        ctx = await try_inject_market_context("你好，请做个市场综述")
    assert ctx is None
    mock_get.assert_not_called()  # 无标的则不查复盘，省一次 IO
