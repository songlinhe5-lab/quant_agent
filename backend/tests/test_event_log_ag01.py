"""
AGENT-01 · 会话事件日志（append-only）+ 投影 + 不变量测试

验收（TODO-AGENT-ARCH.md）：
- 任一历史会话可重放出当时模型看到的完整上下文
- 违反「模型可见即已记录」不变量即测试失败
- 压缩只影响投影，不删事件
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.test.com")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── append-only 事件日志 ─────────────────────────────────────────────


class TestSessionEventLog:
    def test_append_seq_monotonic(self):
        """事件 seq 单调递增，追加后不可变语义"""
        from hermes_agent.event_log import SessionEventLog

        log = SessionEventLog(session_id="s1")
        e1 = log.record_user_message("查一下 AAPL")
        e2 = log.record_tool_call("call_1", "get_broker_market_data", '{"action":"QUOTE"}')
        assert e1.seq == 1 and e2.seq == 2
        assert len(log) == 2

    def test_closed_event_types(self):
        """事件类型闭集：未知类型标记 _invalid_type 但仍写入（宽容审计）"""
        from hermes_agent.event_log import EVENT_TYPES, SessionEventLog

        assert "user/message" in EVENT_TYPES
        assert "tool/call" in EVENT_TYPES
        assert "approval/decided" in EVENT_TYPES  # AGENT-07 预留

        log = SessionEventLog()
        evt = log.append("nonexistent/type", {"x": 1})
        assert evt.payload.get("_invalid_type") is True

    def test_event_to_dict_serializable(self):
        from hermes_agent.event_log import SessionEventLog

        log = SessionEventLog()
        evt = log.record_assistant_message("AAPL 看涨")
        d = evt.to_dict()
        assert d["type"] == "assistant/message"
        assert d["payload"]["content"] == "AAPL 看涨"
        assert d["seq"] == 1
        assert d["ts"] > 0

    def test_reset_clears_log(self):
        """用户 /clear 时事件日志可重置"""
        from hermes_agent.event_log import SessionEventLog

        log = SessionEventLog()
        log.record_user_message("hello")
        log.reset()
        assert len(log) == 0


# ─── 投影函数 derive_messages ────────────────────────────────────────


class TestDeriveMessages:
    def test_full_turn_projection(self):
        """完整轮次重放：user → assistant(tool_calls) → tool → assistant"""
        from hermes_agent.event_log import SessionEventLog, derive_messages

        log = SessionEventLog()
        log.record_user_message("查询 AAPL 最新价")
        log.record_tool_call("call_1", "get_broker_market_data", '{"action":"QUOTE","ticker":"AAPL"}')
        log.record_tool_result("call_1", "get_broker_market_data", '{"status":"success","price":150.2}')
        log.record_assistant_message("AAPL 最新价 150.2，站稳双均线。")

        msgs = derive_messages(log)
        assert msgs[0] == {"role": "user", "content": "查询 AAPL 最新价"}
        # tool_call 投影为 assistant 消息的 tool_calls
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["id"] == "call_1"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "get_broker_market_data"
        # tool result 投影
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["tool_call_id"] == "call_1"
        assert "150.2" in msgs[2]["content"]
        # 最终回复
        assert msgs[3] == {"role": "assistant", "content": "AAPL 最新价 150.2，站稳双均线。"}

    def test_parallel_tool_calls_merged(self):
        """同一轮内多个 tool_call 合并为一条 assistant 消息"""
        from hermes_agent.event_log import SessionEventLog, derive_messages

        log = SessionEventLog()
        log.record_user_message("对比 AAPL 和 MSFT")
        log.record_tool_call("c1", "get_fundamental_data", '{"ticker":"AAPL"}')
        log.record_tool_call("c2", "get_fundamental_data", '{"ticker":"MSFT"}')
        log.record_tool_result("c1", "get_fundamental_data", '{"pe":28}')
        log.record_tool_result("c2", "get_fundamental_data", '{"pe":35}')

        msgs = derive_messages(log)
        assert len(msgs) == 4  # user + assistant(2 calls) + 2 tool
        assert len(msgs[1]["tool_calls"]) == 2

    def test_turn_and_memory_events_not_projected(self):
        """turn/* 与 memory/* 事件仅作审计，不进入消息投影"""
        from hermes_agent.event_log import SessionEventLog, derive_messages

        log = SessionEventLog()
        log.record_turn_start(1)
        log.record_user_message("hello")
        log.record_memory_op("compress", "window_cut=5")
        log.record_turn_end(1, content_len=10)

        msgs = derive_messages(log)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"


# ─── 「模型可见即已记录」不变量 ──────────────────────────────────────


class TestInvariant:
    def test_invariant_holds_when_recorded(self):
        """窗口内每条消息均可从日志重建 → 不变量成立"""
        from hermes_agent.event_log import SessionEventLog, check_invariant

        log = SessionEventLog()
        log.record_user_message("查询 AAPL")
        log.record_tool_call("c1", "tool_x", "{}")
        log.record_tool_result("c1", "tool_x", '{"price":1}')
        log.record_assistant_message("结果出来了")

        messages = [
            {"role": "system", "content": "系统指令"},  # system 不经日志
            {"role": "user", "content": "查询 AAPL"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "name": "tool_x", "content": '{"price":1}'},
            {"role": "assistant", "content": "结果出来了"},
        ]
        assert check_invariant(log, messages) is True

    def test_invariant_violation_detected(self):
        """模型看到了日志未记录的消息 → 不变量违反（审计红线）"""
        from hermes_agent.event_log import SessionEventLog, check_invariant

        log = SessionEventLog()
        log.record_user_message("正常消息")

        messages = [
            {"role": "user", "content": "正常消息"},
            {"role": "assistant", "content": "这条回复从未被记录"},  # 凭空出现
        ]
        assert check_invariant(log, messages) is False

    def test_compression_window_still_satisfies_invariant(self):
        """压缩裁剪后窗口是投影的子集 → 不变量仍成立"""
        from hermes_agent.event_log import SessionEventLog, check_invariant

        log = SessionEventLog()
        log.record_user_message("旧消息（会被压缩裁掉）")
        log.record_assistant_message("旧回复")
        log.record_memory_op("compress", "window_cut=2")
        log.record_user_message("新消息")
        log.record_assistant_message("新回复")

        # 模拟压缩后的窗口：只保留 system + 最新两条
        window = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "新消息"},
            {"role": "assistant", "content": "新回复"},
        ]
        assert check_invariant(log, window) is True
        # 事件日志未被压缩删改：5 条事件全在
        assert len(log) == 5


# ─── 集成：Agent 挂载事件日志 ────────────────────────────────────────


class TestAgentIntegration:
    def test_agent_has_event_log(self):
        """HermesAgent 初始化即携带 SessionEventLog"""
        from unittest.mock import AsyncMock, MagicMock

        from hermes_agent.agent import HermesAgent
        from hermes_agent.event_log import SessionEventLog

        registry = MagicMock()
        agent = HermesAgent(
            tool_registry=registry,
            session_id="test-ag01",
            llm_client=AsyncMock(),
            redis_client=MagicMock(),
        )
        assert isinstance(agent.event_log, SessionEventLog)
        assert agent.event_log.session_id == "test-ag01"

    def test_chat_records_user_message_event(self):
        """chat() 用户输入写入事件日志"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from hermes_agent.agent import HermesAgent

        registry = MagicMock()
        agent = HermesAgent(
            tool_registry=registry,
            session_id="test-ag01b",
            llm_client=AsyncMock(),
            redis_client=MagicMock(),
        )
        agent._heal_memory = AsyncMock()
        agent._save_session = AsyncMock()
        agent._sink_to_kb = AsyncMock()

        async def fake_loop():
            yield {"type": "text_chunk", "content": "ok"}
            yield {"type": "_done", "content": "ok"}

        agent._react_loop = fake_loop

        asyncio.run(agent.chat("查询 AAPL 基本面"))
        types = [e.type for e in agent.event_log.events]
        assert "user/message" in types
