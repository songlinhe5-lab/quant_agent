"""
DeepSeek 思考模式 reasoning_content 回传 — 回归测试 (2026-08-30)

线上故障: 400 "The reasoning_content in the thinking mode must be passed back to the API"。

根因: _react_loop 流式轮结束后 append assistant 消息时丢弃 reasoning_content
（只 yield SSE 给前端），下一轮请求（ReAct 工具轮次 / 下一会话轮次）缺失该字段，
DeepSeek 思考模式校验失败 → 400。

修复: 流式阶段收集 reasoning_content，append 时随 assistant 消息一并存入
self.messages（主路径 + 熔断恢复路径），经 _save_session 持久化闭环。

本测试验证: fake 流式 chunk 带 reasoning_content 时，最终 self.messages 的
assistant 消息包含 reasoning_content；无 thinking 时消息结构不变。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

import hermes_agent.agent as agent_mod
from hermes_agent.agent import HermesAgent


def _chunk(reasoning: str, content: str, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                delta=SimpleNamespace(reasoning_content=reasoning, content=content, tool_calls=tool_calls),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


async def _stream_with_reasoning():
    yield _chunk("先思考阅文基本面与EMA结构", "")
    yield _chunk("", "阅文集团 PB≈1.0，估值已回到净资产附近。")
    yield _chunk("再核对技术面", "EMA 短期均线走平。")
    yield _chunk("", "")


async def _stream_no_reasoning():
    yield _chunk("", "普通回答")
    yield _chunk("", "")


@pytest.fixture
def agent(monkeypatch, tmp_path):
    """构造轻量 HermesAgent，mock 一切外部依赖"""
    # 事件日志与 LLM 计量全 mock（避免 rollout 写盘 / 真实 token 计量）
    monkeypatch.setattr("hermes_agent.event_log.SessionEventLog", MagicMock)
    monkeypatch.setattr(agent_mod, "token_usage_store", MagicMock(record=AsyncMock()))
    monkeypatch.setattr(
        agent_mod, "usage_pricing_calculator", MagicMock(record_session_cost=AsyncMock(), record=AsyncMock())
    )
    monkeypatch.setattr(
        agent_mod,
        "repetition_guard",
        MagicMock(
            check_stuck=Mock(return_value=SimpleNamespace(is_stuck=False)),
            record_stuck_detection=AsyncMock(),
        ),
    )

    prompt_file = tmp_path / "HERMES.md"
    prompt_file.write_text("你是测试主脑", encoding="utf-8")

    redis_mock = MagicMock()
    redis_mock.incr = AsyncMock(return_value=0)
    redis_mock.expire = AsyncMock()
    redis_mock.set = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)

    inst = HermesAgent(
        tool_registry=MagicMock(),
        system_prompt_path=str(prompt_file),
        session_id="test",
        llm_client=MagicMock(),
        redis_client=redis_mock,
    )
    inst._async_db_upsert = AsyncMock()
    inst._sink_to_kb = AsyncMock()
    inst.provider_router = MagicMock()
    inst.provider_router.get_active_model = Mock(return_value="deepseek-v4-flash")
    return inst


async def _drain(inst, stream_factory):
    """跑一轮 chat_stream_async，返回事件列表与最终 messages 快照"""
    inst.provider_router.execute_with_failover = AsyncMock(return_value=(stream_factory(), None))
    events = []
    async for evt in inst.chat_stream_async("阅文集团基本面 + EMA 技术结构评估"):
        events.append(evt)
    return events, list(inst.messages)


class TestReasoningContentRoundtrip:
    async def test_reasoning_content_saved_to_messages(self, agent):
        """流式 chunk 带 reasoning_content → assistant 消息原样保存（可回传）"""
        events, messages = await _drain(agent, _stream_with_reasoning)

        assert any(evt.get("type") == "reasoning_chunk" for evt in events)
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        assert assistant_msgs, "应至少有一条 assistant 消息"
        last = assistant_msgs[-1]
        assert "先思考阅文基本面与EMA结构" in last["reasoning_content"]
        assert "再核对技术面" in last["reasoning_content"]
        assert last["content"] == "阅文集团 PB≈1.0，估值已回到净资产附近。EMA 短期均线走平。"
        # 修复后字段随消息持久化（_save_session 直接 dumps self.messages）
        import json

        dumped = json.dumps(last, ensure_ascii=False)
        assert "reasoning_content" in dumped

    async def test_no_reasoning_keeps_structure(self, agent):
        """无 thinking 时 assistant 消息不出现 reasoning_content 字段"""
        _, messages = await _drain(agent, _stream_no_reasoning)
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        assert assistant_msgs
        assert "reasoning_content" not in assistant_msgs[-1]
        assert assistant_msgs[-1]["content"] == "普通回答"
