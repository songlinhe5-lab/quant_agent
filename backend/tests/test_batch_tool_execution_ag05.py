"""
AGENT-05: 脚本经 RPC 批量调工具 - 单元测试

验收标准：
1. 50 标的 × 4 工具由 200 次带上下文往返降为 1 轮
2. 沙箱逃逸否定用例（交易工具越权被拒）
3. 白名单验证（只读工具通过，交易/系统工具被拒）
4. 并发控制 + 超时保护
5. 结果脱敏（AGENT-10 集成）
"""

import asyncio

import pytest

from hermes_agent.relay_tools import (
    MAX_BATCH_SIZE,
    BatchExecutionReport,
    BatchToolCall,
    BatchToolExecutor,
    BatchToolResult,
    BatchToolValidator,
    execute_batch_tools,
)


class MockTool:
    """模拟工具类"""

    def __init__(self, name, scopes=None):
        self.name = name
        self.description = f"Mock tool: {name}"
        self._tool_scopes = scopes or []

    async def execute(self, **kwargs):
        return {"status": "success", "data": f"result from {self.name}", "params": kwargs}


class MockToolRegistry:
    """模拟工具注册表"""

    def __init__(self):
        self.tools = {}

    def register(self, name, scopes=None):
        tool = MockTool(name, scopes)
        self.tools[name] = tool
        return tool

    async def execute(self, name, **kwargs):
        if name not in self.tools:
            return {"status": "error", "message": f"工具 '{name}' 不存在"}
        return await self.tools[name].execute(**kwargs)


class TestBatchToolValidator:
    """批量工具验证器测试"""

    @pytest.fixture
    def registry(self):
        """创建带工具的模拟注册表"""
        reg = MockToolRegistry()
        # 只读数据工具（应该通过）
        reg.register("get_broker_market_data", scopes=["quote", "fund_flow"])
        reg.register("get_fundamental_data", scopes=["fundamental"])
        reg.register("calculate_technical_indicators", scopes=["indicators"])
        reg.register("get_macro_news", scopes=["news"])
        reg.register("get_macro_sentiment_history", scopes=["macro"])
        # 交易类工具（应该被拒）
        reg.register("manage_broker_orders_and_account", scopes=["trade"])
        # 系统类工具（应该被拒）
        reg.register("send_notification", scopes=["system"])
        # 无 scope 工具（应该被拒 — fail-closed）
        reg.register("unknown_tool", scopes=[])
        return reg

    def test_whitelist_allows_readonly_tools(self, registry):
        """测试白名单允许只读数据工具"""
        validator = BatchToolValidator(registry)

        # 只读工具应该通过
        is_allowed, reason = validator.validate_tool("get_broker_market_data")
        assert is_allowed, f"只读工具应该通过: {reason}"

        is_allowed, reason = validator.validate_tool("get_fundamental_data")
        assert is_allowed, f"基本面工具应该通过: {reason}"

        is_allowed, reason = validator.validate_tool("calculate_technical_indicators")
        assert is_allowed, f"技术指标工具应该通过: {reason}"

    def test_whitelist_blocks_trade_tools(self, registry):
        """测试白名单拒绝交易类工具（沙箱逃逸否定用例）"""
        validator = BatchToolValidator(registry)

        # 交易工具应该被拒
        is_allowed, reason = validator.validate_tool("manage_broker_orders_and_account")
        assert not is_allowed, "交易工具必须被拒绝"
        assert "trade" in reason.lower() or "黑名单" in reason

    def test_whitelist_blocks_system_tools(self, registry):
        """测试白名单拒绝系统类工具"""
        validator = BatchToolValidator(registry)

        is_allowed, reason = validator.validate_tool("send_notification")
        assert not is_allowed, "系统工具必须被拒绝"
        # send_notification 在 HARDCODED_BLOCKLIST 中，会被黑名单先拦截
        assert "黑名单" in reason or "system" in reason.lower() or "禁止" in reason

    def test_whitelist_blocks_unscoped_tools(self, registry):
        """测试 fail-closed: 无 scope 标注的工具被拒绝"""
        validator = BatchToolValidator(registry)

        is_allowed, reason = validator.validate_tool("unknown_tool")
        assert not is_allowed, "无 scope 工具必须被拒绝（fail-closed）"
        assert "scope" in reason.lower() or "fail-closed" in reason.lower()

    def test_whitelist_blocks_nonexistent_tools(self, registry):
        """测试不存在的工具被拒绝"""
        validator = BatchToolValidator(registry)

        is_allowed, reason = validator.validate_tool("totally_fake_tool")
        assert not is_allowed, "不存在的工具必须被拒绝"
        assert "未注册" in reason or "不存在" in reason

    def test_hardcoded_blocklist(self, registry):
        """测试硬编码黑名单（即使 scope 合法也被拒绝）"""
        # 注册一个在黑名单上的工具（模拟场景）
        registry.register("delete_global_knowledge", scopes=["search"])

        validator = BatchToolValidator(registry)
        is_allowed, reason = validator.validate_tool("delete_global_knowledge")
        assert not is_allowed, "黑名单工具必须被拒绝"
        assert "黑名单" in reason

    def test_validate_batch_separates_allowed_and_blocked(self, registry):
        """测试批量验证分离合法和被拒的调用"""
        validator = BatchToolValidator(registry)

        calls = [
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "AAPL"}),
            BatchToolCall("get_fundamental_data", {"ticker": "MSFT"}),
            BatchToolCall("manage_broker_orders_and_account", {"action": "BUY"}),  # 应该被拒
            BatchToolCall("send_notification", {"msg": "test"}),  # 应该被拒
        ]

        allowed, blocked = validator.validate_batch(calls)

        assert len(allowed) == 2, f"应该有 2 个合法调用，实际 {len(allowed)}"
        assert len(blocked) == 2, f"应该有 2 个被拒调用，实际 {len(blocked)}"
        assert all(r.status == "blocked" for r in blocked)


