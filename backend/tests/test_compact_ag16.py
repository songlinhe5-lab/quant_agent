"""
AGENT-16 · 摘要压缩集成测试

验收标准：
1. 压缩后窗口含摘要项且旧消息不可见
2. 摘要模型注入故障时自动降级（滑动窗口兜底）且测试通过
3. 事件日志有 memory/compact 事件与摘要引用
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ── 辅助 Mixin 实例构造 ────────────────────────────────────────────


def _make_mixin(messages, client=None, event_log=None, model="deepseek-chat", session_id="test"):
    """构造一个带 messages / client / event_log 的 MemoryOperationsMixin 实例"""
    from rich.console import Console

    from hermes_agent.memory_ops import MemoryOperationsMixin

    class _TestAgent(MemoryOperationsMixin):
        pass

    agent = _TestAgent()
    agent.messages = messages
    agent.client = client or AsyncMock()
    agent.event_log = event_log or MagicMock()
    agent.model = model
    agent.session_id = session_id
    agent.console = Console(quiet=True)
    agent.memory_key = f"test:{session_id}"
    agent.redis_client = AsyncMock()
    agent.system_prompt = "You are a test agent."
    return agent


def _make_messages(count=30):
    """构造测试消息列表"""
    msgs = [{"role": "system", "content": "system prompt"}]
    for i in range(count - 1):
        if i % 3 == 0:
            msgs.append({"role": "user", "content": f"用户问题 {i}"})
        elif i % 3 == 1:
            msgs.append({"role": "assistant", "content": f"助手回答 {i}"})
        else:
            msgs.append({"role": "tool", "content": f'{{"result": "data_{i}"}}', "name": f"tool_{i}"})
    return msgs


# ── 集成测试：_compress_memory 完整流程 ─────────────────────────────


class TestCompressMemoryIntegration:
    @pytest.mark.asyncio
    async def test_summary_replaces_destructive_truncation(self):
        """验收标准1：摘要压缩取代破坏性截断，窗口含摘要项"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="历史摘要：讨论了AAPL和TSLA的投资策略"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        event_log = MagicMock()
        messages = _make_messages(30)
        original_user_msgs = [m["content"] for m in messages if m["role"] == "user"]

        agent = _make_mixin(messages, client=client, event_log=event_log)

        # 触发压缩（token 估算超过阈值）
        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10)

        # 窗口中有摘要项
        compacted = [m for m in agent.messages if m.get("content") and "[COMPACTED" in str(m["content"])]
        assert len(compacted) >= 1, "压缩后窗口中应包含摘要项"

        # 旧消息不可见（大部分 user 消息被摘要取代）
        remaining_user = [m["content"] for m in agent.messages if m["role"] == "user"]
        invisible_count = sum(1 for old in original_user_msgs if old not in remaining_user)
        assert invisible_count > 0, "旧消息应被摘要取代而不可见"

    @pytest.mark.asyncio
    async def test_fallback_to_sliding_window_on_model_failure(self):
        """验收标准2：摘要模型故障时自动降级为滑动窗口"""
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("模型服务不可用"))

        event_log = MagicMock()
        messages = _make_messages(30)
        agent = _make_mixin(messages, client=client, event_log=event_log)

        # 触发压缩（token 估算超过激进模式阈值 60000，eff_max_messages=20）
        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10)

        # 滑动窗口兜底：消息数应减少（激进模式下 eff_max=20）
        assert len(agent.messages) <= 25, "滑动窗口兜底后消息数应减少"
        # system 消息保留
        assert agent.messages[0]["role"] == "system"
        # 没有摘要项（因为摘要失败了）
        compacted = [m for m in agent.messages if m.get("content") and "[COMPACTED" in str(m["content"])]
        assert len(compacted) == 0, "摘要失败时不应有摘要项"

    @pytest.mark.asyncio
    async def test_event_log_has_compact_event(self):
        """验收标准3：事件日志有 memory/compact 事件"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="压缩摘要内容"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        event_log = MagicMock()
        messages = _make_messages(30)
        agent = _make_mixin(messages, client=client, event_log=event_log)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10)

        # 事件日志被调用
        event_log.record_memory_op.assert_called()
        # 至少有一次 compact 事件
        compact_calls = [call for call in event_log.record_memory_op.call_args_list if call[0][0] == "compact"]
        assert len(compact_calls) >= 1, "事件日志应记录 memory/compact 事件"
        # 摘要引用在 detail 中
        detail = compact_calls[0][0][1]
        assert "llm_summary" in detail

    @pytest.mark.asyncio
    async def test_no_compress_when_under_budget(self):
        """预算内不触发压缩"""
        client = AsyncMock()
        messages = _make_messages(5)
        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 100):
            await agent._compress_memory()

        # 消息数不变
        assert len(agent.messages) == 5
        # LLM 未被调用
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_too_few_messages(self):
        """消息数过少时跳过压缩"""
        client = AsyncMock()
        messages = _make_messages(3)
        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory()

        # 消息数不变（太少不压缩）
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_truncation_before_summary(self):
        """摘要前先截断巨型 Tool 返回值"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="摘要"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "content": "x" * 5000, "name": "big_tool"},  # 巨型 tool 返回
        ] + [{"role": "user", "content": f"q{i}"} for i in range(30)]

        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10, max_tool_len=100)

        # 巨型 tool 内容被截断（如果还在窗口中的话）
        for m in agent.messages:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                # 截断后的内容应远小于 5000
                assert len(m["content"]) < 5000


