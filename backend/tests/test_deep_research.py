"""
阶段 4 · Multi-Agent 深度研报流水线测试

mock LLM + tools, 测试 pipeline 流程
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.deep_research import (
    ChartDeliveryAgent,
    ClusterDiscoveryAgent,
    DataDeepDiveAgent,
    DeepResearchPipeline,
    ResearchFinding,
    ResearchReport,
    deep_research_pipeline,
)

# ===== ClusterDiscoveryAgent =====


@pytest.mark.asyncio
async def test_cluster_discovery_success():
    """测试聚类发现 Agent 成功路径"""
    mock_response = MagicMock()
    mock_response.findings = [
        {"theme": "AI 芯片", "summary": "NVIDIA 营收创新高", "relevance": 0.9},
        {"theme": "供应链", "summary": "台积电产能紧张", "relevance": 0.7},
    ]

    with patch("backend.services.deep_research.llm_service") as mock_llm:
        mock_llm.generate_pydantic = AsyncMock(return_value=mock_response)
        agent = ClusterDiscoveryAgent()
        findings = await agent.run("AI 半导体趋势", ["NVDA", "TSM"])

    assert len(findings) == 2
    assert findings[0].theme == "AI 芯片"
    assert findings[0].relevance == 0.9
    assert findings[1].theme == "供应链"


@pytest.mark.asyncio
async def test_cluster_discovery_llm_failure():
    """测试聚类发现 Agent LLM 失败降级"""
    with patch("backend.services.deep_research.llm_service") as mock_llm:
        mock_llm.generate_pydantic = AsyncMock(side_effect=Exception("LLM timeout"))
        agent = ClusterDiscoveryAgent()
        findings = await agent.run("测试主题", ["AAPL"])

    assert len(findings) == 1
    assert "异常" in findings[0].theme or "失败" in findings[0].summary


# ===== DataDeepDiveAgent =====


@pytest.mark.asyncio
async def test_data_deepdive_success():
    """测试数据深挖 Agent 成功路径"""
    findings = [
        ResearchFinding(theme="AI 芯片", summary="NVIDIA 营收创新高", relevance=0.9),
    ]

    mock_choice = MagicMock()
    mock_choice.message.content = "深度分析内容：AI 芯片需求持续增长..."

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("backend.services.deep_research.llm_service") as mock_llm:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_llm.get_client.return_value = mock_client
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.router = MagicMock()

        agent = DataDeepDiveAgent()
        result = await agent.run("AI 半导体", findings)

    assert "AI 芯片" in result or "深度分析" in result


@pytest.mark.asyncio
async def test_data_deepdive_llm_failure():
    """测试数据深挖 Agent LLM 失败降级"""
    findings = [ResearchFinding(theme="测试", summary="测试")]

    with patch("backend.services.deep_research.llm_service") as mock_llm:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
        mock_llm.get_client.return_value = mock_client
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.router = MagicMock()

        agent = DataDeepDiveAgent()
        result = await agent.run("测试", findings)

    assert "不可用" in result or "暂时" in result


# ===== ChartDeliveryAgent =====


@pytest.mark.asyncio
async def test_chart_delivery_assembles_report():
    """测试图表交付 Agent 组装研报"""
    findings = [
        ResearchFinding(theme="主题A", summary="摘要A", relevance=0.8),
        ResearchFinding(theme="主题B", summary="摘要B", relevance=0.6),
    ]

    agent = ChartDeliveryAgent()
    report = await agent.run("测试主题", ["AAPL", "NVDA"], findings, "深度分析内容")

    assert isinstance(report, ResearchReport)
    assert report.topic == "测试主题"
    assert report.symbols == ["AAPL", "NVDA"]
    assert len(report.findings) == 2
    assert "测试主题" in report.markdown_content
    assert "深度分析" in report.markdown_content
    assert "风险提示" in report.markdown_content


@pytest.mark.asyncio
async def test_chart_delivery_empty_findings():
    """测试空发现列表时研报生成"""
    agent = ChartDeliveryAgent()
    report = await agent.run("空主题", ["AAPL"], [], "分析内容")

    assert report.executive_summary == ""
    assert "空主题" in report.markdown_content


# ===== DeepResearchPipeline =====


@pytest.mark.asyncio
async def test_pipeline_full_flow():
    """测试完整三段流水线"""
    # Mock Stage 1
    mock_findings = [
        ResearchFinding(theme="趋势", summary="上涨趋势", relevance=0.8),
    ]

    with (
        patch.object(ClusterDiscoveryAgent, "run", new_callable=AsyncMock, return_value=mock_findings),
        patch.object(DataDeepDiveAgent, "run", new_callable=AsyncMock, return_value="深度分析文本"),
        patch.object(ChartDeliveryAgent, "run", new_callable=AsyncMock) as mock_delivery,
    ):
        mock_delivery.return_value = ResearchReport(
            topic="测试",
            symbols=["AAPL"],
            findings=mock_findings,
            deep_analysis="深度分析文本",
            markdown_content="# 测试",
        )

        pipeline = DeepResearchPipeline()
        report = await pipeline.run("测试", ["AAPL"])

    assert report.topic == "测试"
    assert len(report.findings) == 1
    mock_delivery.assert_called_once()


def test_global_singleton():
    """测试全局单例存在"""
    assert deep_research_pipeline is not None
    assert isinstance(deep_research_pipeline, DeepResearchPipeline)
