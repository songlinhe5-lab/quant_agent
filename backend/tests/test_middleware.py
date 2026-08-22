"""
AGENT-02 · 工具执行中间件管线测试
AGENT-09 · 工具结果正交分类测试

覆盖：
  - 正交分类（success / empty / stale / rate_limited / error / circuit_breaker）
  - 失败熔断（同一 Tool 连续 3 次 error → 熔断）
  - 限流不计入熔断计数（AGENTS.md §10.8）
  - 成功重置失败计数
  - 熔断报告含 AGENTS.md §4.4 三要素
  - 中间件管线顺序执行
  - 前端契约兼容（tool_result 事件 result.status 仍为 "error"）
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
from unittest.mock import MagicMock

# ─── AGENT-09: 正交分类 ──────────────────────────────────────────────


class TestToolResultClassification:
    """AGENT-09: 工具结果正交分类测试"""

    def test_classify_none_as_empty(self):
        """None 返回值 → EMPTY"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result(None)
        assert result.status == ToolResultStatus.EMPTY

    def test_classify_error_dict(self):
        """{"status": "error"} → ERROR"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result({"status": "error", "message": "boom"})
        assert result.status == ToolResultStatus.ERROR
        assert result.message == "boom"

    def test_classify_rate_limited(self):
        """{"status": "rate_limited"} → RATE_LIMITED"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result({"status": "rate_limited", "message": "429"})
        assert result.status == ToolResultStatus.RATE_LIMITED

    def test_classify_stale_data(self):
        """{"_stale": True} → STALE"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result({"_stale": True, "data": [1, 2, 3]})
        assert result.status == ToolResultStatus.STALE

    def test_classify_success_dict(self):
        """正常数据 dict → SUCCESS"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result({"price": 150.0, "volume": 1000})
        assert result.status == ToolResultStatus.SUCCESS
        assert result.data["price"] == 150.0

    def test_classify_success_list(self):
        """list 返回值 → SUCCESS"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result([1, 2, 3])
        assert result.status == ToolResultStatus.SUCCESS

    def test_classify_error_with_no_data(self):
        """{"error": "msg"} 无 data → ERROR"""
        from hermes_agent.middleware import ToolResultStatus, classify_raw_result

        result = classify_raw_result({"error": "connection refused"})
        assert result.status == ToolResultStatus.ERROR

    def test_to_dict_backward_compatible(self):
        """ToolResult.to_dict() 生成向后兼容的 dict"""
        from hermes_agent.middleware import ToolResult, ToolResultStatus

        tr = ToolResult(
            status=ToolResultStatus.ERROR,
            message="执行失败",
            execution_time=0.5,
        )
        d = tr.to_dict()
        assert d["status"] == "error"
        assert d["message"] == "执行失败"
        assert d["execution_time"] == 0.5


# ─── AGENT-02: 失败追踪器 ────────────────────────────────────────────


class TestFailureTracker:
    """AGENT-02: 失败计数器 + 熔断器测试"""

    def test_initial_count_zero(self):
        """初始计数为 0"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        assert tracker.get_count("test_tool") == 0
        assert not tracker.is_tripped("test_tool")

    def test_record_failure_increments(self):
        """记录失败递增计数"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        tracker.record_failure("tool_a", "error 1")
        assert tracker.get_count("tool_a") == 1
        tracker.record_failure("tool_a", "error 2")
        assert tracker.get_count("tool_a") == 2

    def test_trip_at_threshold(self):
        """达到阈值时触发熔断"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        for i in range(3):
            tracker.record_failure("tool_a", f"error {i}")
        assert tracker.is_tripped("tool_a")

    def test_not_tripped_below_threshold(self):
        """未达阈值时不熔断"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        tracker.record_failure("tool_a", "error 1")
        tracker.record_failure("tool_a", "error 2")
        assert not tracker.is_tripped("tool_a")

    def test_success_resets_count(self):
        """成功时重置计数"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        tracker.record_failure("tool_a", "error")
        tracker.record_failure("tool_a", "error")
        tracker.record_success("tool_a")
        assert tracker.get_count("tool_a") == 0
        assert not tracker.is_tripped("tool_a")

    def test_different_tools_independent(self):
        """不同工具计数独立"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        tracker.record_failure("tool_a", "error")
        tracker.record_failure("tool_a", "error")
        tracker.record_failure("tool_b", "error")
        assert tracker.get_count("tool_a") == 2
        assert tracker.get_count("tool_b") == 1

    def test_breaker_report_has_three_elements(self):
        """熔断报告含 AGENTS.md §4.4 三要素"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        for i in range(3):
            tracker.record_failure("get_broker_market_data", f"连接超时 {i}")

        report = tracker.build_breaker_report("get_broker_market_data")
        # 1. 失败 Tool 名
        assert report["tool"] == "get_broker_market_data"
        # 2. 错误原因
        assert "连接超时" in report["reason"]
        # 3. 建议检查配置项
        assert "检查" in report["suggestion"]
        assert report["consecutive_failures"] == "3"

    def test_reset_all(self):
        """reset_all 清空所有计数"""
        from hermes_agent.middleware import FailureTracker

        tracker = FailureTracker(threshold=3)
        tracker.record_failure("tool_a", "err")
        tracker.record_failure("tool_b", "err")
        tracker.reset_all()
        assert tracker.get_count("tool_a") == 0
        assert tracker.get_count("tool_b") == 0


