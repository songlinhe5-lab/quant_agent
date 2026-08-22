"""
AGENT-12: 重复/停滞守卫 - 单元测试

验证 RepetitionGuard 的四个检测维度：
1. 同参数重复调用
2. 同结论重复输出
3. 工具调用无进展
4. 循环模式检测（A→B→A→B）
"""

import os
from datetime import date

import pytest

# 设置环境变量（必须在导入模块之前）
os.environ["REPETITION_GUARD_ENABLED"] = "true"

from backend.services.ai_narrator.repetition_guard import (
    MAX_CONSECUTIVE_IDENTICAL_CALLS,
    MAX_CONSECUTIVE_NO_PROGRESS,
    RepetitionGuard,
)


class TestRepetitionGuard:
    """重复/停滞守卫测试"""

    @pytest.fixture
    def guard(self):
        """创建测试用守卫（强制启用）"""
        g = RepetitionGuard(enabled=True)
        g.reset()
        return g

    def test_record_tool_call(self, guard):
        """测试工具调用记录"""
        guard.record_tool_call(
            tool_name="get_weather",
            arguments={"city": "Beijing"},
            result={"temp": 25, "condition": "sunny"},
            output_summary="Beijing weather: 25°C, sunny",
        )
        assert len(guard._call_history) == 1

    def test_check_stuck_insufficient_history(self, guard):
        """测试历史记录不足时不检测停滞"""
        guard.record_tool_call("tool1", {"arg": "val"}, "result1")
        result = guard.check_stuck(current_iteration=1, max_iterations=8)
        assert not result.is_stuck

    def test_check_identical_tool_calls(self, guard):
        """测试同参数重复调用检测"""
        # 连续 3 次调用相同工具和参数
        for _ in range(MAX_CONSECUTIVE_IDENTICAL_CALLS):
            guard.record_tool_call(
                tool_name="get_weather",
                arguments={"city": "Beijing"},
                result={"temp": 25},
            )

        result = guard.check_stuck(current_iteration=3, max_iterations=8)
        assert result.is_stuck
        assert result.reason == "identical_tool_calls"
        assert result.details["tool_name"] == "get_weather"
        assert result.details["consecutive_count"] == MAX_CONSECUTIVE_IDENTICAL_CALLS

    def test_check_identical_outputs(self, guard):
        """测试同结论重复输出检测"""
        # 连续 2 次输出相同结果（不同工具）
        guard.record_tool_call(
            tool_name="tool1",
            arguments={"arg": "val1"},
            result="Same output text",
            output_summary="Same output text",
        )
        guard.record_tool_call(
            tool_name="tool2",
            arguments={"arg": "val2"},
            result="Same output text",
            output_summary="Same output text",
        )

        result = guard.check_stuck(current_iteration=2, max_iterations=8)
        assert result.is_stuck
        assert result.reason == "identical_outputs"
        assert "Same output text" in result.details["output_summary"]

    def test_check_no_progress(self, guard):
        """测试工具调用无进展检测"""
        # 连续 4 次调用返回相同结果（但工具和参数不同，避免触发 identical_outputs）
        for i in range(MAX_CONSECUTIVE_NO_PROGRESS):
            guard.record_tool_call(
                tool_name=f"tool{i}",
                arguments={"arg": f"val{i}"},
                result="Same result",  # 结果相同
                output_summary=f"Different output {i}",  # 输出摘要不同
            )

        result = guard.check_stuck(current_iteration=4, max_iterations=8)
        assert result.is_stuck
        assert result.reason == "no_progress"
        assert result.details["result_hash"] is not None

    def test_check_loop_pattern(self, guard):
        """测试循环模式检测（A→B→A→B）"""
        # A→B→A→B 模式
        guard.record_tool_call("toolA", {"arg": "1"}, "resultA")
        guard.record_tool_call("toolB", {"arg": "2"}, "resultB")
        guard.record_tool_call("toolA", {"arg": "1"}, "resultA")
        guard.record_tool_call("toolB", {"arg": "2"}, "resultB")

        result = guard.check_stuck(current_iteration=4, max_iterations=8)
        assert result.is_stuck
        assert result.reason == "loop_pattern"
        assert result.details["pattern"] == ["toolA", "toolB"]

    def test_check_not_stuck(self, guard):
        """测试正常情况（未停滞）"""
        # 不同的工具调用
        guard.record_tool_call("tool1", {"arg": "1"}, "result1")
        guard.record_tool_call("tool2", {"arg": "2"}, "result2")
        guard.record_tool_call("tool3", {"arg": "3"}, "result3")

        result = guard.check_stuck(current_iteration=3, max_iterations=8)
        assert not result.is_stuck
        assert result.reason is None

    def test_iterations_saved_calculation(self, guard):
        """测试节省的迭代轮数计算"""
        # 连续 3 次相同调用
        for _ in range(MAX_CONSECUTIVE_IDENTICAL_CALLS):
            guard.record_tool_call("tool1", {"arg": "1"}, "result1")

        result = guard.check_stuck(current_iteration=3, max_iterations=8)
        assert result.is_stuck
        # 节省轮数 = max_iterations - current_iteration
        assert result.iterations_saved == 8 - 3

    @pytest.mark.asyncio
    async def test_record_stuck_detection(self, guard):
        """测试停滞检测事件记录"""
        await guard.record_stuck_detection(
            session_id="test-session-001",
            reason="identical_tool_calls",
            iterations_saved=5,
        )

        # 查询统计
        stats = await guard.get_stuck_stats("test-session-001")
        assert stats["total"] == 1
        assert stats["metric_source"] in ["redis", "memory_fallback"]

    @pytest.mark.asyncio
    async def test_get_global_stuck_stats(self, guard):
        """测试全局停滞统计查询"""
        await guard.record_stuck_detection("session-1", "identical_tool_calls", 3)
        await guard.record_stuck_detection("session-2", "no_progress", 4)

        stats = await guard.get_stuck_stats()
        assert stats["total"] == 2
        assert stats["date"] == date.today().isoformat()

    def test_reset(self, guard):
        """测试重置检测状态"""
        guard.record_tool_call("tool1", {"arg": "1"}, "result1")
        guard.record_tool_call("tool2", {"arg": "2"}, "result2")
        assert len(guard._call_history) == 2

        guard.reset()
        assert len(guard._call_history) == 0

    def test_text_similarity_calculation(self, guard):
        """测试文本相似度计算"""
        # 完全相同
        sim1 = guard._calculate_text_similarity("hello world", "hello world")
        assert sim1 == 1.0

        # 部分相同
        sim2 = guard._calculate_text_similarity("hello world", "hello python")
        assert 0.0 < sim2 < 1.0

        # 完全不同
        sim3 = guard._calculate_text_similarity("hello", "world")
        assert sim3 == 0.0

        # 空字符串
        sim4 = guard._calculate_text_similarity("", "hello")
        assert sim4 == 0.0


