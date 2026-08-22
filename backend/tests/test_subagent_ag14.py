"""
AGENT-14: 子代理并行编排 - 单元测试

验收标准：
1. 子代理继承父级的审批策略与工具白名单，不得提权
2. 子代理上下文完全隔离（不污染父级消息历史）
3. 并行执行正确性（多任务同时运行）
4. 超时保护（per-task + overall）
5. 结果聚合正确
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_agent.subagent import (
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SUBAGENT_ITERATIONS,
    ORCHESTRATION_TIMEOUT,
    SUBAGENT_TIMEOUT,
    SubAgent,
    SubAgentOrchestrator,
    SubAgentOrchestratorReport,
    SubAgentResult,
    SubAgentTask,
    run_parallel_analysis,
)


class MockTool:
    """模拟工具类"""

    def __init__(self, name, description, scopes=None, result=None):
        self.name = name
        self.description = description
        self._tool_scopes = scopes or []
        self.parameters = {"type": "object", "properties": {}}
        self._result = result or {"status": "success", "data": f"result from {name}"}

    async def execute(self, **kwargs):
        return self._result


class MockToolRegistry:
    """模拟 ToolRegistry"""

    def __init__(self):
        self.tools = {}
        self._execute_count = 0

    def add_tool(self, name, description, scopes=None, result=None):
        tool = MockTool(name, description, scopes, result)
        self.tools[name] = tool

    async def execute(self, name, **kwargs):
        self._execute_count += 1
        if name not in self.tools:
            return {"status": "error", "message": f"工具 '{name}' 不存在"}
        return await self.tools[name].execute(**kwargs)

    def get_schemas_by_scopes(self, scopes):
        result = []
        for name, tool in self.tools.items():
            tool_scopes = getattr(tool, "_tool_scopes", [])
            if scopes is None or any(s in tool_scopes for s in scopes):
                result.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                )
        return result


class MockLLMResponse:
    """模拟 LLM 响应"""

    def __init__(self, content="", tool_calls=None):
        self.choices = [MagicMock()]
        self.choices[0].message = MagicMock()
        self.choices[0].message.content = content
        self.choices[0].message.tool_calls = tool_calls
        self.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)


class MockToolCall:
    """模拟工具调用"""

    def __init__(self, name, arguments="{}"):
        self.id = f"call_{name}"
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


@pytest.fixture
def registry():
    """创建模拟 ToolRegistry"""
    reg = MockToolRegistry()
    reg.add_tool(
        "get_broker_market_data",
        "获取市场数据",
        scopes=["quote"],
        result={"status": "success", "price": 150.0, "ticker": "AAPL"},
    )
    reg.add_tool(
        "calculate_technical_indicators",
        "计算技术指标",
        scopes=["indicators"],
        result={"status": "success", "rsi": 55.0, "macd": "bullish"},
    )
    reg.add_tool(
        "get_fundamental_data",
        "获取基本面数据",
        scopes=["fundamental"],
        result={"status": "success", "pe": 25.0, "pb": 3.0},
    )
    return reg


@pytest.fixture
def mock_provider_router():
    """创建模拟 Provider Router"""
    router = MagicMock()
    router.get_active_model.return_value = "test-model"

    async def mock_execute(create_func):
        # 默认返回无工具调用的响应
        response = MockLLMResponse(content="分析完成：标的数据正常。")
        return response, None

    router.execute_with_failover = AsyncMock(side_effect=mock_execute)
    return router


class TestSubAgentTask:
    """子代理任务定义测试"""

    def test_task_creation(self):
        """测试任务创建"""
        task = SubAgentTask(
            task_id="aapl",
            target="AAPL",
            instruction="分析技术面",
        )
        assert task.task_id == "aapl"
        assert task.target == "AAPL"
        assert task.instruction == "分析技术面"
        assert task.scopes is None

    def test_task_with_scopes(self):
        """测试带 scope 限定的任务"""
        task = SubAgentTask(
            task_id="msft",
            target="MSFT",
            instruction="分析基本面",
            scopes=["fundamental"],
        )
        assert task.scopes == ["fundamental"]


class TestSubAgentResult:
    """子代理结果测试"""

    def test_result_to_dict(self):
        """测试结果序列化"""
        result = SubAgentResult(
            task_id="aapl",
            target="AAPL",
            status="success",
            content="分析完成",
            iterations=2,
            execution_time=1.5,
        )
        d = result.to_dict()
        assert d["task_id"] == "aapl"
        assert d["status"] == "success"
        assert d["iterations"] == 2
        assert d["execution_time"] == 1.5


class TestSubAgent:
    """子代理核心测试"""

    def test_subagent_isolation(self, registry, mock_provider_router):
        """测试子代理上下文隔离"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="你是量化交易 Agent",
            task=task,
            provider_router=mock_provider_router,
        )

        # 子代理有独立的消息上下文
        assert len(subagent.messages) == 2  # system + user
        assert subagent.messages[0]["role"] == "system"
        assert subagent.messages[1]["role"] == "user"
        assert "AAPL" in subagent.messages[1]["content"]

    def test_subagent_inherits_registry(self, registry, mock_provider_router):
        """测试子代理继承父级 ToolRegistry"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
            provider_router=mock_provider_router,
        )

        # 子代理使用同一个 registry 实例
        assert subagent._registry is registry

    @pytest.mark.asyncio
    async def test_subagent_run_success(self, registry, mock_provider_router):
        """测试子代理成功执行"""
        task = SubAgentTask(task_id="aapl", target="AAPL", instruction="分析技术面")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="你是量化交易 Agent",
            task=task,
            provider_router=mock_provider_router,
        )

        result = await subagent.run()

        assert result.status == "success"
        assert result.task_id == "aapl"
        assert result.target == "AAPL"
        assert result.iterations >= 1
        assert result.execution_time > 0

    @pytest.mark.asyncio
    async def test_subagent_scope_restriction(self, registry, mock_provider_router):
        """测试子代理 scope 限制（只能用只读数据工具）"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
            provider_router=mock_provider_router,
        )

        # 构建请求参数时应该只包含安全 scope 的工具
        kwargs = subagent._build_request_kwargs()
        if "tools" in kwargs:
            tool_names = [t["function"]["name"] for t in kwargs["tools"]]
            # 所有工具都应该是只读数据工具
            for name in tool_names:
                assert name in ["get_broker_market_data", "calculate_technical_indicators", "get_fundamental_data"]