# ─── AGENT-02: 中间件管线 ────────────────────────────────────────────


class TestMiddlewarePipeline:
    """AGENT-02: 中间件管线执行测试"""

    def test_empty_pipeline_runs_core(self):
        """空管线直接执行 core"""
        from hermes_agent.middleware import (
            ToolContext,
            ToolMiddlewarePipeline,
            ToolResult,
            ToolResultStatus,
        )

        async def core(ctx):
            return ToolResult(status=ToolResultStatus.SUCCESS, data="hello")

        pipeline = ToolMiddlewarePipeline()
        result = asyncio.run(pipeline.execute(ToolContext("test", {}), core))
        assert result.status == ToolResultStatus.SUCCESS
        assert result.data == "hello"

    def test_middleware_order(self):
        """中间件按注册顺序执行（pre 阶段）"""
        from hermes_agent.middleware import (
            ToolContext,
            ToolMiddlewarePipeline,
            ToolResult,
            ToolResultStatus,
        )

        order = []

        async def mw1(ctx, next):
            order.append("mw1_pre")
            result = await next(ctx)
            order.append("mw1_post")
            return result

        async def mw2(ctx, next):
            order.append("mw2_pre")
            result = await next(ctx)
            order.append("mw2_post")
            return result

        async def core(ctx):
            order.append("core")
            return ToolResult(status=ToolResultStatus.SUCCESS)

        pipeline = ToolMiddlewarePipeline()
        pipeline.use(mw1)
        pipeline.use(mw2)

        asyncio.run(pipeline.execute(ToolContext("test", {}), core))
        assert order == ["mw1_pre", "mw2_pre", "core", "mw2_post", "mw1_post"]

    def test_middleware_short_circuit(self):
        """中间件不调 next() 即终止链路"""
        from hermes_agent.middleware import (
            ToolContext,
            ToolMiddlewarePipeline,
            ToolResult,
            ToolResultStatus,
        )

        async def blocking_mw(ctx, next):
            return ToolResult(status=ToolResultStatus.CIRCUIT_BREAKER, message="blocked")

        async def core(ctx):
            raise RuntimeError("should not be called")

        pipeline = ToolMiddlewarePipeline()
        pipeline.use(blocking_mw)

        result = asyncio.run(pipeline.execute(ToolContext("test", {}), core))
        assert result.status == ToolResultStatus.CIRCUIT_BREAKER


# ─── AGENT-02: 熔断中间件集成 ────────────────────────────────────────


class TestCircuitBreakerMiddleware:
    """AGENT-02: 熔断中间件完整集成测试（通过 ToolRegistry.execute）"""

    def test_circuit_breaker_trips_after_3_errors(self):
        """连续 3 次 error 后熔断"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        mock_tool = MagicMock()
        mock_tool.name = "fail_tool"
        mock_tool.description = "Always fails"

        call_count = 0

        async def failing_run(**kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"fail #{call_count}")

        mock_tool.run = failing_run
        registry.tools["fail_tool"] = mock_tool

        # 前 3 次返回 error
        for i in range(3):
            result = asyncio.run(registry.execute("fail_tool"))
            assert result["status"] == "error", f"Expected error on attempt {i + 1}"

        assert call_count == 3

        # 第 4 次熔断
        result = asyncio.run(registry.execute("fail_tool"))
        assert result["status"] == "circuit_breaker"
        assert call_count == 3  # core 未被调用

    def test_success_resets_failure_count(self):
        """成功执行重置失败计数"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        mock_tool = MagicMock()
        mock_tool.name = "flaky_tool"
        mock_tool.description = "Sometimes fails"

        should_fail = True

        async def flaky_run(**kwargs):
            if should_fail:
                raise ValueError("fail")
            return {"result": "ok"}

        mock_tool.run = flaky_run
        registry.tools["flaky_tool"] = mock_tool

        # 2 次失败
        asyncio.run(registry.execute("flaky_tool"))
        asyncio.run(registry.execute("flaky_tool"))
        assert registry.failure_tracker.get_count("flaky_tool") == 2

        # 1 次成功 → 重置
        should_fail = False
        result = asyncio.run(registry.execute("flaky_tool"))
        assert result["status"] == "success"
        assert registry.failure_tracker.get_count("flaky_tool") == 0

    def test_rate_limited_does_not_count(self):
        """限流不计入失败计数（AGENTS.md §10.8）"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        mock_tool = MagicMock()
        mock_tool.name = "limited_tool"
        mock_tool.description = "Gets rate limited"

        async def rate_limited_run(**kwargs):
            return {"status": "rate_limited", "message": "429"}

        mock_tool.run = rate_limited_run
        registry.tools["limited_tool"] = mock_tool

        # 连续 5 次限流 — 不应触发熔断
        for _ in range(5):
            result = asyncio.run(registry.execute("limited_tool"))
            assert result["status"] == "rate_limited"

        assert not registry.failure_tracker.is_tripped("limited_tool")
        assert registry.failure_tracker.get_count("limited_tool") == 0

    def test_circuit_breaker_report_content(self):
        """熔断报告内容符合 AGENTS.md §4.4 三要素"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        mock_tool = MagicMock()
        mock_tool.name = "get_broker_market_data"
        mock_tool.description = "Market data"

        async def failing_run(**kwargs):
            raise ConnectionError("连接超时: Futu API 无响应")

        mock_tool.run = failing_run
        registry.tools["get_broker_market_data"] = mock_tool

        # 触发熔断
        for _ in range(3):
            asyncio.run(registry.execute("get_broker_market_data"))

        result = asyncio.run(registry.execute("get_broker_market_data"))
        assert result["status"] == "circuit_breaker"
        # 熔断报告扁平化后字段在顶层
        assert result["tool"] == "get_broker_market_data"
        assert "连接超时" in result["reason"]
        assert "检查" in result["suggestion"]


