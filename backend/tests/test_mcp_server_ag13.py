"""
AGENT-13: 把自家工具暴露为 MCP Server - 单元测试

验收标准：
1. 外部 MCP 客户端可发现并调用只读行情/基本面工具
2. 交易类工具不可见（不可调用）
3. MCP 协议方法正确处理（initialize / tools/list / tools/call / ping）
4. JSON-RPC 2.0 格式正确
5. 安全拦截：黑名单工具被拒
"""

from unittest.mock import AsyncMock

import pytest

from hermes_agent.mcp_server import (
    MCP_BLOCKLIST,
    MCP_EXPORT_SCOPES,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCPServer,
)
from hermes_agent.scopes import ToolScope


class MockTool:
    """模拟工具类"""

    def __init__(self, name, description, scopes=None, parameters=None):
        self.name = name
        self.description = description
        self._tool_scopes = scopes or []
        self.parameters = parameters or {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return {"status": "success", "data": f"mock result from {self.name}"}


class MockToolRegistry:
    """模拟 ToolRegistry"""

    def __init__(self):
        self.tools = {}

    def add_tool(self, name, description, scopes=None, parameters=None):
        tool = MockTool(name, description, scopes, parameters)
        self.tools[name] = tool

    async def execute(self, name, **kwargs):
        if name not in self.tools:
            return {"status": "error", "message": f"工具 '{name}' 不存在"}
        return await self.tools[name].execute(**kwargs)


@pytest.fixture
def registry():
    """创建模拟 ToolRegistry"""
    reg = MockToolRegistry()

    # 添加只读数据工具（应该被导出）
    reg.add_tool(
        "get_broker_market_data",
        "获取市场数据（报价/历史/资金流/期权链）",
        scopes=["quote", "fund_flow"],
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["QUOTE", "HISTORY", "FUND_FLOW", "OPTION_CHAIN"]},
                "ticker": {"type": "string"},
            },
        },
    )
    reg.add_tool(
        "calculate_technical_indicators",
        "计算技术指标（MA/MACD/RSI/布林带等）",
        scopes=["indicators"],
    )
    reg.add_tool(
        "get_fundamental_data",
        "获取个股基本面数据（PE/PB/ROE等）",
        scopes=["fundamental"],
    )
    reg.add_tool(
        "get_macro_news",
        "获取全球宏观新闻",
        scopes=["macro", "news"],
    )
    reg.add_tool(
        "get_company_news",
        "获取个股新闻舆情",
        scopes=["news"],
    )

    # 添加交易类工具（不应该被导出）
    reg.add_tool(
        "manage_broker_orders_and_account",
        "管理券商订单和账户（买入/卖出/撤单）",
        scopes=["trade"],
    )

    # 添加系统工具（不应该被导出）
    reg.add_tool(
        "send_notification",
        "发送推送通知",
        scopes=["system"],
    )

    # 添加黑名单工具（scope 安全但被硬编码黑名单拦截）
    reg.add_tool(
        "delete_global_knowledge",
        "删除全局知识库条目",
        scopes=["search"],  # scope 安全但黑名单拦截
    )

    # 添加无 scope 工具（fail-closed，不导出）
    reg.add_tool(
        "unknown_tool",
        "未知工具（无 scope 标注）",
        scopes=[],
    )

    return reg


@pytest.fixture
def server(registry):
    """创建 MCP Server"""
    return MCPServer(tool_registry=registry, enabled=True)


class TestMCPServerInit:
    """MCP Server 初始化测试"""

    def test_server_creation(self, server):
        """测试服务端创建"""
        assert server is not None
        assert server.get_exported_tool_count() > 0

    def test_exported_tool_count(self, server):
        """测试导出工具数量（只读工具应被导出，交易/系统/黑名单不应）"""
        exported = server.get_exported_tool_names()
        # 应该导出 5 个只读工具
        assert server.get_exported_tool_count() == 5
        # 验证具体工具
        assert "get_broker_market_data" in exported
        assert "calculate_technical_indicators" in exported
        assert "get_fundamental_data" in exported
        assert "get_macro_news" in exported
        assert "get_company_news" in exported

    def test_trade_tool_not_exported(self, server):
        """测试交易类工具不被导出"""
        assert not server.is_tool_exported("manage_broker_orders_and_account")

    def test_system_tool_not_exported(self, server):
        """测试系统类工具不被导出"""
        assert not server.is_tool_exported("send_notification")

    def test_blacklisted_tool_not_exported(self, server):
        """测试黑名单工具不被导出（即使 scope 安全）"""
        assert not server.is_tool_exported("delete_global_knowledge")

    def test_no_scope_tool_not_exported(self, server):
        """测试无 scope 标注工具不被导出（fail-closed）"""
        assert not server.is_tool_exported("unknown_tool")


