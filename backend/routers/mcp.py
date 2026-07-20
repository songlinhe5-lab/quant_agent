"""
MCP (Model Context Protocol) SSE 通讯层
从 main.py 迁出 (ARCH-01): /mcp/sse + /mcp/message
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.core.redis_client import redis_client

router = APIRouter(prefix="/mcp", tags=["MCP"])


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
    """MCP HTTP 协议端点：接收客户端发来的 JSON-RPC 指令"""
    response_payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "status": "success",
                "message": f"Action {payload.get('method')} executed by Hermes Agent",
            },
        }
    )

    # 分布式广播：通过 Redis Pub/Sub 精准投递
    receivers = await redis_client.publish(f"mcp_session_{session_id}", response_payload)
    if receivers == 0:
        raise HTTPException(status_code=404, detail="Session not found or expired on any cluster node")

    return "Accepted"
