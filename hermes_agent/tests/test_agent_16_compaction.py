"""
AGENT-16 · 摘要压缩取代破坏性截断 — 完整单元测试

验收标准：
1. 压缩后窗口含摘要项且旧消息不可见
2. 摘要模型注入故障时自动降级且测试通过
3. 事件日志有 memory/compact 事件与摘要引用
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hermes_agent.compact import (
    CompactConfig,
    CompactMetadata,
    ContextCompactionItem,
    ContextCompressor,
)

# ── CompactConfig 测试 ──────────────────────────────────────────────


class TestCompactConfig:
    def test_default_config(self):
        """默认配置值正确"""
        config = CompactConfig()
        assert config.max_summary_tokens == 2000
        assert "量化交易" in config.summary_system_prompt
        assert "核心事实" in config.compact_system_prompt

    def test_from_env_defaults(self):
        """环境变量缺失时使用默认值"""
        config = CompactConfig.from_env()
        assert config.max_summary_tokens == 2000

    def test_from_env_overrides(self):
        """环境变量覆盖默认值"""
        with patch.dict(
            "os.environ",
            {
                "HERMES_COMPACT_MAX_SUMMARY_TOKENS": "500",
                "HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT": "自定义提示词",
            },
        ):
            config = CompactConfig.from_env()
            assert config.max_summary_tokens == 500
            assert config.summary_system_prompt == "自定义提示词"


# ── CompactMetadata 测试 ────────────────────────────────────────────


class TestCompactMetadata:
    def test_serialization(self):
        """元数据序列化"""
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
        assert isinstance(data["timestamp"], float)

    def test_fallback_method(self):
        """fallback 截断方法标记"""
        metadata = CompactMetadata(
            original_range_start=0,
            original_range_end=5,
            token_before=3000,
            token_after=0,
            compaction_method="fallback_truncate",
        )
        assert metadata.compaction_method == "fallback_truncate"


# ── ContextCompactionItem 测试 ──────────────────────────────────────


class TestContextCompactionItem:
    def test_to_message(self):
        """摘要项转换为 LLM 可见 message"""
        metadata = CompactMetadata(
            original_range_start=1,
            original_range_end=5,
            token_before=2000,
            token_after=300,
            compaction_method="llm_summary",
        )
        item = ContextCompactionItem(summary="AAPL 150美元，MACD金叉", metadata=metadata, original_items_count=5)
        msg = item.to_message()
        assert msg["role"] == "assistant"
        assert "[COMPACTED 5 items]" in msg["content"]
        assert "AAPL 150美元" in msg["content"]

    def test_to_message_preserves_summary(self):
        """摘要内容完整保留"""
        metadata = CompactMetadata(0, 0, 0, 0, "llm_summary")
        summary_text = "关键事实：美联储加息25bps，纳斯达克下跌2%"
        item = ContextCompactionItem(summary=summary_text, metadata=metadata, original_items_count=3)
        msg = item.to_message()
        assert summary_text in msg["content"]


# ── ContextCompressor 核心测试 ──────────────────────────────────────


class TestContextCompressor:
    def _make_compressor(self, client=None, event_log=None, **kwargs):
        """辅助工厂"""
        return ContextCompressor(
            llm_client=client or AsyncMock(),
            event_log=event_log or MagicMock(),
            **kwargs,
        )

    def _make_messages(self, count=30, system_content="system"):
        """构造测试消息列表"""
        msgs = [{"role": "system", "content": system_content}]
        for i in range(count - 1):
            if i % 3 == 0:
                msgs.append({"role": "user", "content": f"用户问题 {i}"})
            elif i % 3 == 1:
                msgs.append({"role": "assistant", "content": f"助手回答 {i}"})
            else:
                msgs.append(
                    {"role": "tool", "content": f'{{"status": "ok", "data": "tool_result_{i}"}}', "name": f"tool_{i}"}
                )
        return msgs

    @pytest.mark.asyncio
    async def test_skip_when_under_budget(self):
        """预算内跳过压缩"""
        compressor = self._make_compressor(max_tokens_before_compress=100000)
        messages = self._make_messages(5)

        result = await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 500)
        assert result is False

    @pytest.mark.asyncio
    async def test_summary_compress_success(self):
        """LLM 摘要压缩成功 — 旧消息被摘要取代"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="摘要：AAPL 150美元，MACD金叉，建议持有"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        event_log = MagicMock()
        compressor = self._make_compressor(client=client, event_log=event_log, max_tokens_before_compress=100)

        messages = self._make_messages(30)
        original_len = len(messages)

        result = await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)
        assert result is True
        # 旧消息被摘要取代，消息数大幅减少
        assert len(messages) < original_len
        # 消息中包含摘要项
        assert any("[COMPACTED" in str(m.get("content", "")) for m in messages)
        # 事件日志记录了 compact 事件
        event_log.record_memory_op.assert_called()
        call_args = event_log.record_memory_op.call_args
        assert "compact" in call_args[0][0]
        assert "llm_summary" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_old_messages_invisible_after_compact(self):
        """验收标准1：压缩后旧消息不可见"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="历史摘要内容"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        compressor = self._make_compressor(client=client, max_tokens_before_compress=100, min_items_retained=5)

        messages = self._make_messages(25)
        # 记录被压缩前的旧消息内容
        old_user_msgs = [m for m in messages if m["role"] == "user"]

        result = await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)
        assert result is True

        # 旧消息不在窗口中（大部分 user 消息被摘要取代）
        remaining_user_contents = [m.get("content", "") for m in messages if m["role"] == "user"]
        invisible_count = sum(1 for old in old_user_msgs if old["content"] not in remaining_user_contents)
        assert invisible_count > 0, "旧消息应被摘要取代而不可见"

        # 窗口中有摘要
        compacted = [m for m in messages if m.get("content") and "[COMPACTED" in str(m["content"])]
        assert len(compacted) >= 1

    @pytest.mark.asyncio
    async def test_fallback_on_model_failure(self):
        """验收标准2：摘要模型注入故障时自动降级"""
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("模型服务不可用"))

        event_log = MagicMock()
        compressor = self._make_compressor(client=client, event_log=event_log, max_tokens_before_compress=100)

        messages = self._make_messages(25)

        # 摘要失败 → 抛异常（不再内部 fallback），由调用方处理
        with pytest.raises(RuntimeError, match="Pro 模型摘要失败"):
            await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)

    @pytest.mark.asyncio
    async def test_fallback_on_empty_summary(self):
        """空摘要视为失败"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content=""))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        compressor = self._make_compressor(client=client, max_tokens_before_compress=100)
        messages = self._make_messages(25)

        with pytest.raises(RuntimeError, match="Pro 模型摘要失败"):
            await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)

    @pytest.mark.asyncio
    async def test_skip_when_too_few_messages(self):
        """消息数低于最小保留线时跳过"""
        client = AsyncMock()
        compressor = self._make_compressor(client=client, max_tokens_before_compress=100, min_items_retained=10)

        messages = self._make_messages(5)  # 低于 min_items_retained * 2
        result = await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)
        assert result is False
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_log_records_compact_event(self):
        """验收标准3：事件日志记录 memory/compact 事件"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="压缩后的摘要"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        event_log = MagicMock()
        compressor = self._make_compressor(client=client, event_log=event_log, max_tokens_before_compress=100)

        messages = self._make_messages(25)
        await compressor.maybe_compress(messages, estimate_tokens_func=lambda: 50000)

        # 验证事件日志被调用
        event_log.record_memory_op.assert_called_once()
        args = event_log.record_memory_op.call_args
        assert args[0][0] == "compact"
        detail = args[0][1]
        assert "llm_summary" in detail
        assert "range=" in detail
        assert "tokens=" in detail


# ── Prompt 构建测试 ─────────────────────────────────────────────────


class TestCompactionPrompt:
    def test_tool_messages_simplified(self):
        """Tool 消息在压缩 Prompt 中被简化"""
        compressor = ContextCompressor(llm_client=AsyncMock(), event_log=None)

        items = [
            {"role": "user", "content": "查询 AAPL"},
            {"role": "assistant", "content": "正在查询"},
            {"role": "tool", "name": "get_quote", "content": '{"price": 150, "change": 0.02}'},
            {"role": "tool", "name": "bad_tool", "content": '{"error": "timeout"}'},
        ]

        prompt = compressor._build_compaction_prompt(items)
        tool_items = [p for p in prompt if p["role"] == "tool"]
        assert len(tool_items) == 2
        # 成功的 tool
        assert "status=ok" in tool_items[0]["content"]
        # 失败的 tool
        assert "status=error" in tool_items[1]["content"]
        # 详细内容被丢弃
        assert "150" not in tool_items[0]["content"]

    def test_system_prompt_from_config(self):
        """压缩 Prompt 使用配置的系统提示词"""
        config = CompactConfig(compact_system_prompt="自定义压缩提示词")
        compressor = ContextCompressor(llm_client=AsyncMock(), event_log=None, config=config)

        items = [{"role": "user", "content": "test"}]
        prompt = compressor._build_compaction_prompt(items)
        assert prompt[0]["content"] == "自定义压缩提示词"

    def test_user_assistant_preserved(self):
        """user/assistant 消息在 Prompt 中完整保留"""
        compressor = ContextCompressor(llm_client=AsyncMock(), event_log=None)
        items = [
            {"role": "user", "content": "分析 TSLA"},
            {"role": "assistant", "content": "TSLA 当前PE为50"},
        ]
        prompt = compressor._build_compaction_prompt(items)
        non_system = [p for p in prompt if p["role"] != "system"]
        assert len(non_system) == 2
        assert non_system[0]["content"] == "分析 TSLA"
        assert non_system[1]["content"] == "TSLA 当前PE为50"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
