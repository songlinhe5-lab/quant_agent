"""BRD-01: 早报生成引擎单元测试

mock 数据源 ToolRegistry 与 LLMService，验证:
- 正常流程: 编排 4 工具 -> LLM 组装 Markdown -> 持久化
- LLM 失败: 触发数据兜底骨架，且内存存储可读
- 模块级便捷封装 generate_morning_briefing 可用
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.morning_briefing.generator import (
    MorningBriefingGenerator,
    generate_morning_briefing,
)
from backend.services.morning_briefing.models import BriefingResult
from backend.services.morning_briefing.storage import get_briefing, get_latest_briefing

FAKE_MARKDOWN = (
    "# 🌤️ Quant Agent 盘前推演早报\n\n"
    "## 📅 全球宏观高危雷达 (未来 7 天)\n"
    "- 2026-07-28 美国 美联储利率决议 (前值:5.5% | 预期:5.25%)\n\n"
    "## 📈 核心标的监控\n"
    "- **SPY**: 最新价: 540.2 | 涨跌幅: 0.8% | 成交量: 50000000\n\n"
    "## 🧠 主脑综合研判\n"
    "| 多头因素 ✅ | 空头因素 ❌ |\n|---|---|\n| 流动性宽松 | 估值偏高 |\n\n"
    "**看涨概率 (Bullish Probability):** 62%\n\n主脑研判：短线偏多，设好止损。"
)


def _make_registry():
    registry = MagicMock()

    async def mock_execute(name, **kwargs):
        if name == "get_macro_calendar":
            return {
                "status": "success",
                "data": {
                    "events": [
                        {
                            "time": "2026-07-28 02:00",
                            "country": "美国",
                            "title": "美联储利率决议",
                            "previous": "5.5%",
                            "forecast": "5.25%",
                        }
                    ]
                },
            }
        if name == "get_broker_market_data" and kwargs.get("action") == "QUOTE":
            return {
                "status": "success",
                "data": [
                    {"symbol": "SPY", "last_price": 540.2, "change_pct": 0.8, "volume": 50000000}
                ],
            }
        if name == "get_macro_news":
            return {
                "status": "success",
                "data": [{"time": "2026-07-26", "title": "通胀超预期回落", "summary": "核心PCE降温"}],
            }
        if name == "get_macro_sentiment_history":
            return {"status": "success", "data": {"latest": {"vix": 14.2, "pcr": 0.9, "credit_spread": 3.1}}}
        return {"status": "error", "message": "unknown"}

    registry.execute = mock_execute
    return registry


class TestGenerateMorningBriefing:
    @pytest.mark.asyncio
    async def test_generate_with_mocked_deps(self):
        registry = _make_registry()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=FAKE_MARKDOWN)

        with patch(
            "backend.services.morning_briefing.generator.save_briefing",
            new_callable=AsyncMock,
        ) as mock_save:
            result = await MorningBriefingGenerator(llm=llm, tool_registry=registry).generate(
                market="全球", target_date="2026-07-26"
            )

        assert isinstance(result, BriefingResult)
        assert result.id
        assert result.date == "2026-07-26"
        assert result.market == "全球"
        assert "看涨概率" in result.markdown
        assert result.source_tools == [
            "get_macro_calendar",
            "get_broker_market_data",
            "get_macro_news",
            "get_macro_sentiment_history",
        ]
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_llm_failure_fallback(self):
        registry = _make_registry()
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("LLM dead"))

        # 不 patch save，走内存兜底存储
        result = await MorningBriefingGenerator(llm=llm, tool_registry=registry).generate(market="全球")
        assert result.markdown
        assert "降级" in result.markdown  # 触发兜底骨架
        fetched = await get_briefing(result.id)
        assert fetched is not None and fetched.id == result.id
        latest = await get_latest_briefing("全球")
        assert latest is not None and latest.id == result.id

    @pytest.mark.asyncio
    async def test_module_level_helper(self):
        registry = _make_registry()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=FAKE_MARKDOWN)

        with patch(
            "backend.services.morning_briefing.generator.ToolRegistry"
        ) as mock_cls, patch(
            "backend.services.morning_briefing.generator.LLMService"
        ) as mock_llm_cls, patch(
            "backend.services.morning_briefing.generator.save_briefing",
            new_callable=AsyncMock,
        ):
            mock_cls.return_value = registry
            mock_llm_cls.return_value = llm
            result = await generate_morning_briefing(market="全球")

        assert isinstance(result, BriefingResult)
        assert "看涨概率" in result.markdown
