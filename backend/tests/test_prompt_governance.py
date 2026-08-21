"""
AGENT-16-NEXT · Prompt Governance 服务层测试
"""

import pytest

from hermes_agent.prompt_versioning import (
    FeedbackCollector,
    GoldenDatasetItem,
    PromptVersionManager,
)


def test_golden_dataset_item_evaluation():
    """测试 Golden Dataset 单项评估"""
    item = GoldenDatasetItem(
        name="test_case",
        input_context="用户询问 AAPL 股价走势",
        expected_output="AAPL 股价在过去 5 个交易日内上涨 3.2%",
        metrics=["relevance", "accuracy"],
    )

    actual_output = "AAPL 股价在过去 5 天内上涨约 3%，主要受财报驱动"

    scores = item.evaluate(actual_output)

    assert "relevance" in scores
    assert "accuracy" in scores
    assert 0 <= scores["relevance"] <= 1
    assert 0 <= scores["accuracy"] <= 1


def test_golden_dataset_runner_create_sample(tmp_path):
    """测试 Golden Dataset 样例创建"""
    dataset_path = tmp_path / "golden_dataset.jsonl"

    runner = GoldenDatasetRunner(str(dataset_path))

    # Should create sample file if not exists
    assert dataset_path.exists()
    assert len(runner.items) > 0


def test_feedback_collector_record_and_stats(tmp_path):
    """测试反馈收集器记录与统计"""
    storage_path = tmp_path / "feedback.jsonl"

    collector = FeedbackCollector(str(storage_path))

    # Record feedback
    collector.record("test_prompt", "1.0.0", "user_123", rating=1, comment="Great!")
    collector.record("test_prompt", "1.0.0", "user_456", rating=1, comment="Excellent")
    collector.record("test_prompt", "1.0.0", "user_789", rating=-1, comment="Needs improvement")

    collector._flush_to_disk()

    # Check stats
    stats = collector.get_stats("test_prompt", "1.0.0")

    assert stats["total_count"] == 3
    assert stats["up_ratio"] == 2 / 3  # 2 up, 1 down
    assert -1 < stats["avg_rating"] < 1


def test_prompt_version_manager_full_workflow(tmp_path):
    """测试版本管理完整工作流"""
    manager = PromptVersionManager(str(tmp_path / "prompts"))

    # 1. Create initial version
    v1 = manager.create_version("compact_summary", "Initial prompt", {"author": "alice"})
    assert v1.version == "1.0.0"

    # 2. Create second version
    v2 = manager.create_version("compact_summary", "Updated prompt", {"author": "bob"})
    assert v2.version == "1.1.0"

    # 3. Verify history
    template = manager.load_template("compact_summary")
    assert len(template.versions) == 2
    assert template.current_version == "1.1.0"

    # 4. Get specific version content
    content_v1 = manager.get_variant("compact_summary", "1.0.0")
    assert "Initial" in content_v1

    # 5. Rollback to v1
    result = manager.rollback("compact_summary", "1.0.0")
    assert result is True
    assert manager.templates["compact_summary"].current_version == "1.0.0"


def test_quality_evaluator_coherence_clarity():
    """测试质量评估器的连贯性与清晰度计算"""
    from hermes_agent.prompt_versioning import PromptQualityEvaluator

    evaluator = PromptQualityEvaluator()

    # High coherence prompt
    high_coherence = "首先分析数据，其次提取关键信息，最后生成总结报告。"
    score = evaluator._compute_coherence(high_coherence)
    assert score > 0.8

    # Low coherence prompt
    low_coherence = "这个那个什么然后呃不对应该不是这样"
    score = evaluator._compute_coherence(low_coherence)
    assert score < 0.7

    # Clear instructions
    clear_prompt = "请总结以下内容，不超过 500 字，提取核心事实与决策依据。"
    score = evaluator._compute_clarity(clear_prompt)
    assert score > 0.8

    # Ambiguous instructions
    ambiguous_prompt = "把这个弄一下，看看怎么样。"
    score = evaluator._compute_clarity(ambiguous_prompt)
    assert score < 0.7


@pytest.mark.asyncio
async def test_llm_driven_perplexity_fallback():
    """测试 LLM-driven perplexity 的 fallback 机制"""
    from hermes_agent.prompt_versioning import LLMDrivenEvaluator

    # Create evaluator without LLM client (should fallback to heuristic)
    evaluator = LLMDrivenEvaluator(llm_client=None)

    # Test with normal text
    text = "这是一个专业的量化交易记忆压缩助手提示词。"
    score = evaluator._heuristic_perplexity(text)

    assert 0 <= score <= 1
    assert isinstance(score, float)


def test_vector_store_embedding_and_search(tmp_path):
    """测试向量存储的嵌入和搜索功能"""
    from hermes_agent.prompt_versioning import PromptQualityMetrics, VectorStoreIntegrator

    vector_store = VectorStoreIntegrator(embedding_client=None)

    # Index a prompt
    metrics = PromptQualityMetrics(
        coherence=0.85,
        clarity=0.90,
        relevance=0.88,
        composite_score=0.87,
    )

    vector_store.index_prompt(
        name="compact_summary",
        version="1.0.0",
        content="你是一个专业的 AI 研究助手...",
        metrics=metrics,
        tags=["summary", "quantitative"],
    )

    # Search similar prompts
    results = vector_store.search_similar(
        query="AI research assistant prompt for summarization",
        top_k=5,
        min_score=0.0,  # Accept all for testing
    )

    assert len(results) == 1
    assert results[0]["key"] == "compact_summary:1.0.0"
    assert results[0]["metadata"]["quality_score"] == 0.87


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
