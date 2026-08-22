"""
MCP (Model Context Protocol) SSE 通讯层 + 协议处理
从 main.py 迁出 (ARCH-01): /mcp/sse + /mcp/message
AGENT-13: 接入 MCPServer 协议处理，将 ToolRegistry 工具暴露为标准 MCP 端点
"""

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.core.redis_client import redis_client
from hermes_agent.mcp_server import MCPServer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP"])

# AGENT-13: 延迟初始化的 MCP Server + ToolRegistry
_mcp_server: Optional[MCPServer] = None
_tool_registry = None


def _get_mcp_server() -> MCPServer:
    """获取/初始化 MCP Server（延迟加载 ToolRegistry）"""
    global _mcp_server, _tool_registry
    if _mcp_server is None:
        from hermes_agent.tool_registry import ToolRegistry

        _tool_registry = ToolRegistry()
        _mcp_server = MCPServer(tool_registry=_tool_registry, enabled=True)
        logger.info(f"🔌 [MCP] Server 初始化完成，导出工具: {_mcp_server.get_exported_tool_count()} 个")
    return _mcp_server


@router.get("/sse")
async def mcp_sse(request: Request):
    """MCP SSE 协议端点：建立长连接，下发双向通讯路由"""
    session_id = str(uuid.uuid4())

    async def sse_generator():
        post_url = f"{request.url.scheme}://{request.url.netloc}/mcp/message?session_id={session_id}"
        yield f"event: endpoint\ndata: {post_url}\n\n"

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"mcp_session_{session_id}")
        try:
            while True:
                # ARCH-06: 客户端断开后立即退出，避免无谓的 Redis 订阅空转
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0),
                        timeout=15.0,
                    )
                    if msg and msg["type"] == "message":
                        message_str = msg["data"].decode("utf-8") if isinstance(msg["data"], bytes) else msg["data"]
                        yield f"data: {message_str}\n\n"
                    elif msg is None:
                        yield ": keep-alive\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe()
            finally:
                await pubsub.close()

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.post("/message")
async def mcp_message(session_id: str, payload: dict):
    """
    MCP HTTP 协议端点：接收客户端发来的 JSON-RPC 指令。
    AGENT-13: 经 MCPServer 协议处理后返回标准 JSON-RPC 响应。
    """
    # AGENT-13: 经 MCP Server 协议处理
    server = _get_mcp_server()
    result = await server.handle_request(payload)

    response_payload = json.dumps(result, ensure_ascii=False, default=str)

    # 分布式广播：通过 Redis Pub/Sub 精准投递
    receivers = await redis_client.publish(f"mcp_session_{session_id}", response_payload)
    if receivers == 0:
        raise HTTPException(status_code=404, detail="Session not found or expired on any cluster node")

    return "Accepted"


# ========================================================================
# AGENT-13: 直接 JSON-RPC 端点（无需 SSE 会话，简化集成）
# ========================================================================


@router.post("/rpc")
async def mcp_rpc(payload: dict):
    """
    AGENT-13: 直接 JSON-RPC 2.0 端点（无需 SSE 会话）。
    适用于简单 MCP 客户端或脚本直接调用。

    请求体:
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "...", "arguments": {...}}}

    响应:
        标准 JSON-RPC 2.0 响应
    """
    server = _get_mcp_server()
    result = await server.handle_request(payload)
    return result


@router.get("/tools")
async def mcp_list_tools():
    """
    AGENT-13: 快捷工具列表端点（非标准 MCP，用于快速查看导出工具）。
    返回当前 MCP Server 导出的只读工具列表。
    """
    server = _get_mcp_server()
    tools = [{"name": name, "description": schema.description} for name, schema in server._exported_tools.items()]
    return {
        "server": {"name": "quant-agent-mcp-server", "version": "1.0.0"},
        "exported_tools_count": len(tools),
        "tools": tools,
    }