class TestRepetitionGuardIntegration:
    """集成测试：模拟真实死循环场景"""

    @pytest.mark.asyncio
    async def test_dead_loop_detection(self):
        """测试死循环检测（验收标准：3 轮内识别停滞）"""
        guard = RepetitionGuard(enabled=True)
        guard.reset()

        # 模拟死循环：连续 3 次调用相同工具（但输出不同，避免触发 identical_outputs）
        for i in range(3):
            guard.record_tool_call(
                tool_name="get_broker_market_data",
                arguments={"action": "QUOTE", "ticker": "AAPL"},
                result={"price": 150.0, "change": 0.0},
                output_summary=f"AAPL quote round {i}",  # 不同的输出摘要
            )

            # 每轮检查
            result = guard.check_stuck(current_iteration=i + 1, max_iterations=8)

            if i < 2:
                # 前 2 轮不应检测到停滞（历史不足）
                assert not result.is_stuck
            else:
                # 第 3 轮应检测到停滞（identical_tool_calls）
                assert result.is_stuck
                assert result.reason == "identical_tool_calls"
                assert result.iterations_saved == 8 - 3  # 节省 5 轮

        # 记录停滞事件
        await guard.record_stuck_detection(
            session_id="test-dead-loop",
            reason="identical_tool_calls",
            iterations_saved=5,
        )

        # 验证统计
        stats = await guard.get_stuck_stats("test-dead-loop")
        assert stats["total"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
