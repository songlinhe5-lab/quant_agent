"""
回归测试：摘要压缩 / 记忆自愈不得破坏 tool_calls 配对。

线上 400 复现：
    Messages with role 'tool' must be a response to a preceding message with 'tool_calls'

根因 1：ContextCompressor._compress_with_summary 按条数硬切（保留最新 min_items_retained 条），
       切点可能落在 tool 消息上 → 保留窗口以孤立 tool 开头（配对的 assistant(tool_calls) 被裁）。
根因 2：_heal_memory 只修"孤立 assistant(tool_calls)"，不删"孤立 tool"（压缩/持久化遗留）。

修复：compact 切点对齐跳过 tool；_heal_memory 双向修复（剔除孤立 assistant + 丢弃孤立 tool）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_agent.compact import ContextCompressor
from hermes_agent.memory_ops import MemoryOperationsMixin


def _pair_messages(turns: int) -> list:
    """构造真实配对序列：user → assistant(tool_calls) → tool，循环 turns 轮。"""
    msgs = [{"role": "system", "content": "system"}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "get_quote", "arguments": '{"symbol": "AAPL"}'},
                    }
                ],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "name": "get_quote", "content": '{"price": 1}'})
    return msgs


def _assert_valid_pair_sequence(messages: list) -> None:
    """校验：每条 tool 消息前必须紧跟一条带对应 tool_calls 的 assistant（OpenAI 协议约束）。"""
    for idx, m in enumerate(messages):
        if m.get("role") == "tool":
            assert idx > 0, "tool 消息不能是首条"
            prev = messages[idx - 1]
            assert prev.get("role") == "assistant", f"tool 前必须是 assistant（index={idx}）"
            assert prev.get("tool_calls"), f"tool 前的 assistant 必须带 tool_calls（index={idx}）"
            ids = {tc["id"] for tc in prev["tool_calls"]}
            assert m.get("tool_call_id") in ids, f"tool_call_id 不匹配（index={idx}）"


class TestCompressCutKeepsToolPairs:
    @pytest.mark.asyncio
    async def test_cut_idx_on_tool_skips_forward(self):
        """切点恰好落在 tool 上时，压缩后保留窗口不得以孤立 tool 开头。"""
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="历史摘要"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        compressor = ContextCompressor(
            llm_client=client,
            event_log=MagicMock(),
            max_tokens_before_compress=100,
            min_items_retained=3,
        )
        # 7 轮配对 + 结尾一轮纯对话：len = 1 + 7*3 + 2 = 24
        # cut_idx = 24 - 3 = 21 → messages[21] 恰好是第 7 轮的 tool 消息（index 21 = 1 + 6*3 + 2）
        # 修复前：保留 [摘要, tool, user, assistant(纯文本)] → 孤立 tool → API 400
        # 修复后：cut_idx 推进到 22（user），孤立 tool 被裁进摘要区
        msgs = _pair_messages(6)
        msgs.append({"role": "user", "content": "q6"})
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_6", "type": "function", "function": {"name": "get_quote", "arguments": "{}"}}
                ],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": "call_6", "name": "get_quote", "content": '{"price": 2}'})
        msgs.append({"role": "user", "content": "q7"})
        msgs.append({"role": "assistant", "content": "最终答案"})
        assert msgs[21]["role"] == "tool", "测试前置条件：切点必须落在 tool 上"

        result = await compressor.maybe_compress(msgs, estimate_tokens_func=lambda: 50000)
        assert result is True
        _assert_valid_pair_sequence(msgs)

    @pytest.mark.asyncio
    async def test_compress_normal_sequence_keeps_pairs(self):
        """常规压缩不破坏 tool 配对。"""
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="历史摘要"))]
        client.chat.completions.create = AsyncMock(return_value=mock_response)

        compressor = ContextCompressor(
            llm_client=client,
            event_log=MagicMock(),
            max_tokens_before_compress=100,
            min_items_retained=5,
        )
        msgs = _pair_messages(8)
        await compressor.maybe_compress(msgs, estimate_tokens_func=lambda: 50000)
        _assert_valid_pair_sequence(msgs)


class _Host(MemoryOperationsMixin):
    """最小宿主：只提供 _heal_memory 依赖的成员，压缩路径 mock 掉。"""

    def __init__(self, messages: list):
        self.messages = messages
        self.console = MagicMock()
        self.event_log = MagicMock()
        self.client = AsyncMock()
        self.model = "test-model"
        self.session_id = "test-session"
        self.redis_client = AsyncMock()
        self._compress_memory = AsyncMock()


class TestHealMemoryDropsOrphanTool:
    @pytest.mark.asyncio
    async def test_orphaned_tool_message_dropped(self):
        """孤立 tool（前无 assistant(tool_calls)）被丢弃 —— 修复前会留存在上下文导致 400。"""
        host = _Host(
            [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "q1"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "r1"},
                {"role": "user", "content": "q2"},
                # 孤立 tool：其配对的 assistant(tool_calls) 已被压缩裁掉
                {"role": "tool", "tool_call_id": "ghost", "name": "x", "content": "orphan"},
            ]
        )
        await host._heal_memory()
        roles = [m["role"] for m in host.messages]
        assert "ghost" not in [m.get("tool_call_id") for m in host.messages]
        _assert_valid_pair_sequence(host.messages)

    @pytest.mark.asyncio
    async def test_valid_pairs_preserved(self):
        """正常配对序列在自愈后原样保留。"""
        msgs = _pair_messages(3)
        host = _Host(msgs)
        await host._heal_memory()
        assert len(host.messages) == len(msgs)
        _assert_valid_pair_sequence(host.messages)
