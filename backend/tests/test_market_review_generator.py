"""MRKT-02: 市场复盘生成引擎单元测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.market_review.generator import (
    _build_analysis_prompt,
    _parse_events,
    _parse_sentiment_level,
    _parse_style,
    _safe_float,
    generate_market_review,
)
from backend.services.market_review.models import (
    IndexSnapshot,
    MarketStyle,
    MarketType,
    SentimentLevel,
)


class TestHelpers:
    """辅助函数测试"""

    def test_safe_float_valid(self):
        assert _safe_float("3.14") == 3.14
        assert _safe_float(42) == 42.0

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None

    def test_parse_style(self):
        assert _parse_style("大盘价值") == MarketStyle.LARGE_VALUE
        assert _parse_style("当前偏防御避险风格") == MarketStyle.DEFENSIVE
        assert _parse_style("未知风格") == MarketStyle.BALANCED

    def test_parse_sentiment_level(self):
        assert _parse_sentiment_level("极度恐惧") == SentimentLevel.EXTREME_FEAR
        assert _parse_sentiment_level("贪婪") == SentimentLevel.GREED
        assert _parse_sentiment_level("unknown") == SentimentLevel.NEUTRAL

    def test_parse_events(self):
        raw = [
            {"title": "美联储加息", "category": "宏观", "impact": "利空", "affected_sectors": ["科技"]},
            {"title": "中美贸易缓和", "category": "地缘", "impact": "利好", "affected_sectors": []},
        ]
        events = _parse_events(raw)
        assert len(events) == 2
        assert events[0].title == "美联储加息"
        assert events[1].impact == "利好"

    def test_parse_events_max_5(self):
        raw = [{"title": f"event{i}"} for i in range(10)]
        events = _parse_events(raw)
        assert len(events) == 5


class TestBuildPrompt:
    """Prompt 构建测试"""

    def test_basic_prompt(self):
        indices = [
            IndexSnapshot(name="上证指数", code="SH.000001", close=3200.5, change_pct=-1.2),
        ]
        prompt = _build_analysis_prompt(
            market=MarketType.A_SHARE,
            date="2026-07-08",
            indices=indices,
            capital=None,
            news=[],
            sentiment=None,
        )
        assert "A股" in prompt
        assert "2026-07-08" in prompt
        assert "上证指数" in prompt
        assert "3200.5" in prompt

    def test_prompt_with_news(self):
        news = [{"headline": "Fed cuts rates", "summary": "The Fed cut rates by 25bp"}]
        prompt = _build_analysis_prompt(
            market=MarketType.US,
            date="2026-07-08",
            indices=[],
            capital=None,
            news=news,
            sentiment=None,
        )
        assert "Fed cuts rates" in prompt


class TestGenerateMarketReview:
    """主流程集成测试 (mock 外部依赖)"""

    @pytest.mark.asyncio
    async def test_generate_with_mocked_deps(self):
        """完整流程：数据采集 + LLM 分析 + 持久化"""
        mock_registry = MagicMock()

        # Mock 指数行情
        async def mock_execute(name, **kwargs):
            if name == "get_broker_market_data" and kwargs.get("action") == "QUOTE":
                return {
                    "status": "success",
                    "data": {"last_price": 3250.0, "change_pct": 0.85, "turnover": 4500e8},
                }
            if name == "get_broker_market_data" and kwargs.get("action") == "FUND_FLOW":
                return {
                    "status": "success",
                    "data": {"main_fund_net_inflow": 5.2e8},
                }
            if name == "get_macro_news":
                return {"status": "success", "data": [{"headline": "Test news", "summary": "test"}]}
            if name == "get_macro_sentiment_history":
                return {"status": "success", "data": {"summary": "VIX=18"}}
            return {"status": "error", "message": "unknown tool"}

        mock_registry.execute = mock_execute

        # Mock LLM
        from backend.services.market_review.generator import _LLMReviewAnalysis

        mock_analysis = _LLMReviewAnalysis(
            style="大盘成长",
            style_reasoning="科技权重股领涨",
            capital_conclusion="主力净流入科技板块",
            sentiment_score=65,
            sentiment_level="贪婪",
            event_impact_summary="美联储鸽派信号提振市场",
            summary="A股今日放量上涨，科技板块领涨。",
            outlook="短期看多，关注北向资金持续性。",
            risk_tags=["板块轮动"],
            key_events=[{"title": "美联储议息", "category": "宏观", "impact": "利好", "affected_sectors": ["科技"]}],
        )

        with (
            patch(
                "backend.services.market_review.generator.llm_service"
            ) as mock_llm,
            patch(
                "backend.services.market_review.generator.save_market_review",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            mock_llm.generate_pydantic = AsyncMock(return_value=mock_analysis)

            review = await generate_market_review(
                market=MarketType.A_SHARE,
                date="2026-07-08",
                tool_registry=mock_registry,
            )

        # 验证结果
        assert review.date == "2026-07-08"
        assert review.market == MarketType.A_SHARE
        assert len(review.indices) == 3  # A股有3个指数
        assert review.style == MarketStyle.LARGE_GROWTH
        assert review.sentiment_score == 65
        assert review.sentiment_level == SentimentLevel.GREED
        assert "科技" in review.summary
        assert review.risk_tags == ["板块轮动"]
        assert len(review.key_events) == 1

        # 验证持久化被调用
        mock_save.assert_called_once_with(review)

    @pytest.mark.asyncio
    async def test_generate_llm_failure_still_returns(self):
        """LLM 失败时仍返回基础复盘（无分析字段）"""
        mock_registry = MagicMock()

        async def mock_execute(name, **kwargs):
            if name == "get_broker_market_data" and kwargs.get("action") == "QUOTE":
                return {"status": "success", "data": {"last_price": 18000.0, "change_pct": -0.5}}
            return {"status": "error", "message": "unavailable"}

        mock_registry.execute = mock_execute

        with (
            patch(
                "backend.services.market_review.generator.llm_service"
            ) as mock_llm,
            patch(
                "backend.services.market_review.generator.save_market_review",
                new_callable=AsyncMock,
            ),
        ):
            mock_llm.generate_pydantic = AsyncMock(side_effect=Exception("LLM down"))

            review = await generate_market_review(
                market=MarketType.HK,
                date="2026-07-07",
                tool_registry=mock_registry,
            )

        assert review.market == MarketType.HK
        assert review.style is None  # LLM 失败，无风格
        assert review.summary == ""
        assert len(review.indices) == 2  # 港股2个指数