class TestBatchToolExecutor:
    """批量执行引擎测试"""

    @pytest.fixture
    def registry(self):
        """创建模拟注册表"""
        reg = MockToolRegistry()
        reg.register("get_broker_market_data", scopes=["quote"])
        reg.register("get_fundamental_data", scopes=["fundamental"])
        reg.register("manage_broker_orders_and_account", scopes=["trade"])
        return reg

    @pytest.fixture
    def executor(self, registry):
        """创建批量执行器"""
        return BatchToolExecutor(registry)

    @pytest.mark.asyncio
    async def test_execute_batch_success(self, executor):
        """测试批量执行成功场景"""
        calls = [
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "AAPL"}, call_id="q1"),
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "TSLA"}, call_id="q2"),
            BatchToolCall("get_fundamental_data", {"ticker": "MSFT"}, call_id="f1"),
        ]

        report = await executor.execute_batch(calls, batch_id="test_batch_001")

        assert report.batch_id == "test_batch_001"
        assert report.total_calls == 3
        assert report.successful == 3
        assert report.failed == 0
        assert report.blocked == 0
        assert len(report.results) == 3

    @pytest.mark.asyncio
    async def test_execute_batch_blocks_trade_tools(self, executor):
        """测试批量执行拒绝交易工具（沙箱逃逸否定用例）"""
        calls = [
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "AAPL"}),
            BatchToolCall("manage_broker_orders_and_account", {"action": "BUY", "ticker": "AAPL"}),  # 应该被拒
        ]

        report = await executor.execute_batch(calls, batch_id="test_batch_002")

        assert report.total_calls == 2
        assert report.successful == 1  # 只有 get_broker_market_data 成功
        assert report.blocked == 1  # 交易工具被拒
        assert any(r.status == "blocked" for r in report.results)

    @pytest.mark.asyncio
    async def test_execute_batch_size_limit(self, executor):
        """测试批量大小上限"""
        # 创建超过上限的调用列表
        calls = [BatchToolCall("get_broker_market_data", {"ticker": f"T{i}"}) for i in range(MAX_BATCH_SIZE + 10)]

        report = await executor.execute_batch(calls, batch_id="test_batch_003")

        assert report.total_calls == MAX_BATCH_SIZE + 10
        assert report.blocked == MAX_BATCH_SIZE + 10  # 全部被拒
        assert report.successful == 0

    @pytest.mark.asyncio
    async def test_execute_batch_handles_tool_errors(self, executor):
        """测试批量执行处理工具错误"""
        # 注册一个会失败的工具
        executor._registry.register("failing_tool", scopes=["quote"])

        async def failing_execute(**kwargs):
            return {"status": "error", "message": "模拟失败"}

        executor._registry.tools["failing_tool"].execute = failing_execute

        calls = [
            BatchToolCall("get_broker_market_data", {"ticker": "AAPL"}),
            BatchToolCall("failing_tool", {}),
        ]

        report = await executor.execute_batch(calls, batch_id="test_batch_004")

        assert report.total_calls == 2
        assert report.successful == 1
        assert report.failed == 1
        assert any(r.status == "error" and "模拟失败" in r.error_message for r in report.results)

    @pytest.mark.asyncio
    async def test_execute_batch_timeout_protection(self, executor):
        """测试超时保护"""
        # 注册一个超慢工具
        executor._registry.register("slow_tool", scopes=["quote"])

        async def slow_execute(**kwargs):
            await asyncio.sleep(35)  # 超过 SINGLE_CALL_TIMEOUT
            return {"status": "success"}

        executor._registry.tools["slow_tool"].execute = slow_execute

        calls = [
            BatchToolCall("slow_tool", {}),
        ]

        report = await executor.execute_batch(calls, batch_id="test_batch_005")

        assert report.timed_out == 1
        assert any(r.status == "timeout" for r in report.results)