class TestMCPProtocolMethods:
    """MCP 协议方法测试"""

    @pytest.mark.asyncio
    async def test_initialize(self, server):
        """测试 initialize 方法"""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        response = await server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response

        result = response["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == MCP_SERVER_NAME
        assert result["serverInfo"]["version"] == MCP_SERVER_VERSION
        assert "capabilities" in result
        assert "tools" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_ping(self, server):
        """测试 ping 心跳"""
        request = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        response = await server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert response["result"] == {}

    @pytest.mark.asyncio
    async def test_tools_list(self, server):
        """测试 tools/list 方法"""
        request = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        response = await server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "result" in response

        tools = response["result"]["tools"]
        assert len(tools) == 5  # 5 个只读工具

        # 验证工具 schema 格式
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    @pytest.mark.asyncio
    async def test_tools_list_excludes_trade(self, server):
        """测试 tools/list 不包含交易类工具"""
        request = {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
        response = await server.handle_request(request)

        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "manage_broker_orders_and_account" not in tool_names
        assert "send_notification" not in tool_names
        assert "delete_global_knowledge" not in tool_names

    @pytest.mark.asyncio
    async def test_tools_call_success(self, server):
        """测试 tools/call 成功调用"""
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_broker_market_data",
                "arguments": {"action": "QUOTE", "ticker": "AAPL"},
            },
        }
        response = await server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 5
        assert "result" in response

        result = response["result"]
        assert "content" in result
        assert result["isError"] is False

        # 验证返回内容
        content_text = result["content"][0]["text"]
        assert "mock result from get_broker_market_data" in content_text

    @pytest.mark.asyncio
    async def test_tools_call_blocked_tool(self, server):
        """测试 tools/call 调用被拦截的交易工具"""
        request = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "manage_broker_orders_and_account",
                "arguments": {"action": "BUY", "ticker": "AAPL"},
            },
        }
        response = await server.handle_request(request)

        assert response["jsonrpc"] == "2.0"
        result = response["result"]
        assert result["isError"] is True
        assert "不在 MCP 导出白名单中" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_tools_call_missing_name(self, server):
        """测试 tools/call 缺少工具名称"""
        request = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"arguments": {"action": "QUOTE"}},
        }
        response = await server.handle_request(request)

        result = response["result"]
        assert result["isError"] is True
        assert "缺少工具名称" in result["content"][0]["text"]


class TestMCPErrorHandling:
    """MCP 错误处理测试"""

    @pytest.mark.asyncio
    async def test_unknown_method(self, server):
        """测试未知方法返回 Method not found"""
        request = {"jsonrpc": "2.0", "id": 8, "method": "unknown/method"}
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_method(self, server):
        """测试缺少 method 字段"""
        request = {"jsonrpc": "2.0", "id": 9}
        response = await server.handle_request(request)

        assert "error" in response
        assert response["error"]["code"] == -32600

    @pytest.mark.asyncio
    async def test_tool_execution_error(self, registry):
        """测试工具执行异常"""
        # 创建一个会抛异常的工具
        error_tool = MockTool("error_tool", "会报错的工具", scopes=["quote"])
        error_tool.execute = AsyncMock(side_effect=Exception("模拟工具执行异常"))
        registry.tools["error_tool"] = error_tool

        server = MCPServer(tool_registry=registry, enabled=True)

        request = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "error_tool", "arguments": {}},
        }
        response = await server.handle_request(request)

        result = response["result"]
        assert result["isError"] is True
        assert "工具执行失败" in result["content"][0]["text"]


class TestMCPSecurity:
    """MCP 安全拦截测试"""

    def test_export_scopes_whitelist(self):
        """测试导出白名单只包含只读 scope"""
        assert ToolScope.QUOTE in MCP_EXPORT_SCOPES
        assert ToolScope.INDICATORS in MCP_EXPORT_SCOPES
        assert ToolScope.FUND_FLOW in MCP_EXPORT_SCOPES
        assert ToolScope.FUNDAMENTAL in MCP_EXPORT_SCOPES
        assert ToolScope.MACRO in MCP_EXPORT_SCOPES
        assert ToolScope.NEWS in MCP_EXPORT_SCOPES

        # 交易/系统/回测不在白名单
        assert ToolScope.TRADE not in MCP_EXPORT_SCOPES
        assert ToolScope.SYSTEM not in MCP_EXPORT_SCOPES
        assert ToolScope.BACKTEST not in MCP_EXPORT_SCOPES
        assert ToolScope.STRATEGY not in MCP_EXPORT_SCOPES

    def test_blocklist_contains_dangerous_tools(self):
        """测试硬编码黑名单包含危险工具"""
        assert "delete_global_knowledge" in MCP_BLOCKLIST
        assert "manage_broker_orders_and_account" in MCP_BLOCKLIST
        assert "send_notification" in MCP_BLOCKLIST

    def test_mixed_scope_tool_not_exported(self, registry):
        """测试混合 scope 工具不被导出（如同时有 quote + trade）"""
        # 添加一个同时有 quote 和 trade scope 的工具
        registry.add_tool(
            "mixed_scope_tool",
            "混合 scope 工具",
            scopes=["quote", "trade"],  # 混合 scope
        )
        server = MCPServer(tool_registry=registry, enabled=True)
        assert not server.is_tool_exported("mixed_scope_tool")


class TestMCPIntegration:
    """MCP 集成测试"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, server):
        """测试完整 MCP 工作流：initialize → tools/list → tools/call"""
        # 1. 初始化
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
        }
        init_response = await server.handle_request(init_request)
        assert "result" in init_response
        assert init_response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

        # 2. 列出工具
        list_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        list_response = await server.handle_request(list_request)
        tools = list_response["result"]["tools"]
        assert len(tools) > 0

        # 3. 调用第一个工具
        first_tool = tools[0]["name"]
        call_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": first_tool, "arguments": {}},
        }
        call_response = await server.handle_request(call_request)
        assert "result" in call_response
        assert call_response["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_jsonrpc_format_compliance(self, server):
        """测试 JSON-RPC 2.0 格式合规性"""
        request = {"jsonrpc": "2.0", "id": 42, "method": "ping"}
        response = await server.handle_request(request)

        # 必须包含 jsonrpc, id 字段
        assert "jsonrpc" in response
        assert response["jsonrpc"] == "2.0"
        assert "id" in response
        assert response["id"] == 42

        # 成功响应必须有 result，错误响应必须有 error
        if "error" in response:
            assert "code" in response["error"]
            assert "message" in response["error"]
        else:
            assert "result" in response
