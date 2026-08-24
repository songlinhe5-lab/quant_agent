"""
Hermes Agent ReAct 循环单元测试
TEST-11: mock LLM + mock Tool，验证推理步进、Tool 路由、熔断中止、上下文裁剪逻辑
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.test.com")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── SessionTitleValidator ────────────────────────────────────────────
class TestSessionTitleValidator:
    """会话标题校验器测试"""

    def test_valid_title(self):
        """合法标题通过"""
        from hermes_agent.agent import SessionTitleValidator

        result = SessionTitleValidator(title="AAPL 分析")
        assert result.title == "AAPL 分析"

    def test_title_length_limit(self):
        """标题长度硬限制 15 字符"""
        from hermes_agent.agent import SessionTitleValidator

        long_title = "这是一个非常非常非常非常非常非常非常长的标题"
        result = SessionTitleValidator(title=long_title)
        assert len(result.title) <= 15

    def test_banned_words_rejected(self):
        """违禁词被拦截"""
        from pydantic import ValidationError

        from hermes_agent.agent import SessionTitleValidator

        with pytest.raises(ValidationError):
            SessionTitleValidator(title="测试违禁内容")

    def test_garbage_cleaned(self):
        """乱码清洗后为空则拒绝"""
        from pydantic import ValidationError

        from hermes_agent.agent import SessionTitleValidator

        with pytest.raises(ValidationError):
            SessionTitleValidator(title="!!!@@@###")

    def test_special_chars_cleaned(self):
        """特殊字符被清洗"""
        from hermes_agent.agent import SessionTitleValidator

        result = SessionTitleValidator(title="Hello! @World# 123")
        # 特殊字符应被移除
        assert "@" not in result.title
        assert "#" not in result.title


# ─── Memory Healing ──────────────────────────────────────────────────
class TestMemoryHealing:
    """Agent 记忆自愈测试"""

    def _make_agent_stub(self):
        """创建一个轻量 Agent stub（不连接真实服务）"""
        agent = MagicMock()
        agent.messages = []
        # 绑定真实的 _heal_memory 方法
        from hermes_agent.agent import HermesAgent

        agent._heal_memory = HermesAgent._heal_memory.__get__(agent)
        # _heal_memory 内部会 await self._compress_memory()，提供 AsyncMock 避免报错
        agent._compress_memory = AsyncMock()
        return agent

    def test_heal_empty_messages(self):
        """空消息列表不崩溃"""
        agent = self._make_agent_stub()
        agent.messages = []
        asyncio.run(agent._heal_memory())
        assert agent.messages == []

    def test_heal_normal_conversation(self):
        """正常对话不触发修复"""
        agent = self._make_agent_stub()
        agent.messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        original_len = len(agent.messages)
        asyncio.run(agent._heal_memory())
        assert len(agent.messages) == original_len

    def test_heal_orphan_tool_calls(self):
        """修复孤立的 tool_calls"""
        agent = self._make_agent_stub()
        agent.messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "query AAPL"},
            {
                "role": "assistant",
                "content": "let me check",
                "tool_calls": [{"id": "call_1"}],
            },  # noqa: E501
            # 缺少 tool 回复 → 孤立
            {"role": "user", "content": "next question"},
        ]
        asyncio.run(agent._heal_memory())
        # 孤立的 tool_calls 应被移除
        for msg in agent.messages:
            if msg.get("role") == "assistant":
                assert "tool_calls" not in msg or not msg["tool_calls"]

    def test_heal_trailing_tool_calls(self):
        """修复末尾残留的 tool_calls"""
        agent = self._make_agent_stub()
        agent.messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "check price"},
            {
                "role": "assistant",
                "content": "checking",
                "tool_calls": [{"id": "call_1"}],
            },  # noqa: E501
        ]
        asyncio.run(agent._heal_memory())
        # 末尾的 tool_calls 应被剔除
        last_msg = agent.messages[-1]
        assert last_msg.get("role") != "assistant" or not last_msg.get("tool_calls")


# ─── Tool Registry Execute ───────────────────────────────────────────
class TestToolRegistryExecute:
    """ToolRegistry.execute 测试"""

    def test_execute_unknown_tool(self):
        """执行未知 Tool 返回错误"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        result = asyncio.run(registry.execute("nonexistent_tool"))
        assert result["status"] == "error"
        assert "未找到" in result["message"]

    def test_execute_tool_with_error(self):
        """Tool 执行异常不崩溃"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        # 注册一个会崩溃的 mock tool
        mock_tool = MagicMock()
        mock_tool.name = "crash_tool"
        mock_tool.description = "A tool that crashes"

        async def crashing_run(**kwargs):
            raise ValueError("boom!")

        mock_tool.run = crashing_run
        registry.tools["crash_tool"] = mock_tool

        result = asyncio.run(registry.execute("crash_tool"))
        assert result["status"] == "error"
        assert "boom" in result["message"]

    def test_get_all_schemas(self):
        """获取所有 Tool Schema"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = registry.get_all_schemas()

        assert len(schemas) > 0
        for schema in schemas:
            assert "type" in schema
            assert schema["type"] == "function"
            assert "function" in schema
            fn = schema["function"]
            assert "name" in fn
            assert "description" in fn


