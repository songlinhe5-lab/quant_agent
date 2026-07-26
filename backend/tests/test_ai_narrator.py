"""AI-01: 异动解说员单元测试

mock 数据源 ToolRegistry 与 LLMService，验证:
- 正常流程: 采集新闻/基本面 -> LLM 归纳一句话解说 -> 返回带溯源结果
- 无数据: 返回拒绝在真空里解说的兜底，且不调用 LLM
- LLM 失败: 降级为原始数据摘要
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai_narrator.models import NarrativeResult
from backend.services.ai_narrator.service import AiNarratorService


def _make_registry():
    registry = MagicMock()

    async def mock_execute(name, **kwargs):
        if name == "get_company_news":
            return {
                "status": "success",
                "data": [
                    {"time": "2026-07-26", "title": "营收miss预期", "summary": "Q2营收低于共识8%"},
                ],
            }
        if name == "get_fundamental_data":
            return {"status": "success", "data": {"pe": 28.4, "pb": 9.1, "roe": 0.23, "short_ratio": 1.2}}
        return {"status": "error", "message": "unknown"}

    registry.execute = mock_execute
    return registry


FAKE_SUMMARY = "据最新公司新闻，营收miss预期，空头可劲造。"


class TestAiNarrator:
    @pytest.mark.asyncio
    async def test_narrate_normal(self):
        registry = _make_registry()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=FAKE_SUMMARY)

        result = await AiNarratorService(llm=llm, tool_registry=registry).narrate(
            symbol="AAPL", change_pct=3.2, direction="up", threshold=2.0
        )
        assert isinstance(result, NarrativeResult)
        assert result.symbol == "AAPL"
        assert result.summary == FAKE_SUMMARY
        assert result.source  # 带来源
        assert 0.0 <= result.confidence <= 1.0
        assert result.triggered_by == "price_anomaly"

    @pytest.mark.asyncio
    async def test_narrate_no_data_fallback(self):
        registry = MagicMock()

        async def empty(name, **kwargs):
            return None

        registry.execute = empty
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="不应被使用")

        result = await AiNarratorService(llm=llm, tool_registry=registry).narrate(symbol="X", change_pct=5.0)
        assert "拒绝" in result.summary
        assert result.confidence == 0.0
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_narrate_llm_failure_degrade(self):
        registry = _make_registry()
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("LLM dead"))

        result = await AiNarratorService(llm=llm, tool_registry=registry).narrate(symbol="AAPL", change_pct=3.2)
        assert result.summary  # 降级仍有产出
        assert "原始数据" in result.source
        assert result.confidence < 0.7
