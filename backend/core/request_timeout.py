"""
ARCH-06: 请求级超时与取消传播中间件

- 单 API 请求最大执行时间 (screener 90s / market 30s / 默认 60s)，可通过环境变量覆盖。
- 非流式请求：asyncio.timeout 包裹，超时返回 504 并中断下游协程。
- 流式请求 (SSE / NDJSON)：设置 deadline，交由 heartbeat_wrap 做心跳保活 +
  客户端断开取消 + 超时熔断，避免被 Cloudflare (100s) 等代理静默掐断。
"""

import asyncio
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from backend.core.stream_utils import (
    NDJSON_HEARTBEAT,
    SSE_HEARTBEAT,
    heartbeat_wrap,
)

API_PREFIX = f"/api/{os.getenv('API_URL_VERSION', 'v1')}"


def _resolve_timeout(path: str) -> float:
    """按路由前缀解析请求超时 (秒)"""
    if path.startswith(f"{API_PREFIX}/screener/"):
        return float(os.getenv("REQUEST_TIMEOUT_SCREENER", "90"))
    if path.startswith(f"{API_PREFIX}/market/"):
        return float(os.getenv("REQUEST_TIMEOUT_MARKET", "30"))
    # 注意：market-review 等前缀不含尾斜杠，不会被误判为 market 路由
    return float(os.getenv("REQUEST_TIMEOUT_DEFAULT", "60"))


async def request_timeout_middleware(request: Request, call_next):
    """请求级超时与取消传播 (ARCH-06)"""
    timeout = _resolve_timeout(request.url.path)
    request.state.timeout = timeout
    deadline = time.monotonic() + timeout

    try:
        async with asyncio.timeout(timeout):
            response = await call_next(request)
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={
                "status": "error",
                "code": "REQUEST_TIMEOUT",
                "message": f"请求处理超时 (>{timeout:.0f}s)，已主动中断下游任务",
            },
        )

    # 流式响应：交给 heartbeat_wrap 统一做心跳保活 + 断开取消 + 超时熔断
    if isinstance(response, StreamingResponse):
        hb = SSE_HEARTBEAT if response.media_type == "text/event-stream" else NDJSON_HEARTBEAT
        response.body_iterator = heartbeat_wrap(
            response.body_iterator,
            request,
            interval=15.0,
            heartbeat=hb,
            deadline=deadline,
        )
    return response