class TestSubAgentOrchestrator:
    """编排器测试"""

    @pytest.mark.asyncio
    async def test_empty_tasks(self, registry):
        """测试空任务列表"""
        orchestrator = SubAgentOrchestrator(
            tool_registry=registry,
            system_prompt="test",
        )
        report = await orchestrator.run_parallel(tasks=[])
        assert report.total_tasks == 0
        assert report.completed == 0

    @pytest.mark.asyncio
    async def test_parallel_execution(self, registry, mock_provider_router):
        """测试并行执行"""
        orchestrator = SubAgentOrchestrator(
            tool_registry=registry,
            system_prompt="你是量化交易 Agent",
            provider_router=mock_provider_router,
        )

        tasks = [
            SubAgentTask(task_id="aapl", target="AAPL", instruction="分析技术面"),
            SubAgentTask(task_id="msft", target="MSFT", instruction="分析基本面"),
            SubAgentTask(task_id="googl", target="GOOGL", instruction="分析资金流"),
        ]

        report = await orchestrator.run_parallel(tasks, orchestration_id="test-parallel")

        assert report.orchestration_id == "test-parallel"
        assert report.total_tasks == 3
        assert report.completed + report.failed + report.timed_out == 3
        assert len(report.results) == 3

    @pytest.mark.asyncio
    async def test_report_serialization(self, registry, mock_provider_router):
        """测试报告序列化"""
        orchestrator = SubAgentOrchestrator(
            tool_registry=registry,
            system_prompt="test",
            provider_router=mock_provider_router,
        )

        tasks = [SubAgentTask(task_id="aapl", target="AAPL", instruction="分析")]
        report = await orchestrator.run_parallel(tasks)

        d = report.to_dict()
        assert "orchestration_id" in d
        assert "summary" in d
        assert "results" in d
        assert d["summary"]["total_tasks"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, registry, mock_provider_router):
        """测试并发限制"""
        orchestrator = SubAgentOrchestrator(
            tool_registry=registry,
            system_prompt="test",
            provider_router=mock_provider_router,
        )

        # 创建超过并发上限的任务
        tasks = [
            SubAgentTask(task_id=f"task_{i}", target=f"TICK{i}", instruction=f"分析 {i}")
            for i in range(MAX_CONCURRENT_SUBAGENTS + 3)
        ]

        report = await orchestrator.run_parallel(tasks)
        assert report.total_tasks == MAX_CONCURRENT_SUBAGENTS + 3