class TestBatchExecutionReport:
    """批量执行报告测试"""

    def test_report_to_dict(self):
        """测试报告序列化"""
        report = BatchExecutionReport(
            batch_id="test_001",
            total_calls=3,
            successful=2,
            failed=1,
            blocked=0,
            timed_out=0,
            results=[
                BatchToolResult("c1", "tool1", "success", {"data": "ok"}, None, 0.5),
                BatchToolResult("c2", "tool2", "success", {"data": "ok"}, None, 0.3),
                BatchToolResult("c3", "tool3", "error", None, "失败", 0.1),
            ],
            total_execution_time=0.9,
            wall_clock_time=0.5,
        )

        d = report.to_dict()

        assert d["batch_id"] == "test_001"
        assert d["summary"]["total"] == 3
        assert d["summary"]["successful"] == 2
        assert d["summary"]["failed"] == 1
        assert d["timing"]["wall_clock_time"] == 0.5
        assert len(d["results"]) == 3


class TestConvenienceFunction:
    """便捷函数测试"""

    @pytest.fixture
    def registry(self):
        reg = MockToolRegistry()
        reg.register("get_broker_market_data", scopes=["quote"])
        return reg

    @pytest.mark.asyncio
    async def test_execute_batch_tools_function(self, registry):
        """测试 execute_batch_tools 便捷函数"""
        tool_calls = [
            {"tool_name": "get_broker_market_data", "arguments": {"ticker": "AAPL"}},
            {"tool_name": "get_broker_market_data", "arguments": {"ticker": "TSLA"}},
        ]

        report = await execute_batch_tools(registry, tool_calls, batch_id="conv_test")

        assert report["batch_id"] == "conv_test"
        assert report["summary"]["total"] == 2
        assert report["summary"]["successful"] == 2


