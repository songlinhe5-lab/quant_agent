"""
MRKT-05: context_injector 深度单测（补齐 build_market_context / try_inject 分支）
==============================================================================

detect_market_from_ticker / detect_market_from_text 已由 test_context_injector.py 覆盖，
本文件聚焦未覆盖的 build_market_context 与 try_inject_market_context。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.market_review.context_injector import (
    build_market_context,
    try_inject_market_context,
)
from backend.services.market_review.models import MarketType


def _make_review():
    review = MagicMock()
    review.date = "2024-01-01"
    idx = MagicMock()
    idx.name = "HSI"
    idx.change_pct = 1.5
    review.indices = [idx]
    review.style = MagicMock()
    review.style.value = "Bullish"
    review.style_reasoning = "momentum"
    cf = MagicMock()
    cf.conclusion = "northbound inflow"
    review.capital_flow = cf
    review.sentiment_score = 60
    sl = MagicMock()
    sl.value = "Neutral"
    review.sentiment_level = sl
    review.risk_tags = ["geo"]
    review.summary = "calm session"
    return review


@pytest.mark.asyncio
async def test_build_context_with_full_review():
    review = _make_review()
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new=AsyncMock(return_value=[review]),
    ):
        out = await build_market_context(MarketType.HK, days=3)
    assert out is not None
    assert "HSI" in out
    assert "Bullish" in out
    assert "northbound inflow" in out
    assert "geo" in out
    assert "calm session" in out


@pytest.mark.asyncio
async def test_build_context_no_reviews():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new=AsyncMock(return_value=[]),
    ):
        assert await build_market_context(MarketType.US) is None


@pytest.mark.asyncio
async def test_try_inject_detects_but_no_data():
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new=AsyncMock(return_value=[]),
    ):
        # 检测到港股标的但无复盘数据 → 返回 None
        assert await try_inject_market_context("看看 00700.HK 怎么走") is None


@pytest.mark.asyncio
async def test_try_inject_no_ticker():
    assert await try_inject_market_context("今天天气真不错") is None


@pytest.mark.asyncio
async def test_try_inject_builds_context():
    review = _make_review()
    with patch(
        "backend.services.market_review.context_injector.get_recent_reviews",
        new=AsyncMock(return_value=[review]),
    ):
        out = await try_inject_market_context("帮我分析一下 AAPL 的走势")
    assert out is not None
    assert "HSI" in out
