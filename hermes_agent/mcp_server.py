"""
==========================================================
AGENT-13 · 把自家工具暴露为 MCP Server（对外互操作）
==========================================================

对标 hermes `transports/hermes_tools_mcp_server.py` + dsh `packages/mcp`。
复用现有 ToolRegistry，加 MCP 协议适配层。

核心思想：
  将 Quant Agent 的只读数据工具（行情/基本面/宏观/新闻/指标/资金流）
  通过 MCP (Model Context Protocol) 标准协议暴露给外部客户端
  （如 Claude Desktop / Cursor / 自定义 MCP 客户端）。

  外部客户端 → MCP JSON-RPC 2.0 → Quant Agent ToolRegistry → 数据源

安全约束（不可妥协）：
  1. 交易类工具（trade scope）默认不导出
  2. 系统/回测/策略类工具不导出
  3. 仅导出只读数据工具（quote/indicators/fund_flow/fundamental/macro/news）
  4. 受 AGENT-05 白名单 + AGENT-10 脱敏约束

MCP 协议方法（JSON-RPC 2.0）：
  - initialize → 服务端能力声明
  - tools/list → 可用工具列表（schema + description）
  - tools/call → 执行工具并返回结果
  - ping → 心跳保活

与现有架构的协同：
  - AGENT-03: ToolScope 过滤，只暴露安全 scope 的工具
  - AGENT-05: 复用 BATCH_SAFE_SCOPES + HARDCODED_BLOCKLIST
  - AGENT-02: 工具执行经中间件管线（熔断/缓存）
  - AGENT-10: 结果脱敏后才返回外部客户端

使用示例：
  # 外部 MCP 客户端连接
  GET /mcp/sse → 建立 SSE 长连接
  POST /mcp/message → 发送 JSON-RPC 请求

  # 初始化
  {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}
  → {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", ...}}

  # 列出工具
  {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
  → {"jsonrpc": "2.0", "id": 2, "result": {"tools": [...]}}

  # 调用工具
  {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_broker_market_data", "arguments": {...}}}
  → {"jsonrpc": "2.0", "id": 3, "result": {"content": [...]}}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from hermes_agent.scopes import ToolScope

logger = logging.getLogger(__name__)

# ========================================================================
# MCP 协议常量
# ========================================================================

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "quant-agent-mcp-server"
MCP_SERVER_VERSION = "1.0.0"

# MCP 导出白名单 — 仅允许只读数据工具对外暴露
MCP_EXPORT_SCOPES: Set[ToolScope] = frozenset(
    {
        ToolScope.QUOTE,  # 盘口实时价
        ToolScope.INDICATORS,  # 技术指标
        ToolScope.FUND_FLOW,  # 资金流
        ToolScope.FUNDAMENTAL,  # 基本面财务
        ToolScope.MACRO,  # 宏观数据
        ToolScope.NEWS,  # 新闻舆情
    }
)

# MCP 额外硬编码黑名单（即使 scope 匹配也不导出）
MCP_BLOCKLIST: Set[str] = frozenset(
    {
        "delete_global_knowledge",  # 删除操作
        "manage_broker_orders_and_account",  # 交易执行
        "send_notification",  # 推送通知 — 写操作
        "track_stock",  # 股票监控 — 写操作
        "download_report",  # 研报下载 — I/O 密集
        "screen_stocks",  # 选股 — 计算密集，不适合外部暴露
    }
)


# ========================================================================
# 数据结构
# ========================================================================


@dataclass
class MCPToolSchema:
    """MCP 协议工具 schema（符合 MCP 规范）"""

    name: str
    description: str
    inputSchema: Dict[str, Any]  # JSON Schema for arguments

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }


@dataclass
class MCPToolResult:
    """MCP 工具调用结果"""

    content: List[Dict[str, Any]]  # [{type: "text", text: "..."}]
    isError: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"content": self.content, "isError": self.isError}


@dataclass
class MCPServerInfo:
    """MCP 服务端信息"""

    name: str = MCP_SERVER_NAME
    version: str = MCP_SERVER_VERSION


# ========================================================================
# MCP Server 核心
# ========================================================================


class MCPServer:
    """
    MCP (Model Context Protocol) Server 实现。

    将 Quant Agent 的 ToolRegistry 包装为标准 MCP 协议端点，
    允许外部 MCP 客户端（Claude Desktop / Cursor / 自定义客户端）
    发现并调用只读数据工具。

    安全机制：
    1. 基于 ToolScope 的白名单过滤（MCP_EXPORT_SCOPES）
    2. 硬编码黑名单（MCP_BLOCKLIST）
    3. 交易/系统/回测工具绝对不暴露
    """

    def __init__(self, tool_registry=None, enabled: bool = True):
        self._enabled = enabled
        self._registry = tool_registry
        self._initialized = False
        self._exported_tools: Dict[str, MCPToolSchema] = {}
        self._build_export_cache()

    def _build_export_cache(self):
        """从 ToolRegistry 构建导出工具缓存（只读白名单过滤）"""
        if self._registry is None:
            return

        for name, tool in self._registry.tools.items():
            # 检查硬编码黑名单
            if name in MCP_BLOCKLIST:
                continue

            # 检查 scope 白名单
            tool_scopes = getattr(tool, "_tool_scopes", [])
            if not tool_scopes:
                # 无 scope 标注的工具一律不导出（fail-closed）
                continue

            # 工具必须所有 scope 都在导出白名单内才放行
            # （如果一个工具同时有 quote + trade scope，不导出）
            all_safe = all(ToolScope(s) in MCP_EXPORT_SCOPES for s in tool_scopes)
            if not all_safe:
                continue

            # 构建 MCP tool schema
            params = getattr(tool, "parameters", {"type": "object", "properties": {}})
            self._exported_tools[name] = MCPToolSchema(
                name=name,
                description=tool.description,
                inputSchema=params,
            )

        logger.info(f"🔌 [MCP Server] 导出工具数: {len(self._exported_tools)}/{len(self._registry.tools)}")

    def set_registry(self, registry):
        """延迟设置 ToolRegistry（支持启动时注入）"""
        self._registry = registry
        self._build_export_cache()

    # ── MCP 协议方法处理 ──────────────────────────────────────────

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理 MCP JSON-RPC 2.0 请求。

        Args:
            request: JSON-RPC 请求 dict
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {...}}

        Returns:
            JSON-RPC 响应 dict
        """
        jsonrpc = request.get("jsonrpc", "2.0")
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            return self._make_error(req_id, -32600, "Invalid Request: missing method")

        try:
            # 路由到对应处理器
            handler = self._get_handler(method)
            if handler is None:
                return self._make_error(req_id, -32601, f"Method not found: {method}")

            result = await handler(params)
            return {"jsonrpc": jsonrpc, "id": req_id, "result": result}

        except Exception as e:
            logger.error(f"❌ [MCP Server] 处理 {method} 异常: {e}")
            return self._make_error(req_id, -32603, f"Internal error: {str(e)}")

    def _get_handler(self, method: str):
        """获取方法处理器"""
        handlers = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "notifications/initialized": self._handle_notification_initialized,
        }
        return handlers.get(method)

    # ── MCP 协议方法实现 ──────────────────────────────────────────

    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 initialize 请求 — 返回服务端能力声明"""
        self._initialized = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},  # 工具列表不会动态变化
            },
            "serverInfo": {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            },
        }

    async def _handle_notification_initialized(self, params: Dict[str, Any]) -> None:
        """处理 notifications/initialized 通知（无响应）"""
        logger.info("🔌 [MCP Server] 客户端已初始化")
        return None

    async def _handle_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 ping 心跳"""
        return {}

    async def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理 tools/list — 返回可导出的工具列表"""
        tools = [schema.to_dict() for schema in self._exported_tools.values()]
        return {"tools": tools}

    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理 tools/call — 执行工具并返回结果。

        params:
            name: 工具名称
            arguments: 工具参数字典
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return MCPToolResult(
                content=[{"type": "text", "text": "错误: 缺少工具名称参数"}],
                isError=True,
            ).to_dict()

        # 安全检查：工具必须在导出白名单中
        if tool_name not in self._exported_tools:
            return MCPToolResult(
                content=[
                    {
                        "type": "text",
                        "text": f"错误: 工具 '{tool_name}' 不在 MCP 导出白名单中（可能是交易类/系统类工具）",
                    }
                ],
                isError=True,
            ).to_dict()

        # 检查 ToolRegistry 是否可用
        if self._registry is None:
            return MCPToolResult(
                content=[{"type": "text", "text": "错误: ToolRegistry 未初始化"}],
                isError=True,
            ).to_dict()

        # 执行工具（经 ToolRegistry 中间件管线）
        try:
            result = await self._registry.execute(tool_name, **arguments)

            # 将结果转为 MCP 格式
            result_text = json.dumps(result, ensure_ascii=False, default=str)

            # 截断过长的结果（MCP 客户端上下文有限）
            max_length = 50000
            if len(result_text) > max_length:
                result_text = result_text[:max_length] + "\n... [结果已截断，共 {} 字符]".format(len(result_text))

            return MCPToolResult(
                content=[{"type": "text", "text": result_text}],
                isError=False,
            ).to_dict()

        except Exception as e:
            logger.error(f"❌ [MCP Server] 工具 {tool_name} 执行失败: {e}")
            return MCPToolResult(
                content=[{"type": "text", "text": f"工具执行失败: {str(e)}"}],
                isError=True,
            ).to_dict()

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _make_error(self, req_id: Any, code: int, message: str) -> Dict[str, Any]:
        """构造 JSON-RPC 错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    def get_exported_tool_names(self) -> List[str]:
        """获取所有导出的工具名称（用于测试/监控）"""
        return list(self._exported_tools.keys())

    def get_exported_tool_count(self) -> int:
        """获取导出工具数量"""
        return len(self._exported_tools)

    def is_tool_exported(self, tool_name: str) -> bool:
        """检查工具是否在导出白名单中"""
        return tool_name in self._exported_tools


# ========================================================================
# 全局单例
# ========================================================================

mcp_server = MCPServer(enabled=True)