# ── 集成测试：_heal_memory + _compress_memory 联动 ──────────────────


class TestHealAndCompressIntegration:
    @pytest.mark.asyncio
    async def test_heal_triggers_compression(self):
        """自愈后触发压缩"""
        client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="摘要"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        # 构造带孤立 tool_calls 的消息
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "call", "tool_calls": [{"id": "tc1", "function": {"name": "test"}}]},
            # 缺失 tool 响应 → 需要自愈
        ] + [{"role": "user", "content": f"q{i}"} for i in range(25)]

        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._heal_memory()

        # 孤立 tool_calls 被修复
        has_orphan = False
        for i, m in enumerate(agent.messages):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                next_m = agent.messages[i + 1] if i + 1 < len(agent.messages) else None
                if next_m and next_m.get("role") != "tool":
                    has_orphan = True
        assert not has_orphan, "自愈后不应存在孤立 tool_calls"


# ── 降级链路测试 ────────────────────────────────────────────────────


class TestDegradationChain:
    @pytest.mark.asyncio
    async def test_llm_timeout_fallback(self):
        """LLM 超时 → 滑动窗口兜底"""
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError("LLM 超时"))

        messages = _make_messages(30)
        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10)

        # 滑动窗口兜底（激进模式 eff_max=20）
        assert len(agent.messages) <= 25

    @pytest.mark.asyncio
    async def test_llm_connection_error_fallback(self):
        """连接错误 → 滑动窗口兜底"""
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=ConnectionError("网络断开"))

        messages = _make_messages(30)
        agent = _make_mixin(messages, client=client)

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            await agent._compress_memory(max_messages=10)

        assert len(agent.messages) <= 25

    @pytest.mark.asyncio
    async def test_import_error_fallback(self):
        """compact 模块导入失败 → 滑动窗口兜底"""
        messages = _make_messages(30)
        agent = _make_mixin(messages, client=AsyncMock())

        with patch.object(agent, "_estimate_tokens", side_effect=lambda: 200000):
            with patch.dict("sys.modules", {"hermes_agent.compact": None}):
                await agent._compress_memory(max_messages=10)

        # 即使导入失败，滑动窗口仍然工作（激进模式 eff_max=20）
        assert len(agent.messages) <= 25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
