"""
AGENT-16 · 摘要压缩单元测试

验证 ContextCompressor 的摘要与 fallback 机制。
"""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hermes_agent.compact import CompactMetadata, ContextCompactionItem, ContextCompressor


@pytest.mark.asyncio
async def test_compact_metadata_serialization():
    """测试元数据序列化"""
    metadata = CompactMetadata(
        original_range_start=1,
        original_range_end=10,
        token_before=5000,
        token_after=500,
        compaction_method="llm_summary",
    )

    data = metadata.to_dict()
    assert data["original_range"]["start"] == 1
    assert data["original_range"]["end"] == 10
    assert data["token_before"] == 5000
    assert data["token_after"] == 500
    assert data["compaction_method"] == "llm_summary"


@pytest.mark.asyncio
async def test_context_compaction_item_to_message():
    """测试摘要项转换为 message"""
    metadata = CompactMetadata(
        original_range_start=1,
        original_range_end=5,
        token_before=2000,
        token_after=300,
        compaction_method="llm_summary",
    )

    item = ContextCompactionItem(summary="Test summary content", metadata=metadata, original_items_count=5)
    msg = item.to_message()

    assert msg["role"] == "assistant"
    assert msg["content"] is not None
    assert "[COMPACTED 5 items]" in msg["content"]
    assert "Test summary content" in msg["content"]


@pytest.mark.asyncio
async def test_compressor_skip_when_under_budget():
    """测试预算内跳过压缩"""
    client = AsyncMock()
    event_log = MagicMock()

    compressor = ContextCompressor(llm_client=client, event_log=event_log, max_tokens_before_compress=100000)

    messages = [{"role": "system", "content": "test"}] * 5

    def estimate_tokens():
        return 5000  # 远低于阈值

    result = await compressor.maybe_compress(messages, estimate_tokens_func=estimate_tokens)
    assert result is False  # 未触发压缩
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_compressor_fallback_on_empty_summary():
    """测试空摘要时 fallback"""
    client = AsyncMock()
    # 模拟模型返回空内容
    mock_response = Mock()
    mock_response.choices = [Mock(message=Mock(content=""))]
    client.chat.completions.create = AsyncMock(return_value=mock_response)

    event_log = MagicMock()
    compressor = ContextCompressor(llm_client=client, event_log=event_log, max_tokens_before_compress=100)

    messages = [{"role": "system", "content": "test"}] * 20

    def estimate_tokens():
        return 5000  # 超过阈值

    result = await compressor.maybe_compress(messages, estimate_tokens_func=estimate_tokens)
    assert result is True  # 触发了（但 fallback 了）


@pytest.mark.asyncio
async def test_compaction_prompt_building():
    """测试压缩 Prompt 构建"""
    client = AsyncMock()
    event_log = MagicMock()

    compressor = ContextCompressor(llm_client=client, event_log=event_log)

    items = [
        {"role": "user", "content": "查询 AAPL 价格"},
        {"role": "assistant", "content": "AAPL 当前价格为 150 美元"},
        {"role": "tool", "content": '{"status": "success", "data": {...}}'},
    ]

    prompt = compressor._build_compaction_prompt(items)

    # 检查 system prompt 存在
    assert len(prompt) >= 1
    assert prompt[0]["role"] == "system"
    assert "以下是需要压缩的历史对话片段" in prompt[0]["content"]

    # Tool 消息应被简化
    tool_items = [p for p in prompt if p.get("role") == "tool"]
    assert len(tool_items) > 0
    assert "executed" in tool_items[0]["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