# ─── AGENT-02: ToolRegistry 集成 ─────────────────────────────────────


class TestToolRegistryMiddleware:
    """AGENT-02: ToolRegistry.execute() 经中间件管线集成测试"""

    def test_execute_returns_classified_result(self):
        """execute() 返回包含正交 status 的 dict"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.name = "success_tool"
        mock_tool.description = "A tool that succeeds"

        async def good_run(**kwargs):
            return {"price": 150.0}

        mock_tool.run = good_run
        registry.tools["success_tool"] = mock_tool

        result = asyncio.run(registry.execute("success_tool"))
        assert result["status"] == "success"
        assert result["price"] == 150.0  # 扁平化后字段在顶层

    def test_execute_error_classified(self):
        """execute() 异常结果被分类为 error"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.name = "crash_tool"
        mock_tool.description = "A tool that crashes"

        async def bad_run(**kwargs):
            raise ValueError("boom!")

        mock_tool.run = bad_run
        registry.tools["crash_tool"] = mock_tool

        result = asyncio.run(registry.execute("crash_tool"))
        assert result["status"] == "error"
        assert "boom" in result["message"]

    def test_execute_circuit_breaker_after_3_failures(self):
        """ToolRegistry.execute() 连续 3 次失败后熔断"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.name = "always_fail"
        mock_tool.description = "Always fails"

        async def fail_run(**kwargs):
            raise RuntimeError("persistent failure")

        mock_tool.run = fail_run
        registry.tools["always_fail"] = mock_tool

        # 前 3 次返回 error
        for i in range(3):
            result = asyncio.run(registry.execute("always_fail"))
            assert result["status"] == "error", f"Expected error on attempt {i + 1}"

        # 第 4 次熔断
        result = asyncio.run(registry.execute("always_fail"))
        assert result["status"] == "circuit_breaker"
        assert "熔断" in result.get("message", "") or "circuit" in str(result.get("data", {})).lower()

    def test_unknown_tool_returns_error(self):
        """未知工具返回 error（不经过管线）"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        result = asyncio.run(registry.execute("nonexistent"))
        assert result["status"] == "error"
        assert "未找到" in result["message"]

    def test_execution_time_recorded(self):
        """执行耗时被记录"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.name = "slow_tool"
        mock_tool.description = "A slow tool"

        async def slow_run(**kwargs):
            await asyncio.sleep(0.05)
            return {"result": "done"}

        mock_tool.run = slow_run
        registry.tools["slow_tool"] = mock_tool

        result = asyncio.run(registry.execute("slow_tool"))
        assert result["status"] == "success"
        assert result.get("execution_time", 0) >= 0.04


# ─── 前端契约兼容 ────────────────────────────────────────────────────


class TestFrontendContractCompatibility:
    """验证 tool_result 事件 result 字段的前端兼容性"""

    def test_error_status_preserved(self):
        """error 状态在 dict 中保持 'error' 字符串（前端 COPILOT-21 依赖）"""
        from hermes_agent.middleware import ToolResult, ToolResultStatus

        result = ToolResult(status=ToolResultStatus.ERROR, message="fail")
        d = result.to_dict()
        # 前端检查: r.status === 'error' || r.error || r.failed
        assert d["status"] == "error"

    def test_success_data_accessible(self):
        """成功结果的字段可直接访问（扁平化后无 data 包装）"""
        from hermes_agent.middleware import ToolResult, ToolResultStatus

        result = ToolResult(
            status=ToolResultStatus.SUCCESS,
            data={"price": 150.0, "symbol": "AAPL"},
        )
        d = result.to_dict()
        assert d["status"] == "success"
        # 扁平化后字段在顶层
        assert d["price"] == 150.0
        assert d["symbol"] == "AAPL"