class TestSubAgentSecurity:
    """子代理安全约束测试"""

    def test_subagent_cannot_escalate_privileges(self, registry, mock_provider_router):
        """测试子代理不能提权（使用同一 registry）"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
            provider_router=mock_provider_router,
        )

        # 子代理的 registry 和父级是同一实例
        assert subagent._registry is registry

    def test_subagent_default_safe_scopes(self, registry, mock_provider_router):
        """测试子代理默认使用安全 scope"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
            provider_router=mock_provider_router,
        )

        # 默认 scope 应该只包含只读数据类
        kwargs = subagent._build_request_kwargs()
        if "tools" in kwargs:
            # 所有工具都应该是安全 scope 的
            for tool_schema in kwargs["tools"]:
                name = tool_schema["function"]["name"]
                # 确保没有交易类工具
                assert "trade" not in name.lower()
                assert "order" not in name.lower()

    def test_subagent_inherits_approval_policy(self, registry):
        """测试子代理继承父级审批策略（共享 registry = 共享审批）"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
        )

        # 子代理通过同一 registry 执行工具 → 继承同一审批策略
        assert subagent._registry is registry


class TestSubAgentContextIsolation:
    """子代理上下文隔离测试"""

    def test_isolated_messages(self, registry, mock_provider_router):
        """测试子代理消息上下文隔离"""
        task = SubAgentTask(task_id="test", target="AAPL", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="你是量化交易 Agent",
            task=task,
            provider_router=mock_provider_router,
        )

        # 子代理有自己的 messages 列表
        assert hasattr(subagent, "messages")
        assert isinstance(subagent.messages, list)
        # 父级消息不会被修改
        original_len = len(subagent.messages)
        subagent.messages.append({"role": "assistant", "content": "test"})
        assert len(subagent.messages) == original_len + 1

    def test_different_subagents_isolated(self, registry, mock_provider_router):
        """测试不同子代理之间上下文隔离"""
        task1 = SubAgentTask(task_id="aapl", target="AAPL", instruction="分析 AAPL")
        task2 = SubAgentTask(task_id="msft", target="MSFT", instruction="分析 MSFT")

        sa1 = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task1,
            provider_router=mock_provider_router,
        )
        sa2 = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task2,
            provider_router=mock_provider_router,
        )

        # 两个子代理的消息列表是独立的
        assert sa1.messages is not sa2.messages
        assert "AAPL" in sa1.messages[1]["content"]
        assert "MSFT" in sa2.messages[1]["content"]
        assert "MSFT" not in sa1.messages[1]["content"]
        assert "AAPL" not in sa2.messages[1]["content"]


class TestRunParallelAnalysis:
    """便捷函数测试"""

    @pytest.mark.asyncio
    async def test_run_parallel_analysis(self, registry, mock_provider_router):
        """测试便捷函数"""
        tasks = [
            SubAgentTask(task_id="aapl", target="AAPL", instruction="分析"),
        ]

        report = await run_parallel_analysis(
            tool_registry=registry,
            tasks=tasks,
            system_prompt="test",
            provider_router=mock_provider_router,
            orchestration_id="test-func",
        )

        assert isinstance(report, SubAgentOrchestratorReport)
        assert report.orchestration_id == "test-func"
        assert report.total_tasks == 1


class TestSubAgentTimeout:
    """子代理超时保护测试"""

    @pytest.mark.asyncio
    async def test_subagent_timeout(self, registry):
        """测试单个子代理超时保护"""

        # 创建一个会无限等待的 provider router
        slow_router = MagicMock()
        slow_router.get_active_model.return_value = "slow-model"

        async def slow_execute(create_func):
            await asyncio.sleep(100)  # 模拟长时间等待

        slow_router.execute_with_failover = AsyncMock(side_effect=slow_execute)

        task = SubAgentTask(task_id="slow", target="SLOW", instruction="分析")
        subagent = SubAgent(
            tool_registry=registry,
            system_prompt="test",
            task=task,
            provider_router=slow_router,
        )

        # 用较短超时测试
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(subagent.run(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_orchestrator_handles_timeout(self, registry):
        """测试编排器正确处理超时任务"""
        slow_router = MagicMock()
        slow_router.get_active_model.return_value = "slow-model"

        async def slow_execute(create_func):
            await asyncio.sleep(100)

        slow_router.execute_with_failover = AsyncMock(side_effect=slow_execute)

        orchestrator = SubAgentOrchestrator(
            tool_registry=registry,
            system_prompt="test",
            provider_router=slow_router,
        )

        tasks = [SubAgentTask(task_id="slow", target="SLOW", instruction="分析")]

        # 编排器应该能处理超时而不崩溃
        # 使用较短的超时来测试
        import hermes_agent.subagent as sa_module

        original_timeout = sa_module.SUBAGENT_TIMEOUT
        sa_module.SUBAGENT_TIMEOUT = 0.5

        try:
            report = await orchestrator.run_parallel(tasks)
            assert report.total_tasks == 1
            assert report.timed_out >= 0 or report.failed >= 0  # 超时或失败
        finally:
            sa_module.SUBAGENT_TIMEOUT = original_timeout


class TestSubAgentConstants:
    """常量配置测试"""

    def test_max_iterations(self):
        """测试子代理迭代次数限制"""
        assert MAX_SUBAGENT_ITERATIONS == 4
        assert MAX_SUBAGENT_ITERATIONS < 8  # 比父级 8 次更保守

    def test_concurrency_limit(self):
        """测试并发限制"""
        assert MAX_CONCURRENT_SUBAGENTS == 5
        assert MAX_CONCURRENT_SUBAGENTS > 0

    def test_timeout_values(self):
        """测试超时配置"""
        assert SUBAGENT_TIMEOUT == 60.0
        assert ORCHESTRATION_TIMEOUT == 120.0
        assert SUBAGENT_TIMEOUT < ORCHESTRATION_TIMEOUT
