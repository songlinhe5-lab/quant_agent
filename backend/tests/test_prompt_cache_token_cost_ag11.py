"""
AGENT-11: Prompt 缓存边界 + Token 成本计量 - 单元测试

验证三个核心模块：
1. usage_pricing.py - 成本计量
2. prompt_cache_boundary.py - 缓存边界管理
3. think_scrubber.py - reasoning_content 隔离
"""

import os
from datetime import date
from unittest.mock import Mock

import pytest

# 设置环境变量（必须在导入模块之前）
os.environ["PROMPT_CACHE_ENABLED"] = "true"
os.environ["REASONING_SCRUBBER_ENABLED"] = "true"
os.environ["REASONING_SUMMARY_ENABLED"] = "true"

from backend.services.ai_narrator.prompt_cache_boundary import (
    CACHE_BOUNDARY_MARKER,
)
from backend.services.ai_narrator.think_scrubber import (
    think_scrubber,
)
from backend.services.ai_narrator.usage_pricing import (
    usage_pricing_calculator,
)


class TestUsagePricing:
    """成本计量测试"""

    @pytest.fixture
    def calculator(self):
        """创建测试用计算器"""
        calc = usage_pricing_calculator
        calc.reset()
        return calc

    def test_get_pricing_known_model(self, calculator):
        """测试已知模型定价获取"""
        pricing = calculator.get_pricing("gpt-4")
        assert pricing.model_name == "gpt-4"
        assert pricing.prompt_price == 0.03
        assert pricing.completion_price == 0.06

    def test_get_pricing_unknown_model_fallback(self, calculator):
        """测试未知模型 fallback 到 default"""
        pricing = calculator.get_pricing("unknown-model")
        assert pricing.model_name == "default"
        assert pricing.prompt_price == 0.01
        assert pricing.completion_price == 0.02

    def test_get_pricing_prefix_match(self, calculator):
        """测试前缀匹配（如 deepseek-pro/v4 → deepseek-pro）"""
        pricing = calculator.get_pricing("deepseek-pro/v4")
        assert pricing.model_name == "deepseek-pro"
        assert pricing.prompt_price == 0.00014

    def test_calculate_cost_gpt4(self, calculator):
        """测试 GPT-4 成本计算"""
        cost = calculator.calculate_cost(
            model="gpt-4",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # GPT-4: $0.03/1K prompt + $0.06/1K completion
        expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
        assert abs(cost - expected) < 0.0001

    def test_calculate_cost_deepSeek(self, calculator):
        """测试 DeepSeek 成本计算"""
        cost = calculator.calculate_cost(
            model="deepseek-pro",
            prompt_tokens=10000,
            completion_tokens=5000,
        )
        # DeepSeek: $0.00014/1K prompt + $0.00028/1K completion
        expected = (10000 / 1000) * 0.00014 + (5000 / 1000) * 0.00028
        assert abs(cost - expected) < 0.00001

    @pytest.mark.asyncio
    async def test_record_session_cost(self, calculator):
        """测试会话成本记录"""
        cost = await calculator.record_session_cost(
            session_id="test-session-001",
            model="gpt-4",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert cost > 0

        # 查询会话成本
        result = await calculator.get_session_cost("test-session-001")
        assert result["cost_usd"] > 0
        assert result["metric_source"] in ["redis", "memory_fallback"]

    @pytest.mark.asyncio
    async def test_get_total_cost(self, calculator):
        """测试累计成本查询"""
        # 记录多次调用
        await calculator.record_session_cost("session-1", "gpt-4", 1000, 500)
        await calculator.record_session_cost("session-2", "deepseek-pro", 2000, 1000)

        # 查询当日累计
        result = await calculator.get_total_cost()
        assert result["cost_usd"] > 0
        assert result["date"] == date.today().isoformat()


class TestPromptCacheBoundary:
    """缓存边界管理测试"""

    @pytest.fixture
    def manager(self):
        """创建测试用管理器（强制启用）"""
        from backend.services.ai_narrator.prompt_cache_boundary import PromptCacheManager

        mgr = PromptCacheManager(enabled=True)
        mgr.reset()
        return mgr

    def test_split_messages_disabled(self, manager):
        """测试禁用时全部视为易变后缀"""
        manager._enabled = False
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = manager.split_messages(messages, "System prompt", [])
        assert len(result.cacheable_prefix) == 0
        assert len(result.volatile_suffix) == 2

    def test_split_messages_with_system_prompt(self, manager):
        """测试包含 system prompt 的拆分"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = manager.split_messages(
            messages,
            system_prompt="You are a helpful assistant.",
            tool_schemas=[],
        )
        assert len(result.cacheable_prefix) == 1
        assert result.cacheable_prefix[0]["role"] == "system"
        assert result.cacheable_prefix[0]["content"] == "You are a helpful assistant."

    def test_split_messages_with_tool_schemas(self, manager):
        """测试包含 tool schemas 的拆分"""
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        tool_schemas = [
            {"name": "get_weather", "description": "Get weather info"},
        ]
        result = manager.split_messages(
            messages,
            system_prompt="System prompt",
            tool_schemas=tool_schemas,
        )
        # Should have system prompt + tool schemas
        assert len(result.cacheable_prefix) == 2
        assert "[Tool Schemas]" in result.cacheable_prefix[1]["content"]

    def test_should_inject_boundary_marker(self, manager):
        """测试边界标记注入判断"""
        # 长度 <= 2，不注入
        short_messages = [{"role": "user", "content": "Hello"}]
        assert not manager.should_inject_boundary_marker(short_messages)

        # 长度 > 2，注入
        long_messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        assert manager.should_inject_boundary_marker(long_messages)

        # 已包含边界标记，不重复注入
        marked_messages = long_messages.copy()
        marked_messages.insert(-2, {"role": "system", "content": CACHE_BOUNDARY_MARKER})
        assert not manager.should_inject_boundary_marker(marked_messages)

    def test_inject_boundary_marker(self, manager):
        """测试边界标记注入"""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        result = manager.inject_boundary_marker(messages, boundary_position=-2)
        assert len(result) == 5
        assert result[-3]["content"] == CACHE_BOUNDARY_MARKER

    @pytest.mark.asyncio
    async def test_record_cache_hit(self, manager):
        """测试缓存命中记录"""
        await manager.record_cache_hit("session-001", is_hit=True)
        await manager.record_cache_hit("session-001", is_hit=False)

        result = await manager.get_cache_hit_rate("session-001")
        assert result["hits"] == 1
        assert result["misses"] == 1
        assert result["hit_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_get_global_cache_hit_rate(self, manager):
        """测试全局缓存命中率查询"""
        await manager.record_cache_hit("session-1", is_hit=True)
        await manager.record_cache_hit("session-2", is_hit=True)
        await manager.record_cache_hit("session-3", is_hit=False)

        result = await manager.get_cache_hit_rate()
        assert result["hits"] == 2
        assert result["misses"] == 1
        assert abs(result["hit_rate"] - 66.67) < 0.01


class TestThinkScrubber:
    """reasoning_content 隔离测试"""

    @pytest.fixture
    def scrubber(self):
        """创建测试用隔离器（强制启用）"""
        from backend.services.ai_narrator.think_scrubber import ThinkScrubber

        scrub = ThinkScrubber(enabled=True, summary_enabled=True)
        scrub.reset()
        return scrub

    def test_scrub_disabled(self, scrubber):
        """测试禁用时直接透传"""
        scrubber._enabled = False
        response = Mock()
        response.content = "Final answer"
        response.reasoning_content = "Let me think..."
        response.tool_calls = None
        response.usage = Mock()

        result = scrubber.scrub(response, model="deepseek-pro")
        assert result.content == "Final answer"
        assert result.reasoning_content is None
        assert result.reasoning_tokens == 0

    def test_scrub_with_reasoning_content(self, scrubber):
        """测试提取 reasoning_content"""
        response = Mock()
        response.content = "Final answer"
        response.reasoning_content = "Let me think step by step..."
        response.tool_calls = None
        response.usage = Mock()

        result = scrubber.scrub(response, model="deepseek-pro")
        assert result.content == "Final answer"
        assert result.reasoning_content == "Let me think step by step..."
        assert result.reasoning_tokens > 0

    def test_scrub_without_reasoning_content(self, scrubber):
        """测试无 reasoning_content 的情况"""
        response = Mock()
        response.content = "Final answer"
        response.reasoning_content = None
        response.tool_calls = None
        response.usage = Mock()

        result = scrubber.scrub(response, model="gpt-4")
        assert result.content == "Final answer"
        assert result.reasoning_content is None
        assert result.reasoning_tokens == 0

    def test_generate_summary_short_text(self, scrubber):
        """测试短文本摘要"""
        scrubber._summary_enabled = True
        reasoning = "This is a short reasoning."
        result = scrubber.generate_summary(reasoning, max_length=200)
        assert result == reasoning

    def test_generate_summary_long_text(self, scrubber):
        """测试长文本摘要"""
        scrubber._summary_enabled = True
        reasoning = "This is a very long reasoning process. " * 20
        result = scrubber.generate_summary(reasoning, max_length=100)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_generate_summary_disabled(self, scrubber):
        """测试禁用摘要生成"""
        scrubber._summary_enabled = False
        reasoning = "Some reasoning content."
        result = scrubber.generate_summary(reasoning, max_length=200)
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_reasoning_summary(self, scrubber):
        """测试推理 token 统计查询"""
        # 模拟记录推理 token
        response = Mock()
        response.content = "Answer"
        response.reasoning_content = "A" * 100  # 100 chars
        response.tool_calls = None
        response.usage = Mock()

        scrubber.scrub(response, model="deepseek-pro")

        # 查询统计
        result = await scrubber.get_reasoning_summary()
        assert result["reasoning_tokens"] > 0
        assert result["date"] == date.today().isoformat()


class TestIntegration:
    """集成测试：三个模块协同工作"""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """测试完整流程：token 记录 → 成本计算 → 缓存管理 → 推理隔离"""
        # 1. 模拟 LLM response
        response = Mock()
        response.content = "Final answer"
        response.reasoning_content = "Let me think..."
        response.tool_calls = None
        response.usage = Mock()
        response.usage.prompt_tokens = 1000
        response.usage.completion_tokens = 500
        response.usage.total_tokens = 1500

        # 2. Token 记录 + 成本计算
        await usage_pricing_calculator.record_session_cost(
            session_id="test-session",
            model="gpt-4",
            prompt_tokens=1000,
            completion_tokens=500,
        )

        # 3. 推理隔离
        scrubbed = think_scrubber.scrub(response, model="gpt-4")
        assert scrubbed.content == "Final answer"
        assert scrubbed.reasoning_content is not None

        # 4. 验证成本记录
        cost_result = await usage_pricing_calculator.get_session_cost("test-session")
        assert cost_result["cost_usd"] > 0

        # 5. 验证推理 token 记录
        reasoning_result = await think_scrubber.get_reasoning_summary()
        assert reasoning_result["reasoning_tokens"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