class TestAcceptanceCriteria:
    """验收标准测试"""

    @pytest.fixture
    def registry(self):
        """创建模拟注册表（模拟 4 种只读工具）"""
        reg = MockToolRegistry()
        reg.register("get_broker_market_data", scopes=["quote"])
        reg.register("get_fundamental_data", scopes=["fundamental"])
        reg.register("calculate_technical_indicators", scopes=["indicators"])
        reg.register("get_macro_news", scopes=["news"])
        # 交易工具（应该被拒）
        reg.register("manage_broker_orders_and_account", scopes=["trade"])
        return reg

    @pytest.mark.asyncio
    async def test_50_symbols_x_4_tools_in_one_batch(self, registry):
        """
        验收标准 1: 50 标的 × 4 工具由 200 次带上下文往返降为 1 轮。

        模拟 50 个标的，每个调用 4 种只读工具，共 200 次调用。
        验证全部在 1 轮批量执行中完成。
        """
        executor = BatchToolExecutor(registry)

        # 构造 50 × 4 = 200 次调用
        tickers = [f"TICK{i}" for i in range(50)]
        tool_names = [
            "get_broker_market_data",
            "get_fundamental_data",
            "calculate_technical_indicators",
            "get_macro_news",
        ]

        calls = []
        for ticker in tickers:
            for tool_name in tool_names:
                calls.append(
                    BatchToolCall(
                        tool_name=tool_name,
                        arguments={"ticker": ticker},
                        call_id=f"{tool_name}_{ticker}",
                    )
                )

        assert len(calls) == 200, f"应该有 200 次调用，实际 {len(calls)}"

        report = await executor.execute_batch(calls, batch_id="acceptance_50x4")

        # 验收：全部成功
        assert report.total_calls == 200
        assert report.successful == 200, f"应该全部成功，实际 {report.successful}"
        assert report.blocked == 0
        assert report.failed == 0

        # 验收：1 轮完成（wall_clock_time 远小于 200 × 单次耗时）
        assert report.wall_clock_time < 10.0, f"批量执行应在 10s 内完成，实际 {report.wall_clock_time:.2f}s"

    @pytest.mark.asyncio
    async def test_sandbox_escape_trade_tool_rejected(self, registry):
        """
        验收标准 2: 沙箱逃逸否定用例 — 交易工具越权被拒。

        即使脚本尝试调用交易工具，也必须被白名单拦截。
        """
        executor = BatchToolExecutor(registry)

        calls = [
            BatchToolCall("get_broker_market_data", {"ticker": "AAPL"}),
            BatchToolCall("manage_broker_orders_and_account", {"action": "BUY", "ticker": "AAPL", "quantity": 100}),
        ]

        report = await executor.execute_batch(calls, batch_id="sandbox_escape_test")

        # 验收：交易工具被拒
        assert report.total_calls == 2
        assert report.successful == 1  # 只有 get_broker_market_data 成功
        assert report.blocked == 1  # 交易工具被拒

        # 找到被拒的调用
        blocked_results = [r for r in report.results if r.status == "blocked"]
        assert len(blocked_results) == 1
        assert blocked_results[0].tool_name == "manage_broker_orders_and_account"
        assert "交易" in blocked_results[0].error_message or "黑名单" in blocked_results[0].error_message

    @pytest.mark.asyncio
    async def test_mixed_batch_with_trade_attempt(self, registry):
        """
        验收标准 3: 混合批量调用中的交易工具尝试。

        10 个标的 × (2 只读 + 1 交易尝试) = 30 次调用。
        预期：20 成功，10 被拒。
        """
        executor = BatchToolExecutor(registry)

        calls = []
        for i in range(10):
            ticker = f"STOCK{i}"
            calls.append(BatchToolCall("get_broker_market_data", {"ticker": ticker}))
            calls.append(BatchToolCall("get_fundamental_data", {"ticker": ticker}))
            calls.append(
                BatchToolCall(
                    "manage_broker_orders_and_account",
                    {"action": "SELL", "ticker": ticker, "quantity": 50},
                )
            )

        report = await executor.execute_batch(calls, batch_id="mixed_batch_test")

        assert report.total_calls == 30
        assert report.successful == 20  # 10 × 2 只读工具
        assert report.blocked == 10  # 10 × 1 交易尝试