# ─── Rate Limiter ────────────────────────────────────────────────────
class TestAsyncTokenBucket:
    """异步令牌桶限流器测试"""

    def test_initial_tokens(self):
        """初始令牌充足"""
        from hermes_agent.tool_registry import AsyncTokenBucket

        bucket = AsyncTokenBucket(capacity=3, fill_rate=1.0)

        # 应能立即获取 3 个令牌
        for _ in range(3):
            asyncio.run(bucket.acquire())

    def test_rate_limiting(self):
        """超出容量后需等待"""
        import time

        from hermes_agent.tool_registry import AsyncTokenBucket

        bucket = AsyncTokenBucket(capacity=2, fill_rate=10.0)

        start = time.monotonic()
        # 消耗 2 个初始令牌
        asyncio.run(bucket.acquire())
        asyncio.run(bucket.acquire())
        # 第 3 个需要等待（约 0.1s）
        asyncio.run(bucket.acquire())
        elapsed = time.monotonic() - start

        # 应该有一定等待时间
        assert elapsed >= 0.05


# ─── _safe_execute_tool 回归 ────────────────────────────────────
class TestSafeExecuteTool:
    """回归：同步的 repetition_guard.record_tool_call 不得被 await。

    修复前：await 同步方法返回 None → TypeError: object NoneType can't be used
    in 'await' expression，导致所有工具实际执行成功后仍报"工具执行异常"。
    """

    def _make_agent_stub(self):
        agent = MagicMock()
        from hermes_agent.agent import HermesAgent

        agent._safe_execute_tool = HermesAgent._safe_execute_tool.__get__(agent)
        return agent

    def test_tool_success_not_swallowed(self):
        """工具执行成功后结果应原样返回，不得被后置记录逻辑的异常吞掉"""
        agent = self._make_agent_stub()
        agent.tool_registry = MagicMock()
        agent.tool_registry.execute = AsyncMock(return_value={"status": "success", "price": 150.5})

        result = asyncio.run(agent._safe_execute_tool("get_broker_market_data", '{"ticker": "US.TSLA"}'))

        assert result.get("status") == "success"
        assert "工具执行异常" not in result.get("message", "")

    def test_tool_execute_error_still_reported(self):
        """工具执行本身抛异常时仍返回结构化错误"""
        agent = self._make_agent_stub()
        agent.tool_registry = MagicMock()
        agent.tool_registry.execute = AsyncMock(side_effect=ValueError("boom"))

        result = asyncio.run(agent._safe_execute_tool("get_broker_market_data", "{}"))

        assert result.get("status") == "error"
        assert "工具执行异常" in result.get("message", "")
