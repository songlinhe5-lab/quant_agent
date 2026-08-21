"""
AGENT-16-NEXT · Prompt 版本控制与质量检测单元测试
"""

import pytest

from hermes_agent.prompt_versioning import (
    ABTestOrchestrator,
    PromptQualityEvaluator,
    PromptVersionManager,
    parse_yaml_frontmatter,
)


def test_parse_yaml_frontmatter_basic():
    """测试基础 YAML frontmatter 解析"""
    text = """---
version: 1.0.0
created_at: 1234567890
---
这里是 Prompt 内容。"""

    metadata, content = parse_yaml_frontmatter(text)

    assert metadata["version"] == "1.0.0"
    assert metadata["created_at"] == 1234567890
    assert "这里是 Prompt 内容" in content


def test_parse_yaml_frontmatter_numeric_types():
    """测试数值类型转换"""
    text = """---
count: 10
ratio: 0.75
active: true
---
Content."""

    metadata, _ = parse_yaml_frontmatter(text)

    assert isinstance(metadata["count"], int)
    assert isinstance(metadata["ratio"], float)
    assert metadata["active"] is True


def test_prompt_version_manager_create_version(tmp_path):
    """测试创建新版本"""
    manager = PromptVersionManager(str(tmp_path))

    # Create first version
    v1 = manager.create_version("test_prompt", "Initial prompt", {"author": "Alice"})
    assert v1.version == "1.0.0"
    assert len(manager.templates["test_prompt"].versions) == 1

    # Create second version (minor bump)
    v2 = manager.create_version("test_prompt", "Updated prompt")
    assert v2.version == "1.1.0"
    assert len(manager.templates["test_prompt"].versions) == 2


def test_prompt_version_manager_rollback(tmp_path):
    """测试回滚到指定版本"""
    manager = PromptVersionManager(str(tmp_path))

    # Create two versions
    manager.create_version("test_prompt", "Version 1 content")
    manager.create_version("test_prompt", "Version 2 content")

    # Rollback to v1
    result = manager.rollback("test_prompt", "1.0.0")
    assert result is True
    assert manager.templates["test_prompt"].current_version == "1.0.0"


def test_prompt_quality_evaluator_coherence():
    """测试连贯性评估"""
    evaluator = PromptQualityEvaluator()

    # High coherence prompt
    high_coherence = "首先，我们需要分析数据。其次，提取关键信息。最后，生成总结。"
    score = evaluator._compute_coherence(high_coherence)
    assert score > 0.8

    # Low coherence prompt
    low_coherence = "这个那个什么然后呃不对应该不是这样"
    score = evaluator._compute_coherence(low_coherence)
    assert score < 0.7


def test_prompt_quality_evaluator_clarity():
    """测试清晰度评估"""
    evaluator = PromptQualityEvaluator()

    # Clear instructions
    clear_prompt = "请总结以下内容，不超过 500 字，提取核心事实与决策依据。"
    score = evaluator._compute_clarity(clear_prompt)
    assert score > 0.8

    # Ambiguous instructions
    ambiguous_prompt = "把这个弄一下，看看怎么样。"
    score = evaluator._compute_clarity(ambiguous_prompt)
    assert score < 0.7


@pytest.mark.asyncio
async def test_ab_test_orchestrator_select_variant():
    """测试 A/B 测试变体选择"""
    version_manager = PromptVersionManager("/tmp/test_prompts")
    orchestrator = ABTestOrchestrator(version_manager)

    # Create a test with two variants
    test = orchestrator.create_test(
        name="compact_prompt_test",
        variants=[("v1", "1.0.0"), ("v2", "1.1.0")],
        metric="token_reduction_rate",
        duration_hours=24,
    )

    # Select variant (should be deterministic based on hash)
    variant_id, version = orchestrator.select_variant("compact_prompt_test", "test context")
    assert variant_id in ["v1", "v2"]
    assert version in ["1.0.0", "1.1.0"]


def test_prompt_quality_evaluator_composite_score():
    """测试综合评分计算"""
    evaluator = PromptQualityEvaluator()

    metrics = evaluator.evaluate("请总结以下内容，不超过 500 字。")

    assert metrics.composite_score is not None
    assert 0 <= metrics.composite_score <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
