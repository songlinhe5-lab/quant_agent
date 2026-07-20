"""
全局 HTTP 中间件栈
从 main.py 迁出 (ARCH-01): 响应信封 / trace_id / profiler / 限流 / 慢请求
"""

import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.core.error_codes import ErrorCode
from backend.core.otel_config import get_current_trace_id
from backend.core.redis_client import redis_client
from backend.core.structlog_config import (
    latency_ms_var,
    new_trace_id,
    symbol_var,
    trace_id_var,
)
from backend.services.system_monitor_service import system_monitor_service

# ─── API 版本前缀 ─────────────────────────────────────────────
API_URL_VERSION = os.getenv("API_URL_VERSION", "v1")
API_PREFIX = f"/api/{API_URL_VERSION}"

# 响应信封中间件跳过路径
_SKIP_TRANSFORM_PREFIXES = (
    f"{API_PREFIX}/chat",
    f"{API_PREFIX}/sse",
    f"{API_PREFIX}/ws",
    "/ws/",
    "/assets",
    "/metrics",
    "/mcp",
)

# 限流配置
_is_dev = os.getenv("QUANT_ENV", "production") == "development"
RATE_LIMIT = 1000 if _is_dev else 100
RATE_WINDOW = 60


def register_middleware(app: FastAPI) -> None:
    """注册所有全局 HTTP 中间件 (注意: FastAPI middleware 执行顺序为后注册先执行)"""

    @app.middleware("http")
    async def response_envelope_middleware(request: Request, call_next):
        """BE-13: 将旧式 JSON 响应自动包装为统一信封格式"""
        response = await call_next(request)
        path = request.url.path

        if any(path.startswith(p) for p in _SKIP_TRANSFORM_PREFIXES):
            return response
        if path in ("/", "/monitor", "/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/openapi.yaml"):
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        try:
            body_chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    body_chunks.append(chunk)
                else:
                    body_chunks.append(chunk.encode("utf-8"))
            raw_body = b"".join(body_chunks)
            data = json.loads(raw_body)
        except Exception:
            return JSONResponse(
                status_code=response.status_code,
                content=json.loads(raw_body) if raw_body else None,
                headers=dict(response.headers),
            )

        if isinstance(data, dict) and "code" in data:
            return JSONResponse(status_code=response.status_code, content=data)

        envelope = {
            "code": 0 if 200 <= response.status_code < 300 else int(ErrorCode.INTERNAL_ERROR),
            "msg": "ok" if 200 <= response.status_code < 300 else (data.get("message", "error") if isinstance(data, dict) else "error"),
            "data": data,
            "ts": int(time.time() * 1000),
        }
        return JSONResponse(status_code=response.status_code, content=envelope)

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        """BE-05 + BE-10: 为每个请求注入 trace_id 上下文"""
        otel_tid = get_current_trace_id()
        if not otel_tid:
            otel_tid = request.headers.get("x-trace-id", new_trace_id())

        token_trace = trace_id_var.set(otel_tid)
        token_symbol = symbol_var.set("-")
        token_latency = latency_ms_var.set(0.0)

        try:
            response = await call_next(request)
            otel_tid = get_current_trace_id() or otel_tid
            response.headers["X-Trace-Id"] = otel_tid
            return response
        finally:
            trace_id_var.reset(token_trace)
            symbol_var.reset(token_symbol)
            latency_ms_var.reset(token_latency)

    @app.middleware("http")
    async def pyinstrument_profiler_middleware(request: Request, call_next):
        """性能分析: ?profile=true 返回交互式调用树 HTML"""
        if request.query_params.get("profile") == "true":
            try:
                from fastapi.responses import HTMLResponse
                from pyinstrument import Profiler

                profiler = Profiler(interval=0.001, async_mode="enabled")
                profiler.start()
                await call_next(request)
                profiler.stop()
                return HTMLResponse(content=profiler.output_html(), status_code=200)
            except ImportError:
                print("⚠️ [Profiler] 未安装 pyinstrument，请先执行 pip install pyinstrument")
                return await call_next(request)
        return await call_next(request)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """全局 API 限流 (Redis 滑动窗口)"""
        if not request.url.path.startswith("/assets") and request.url.path not in ["/", "/monitor", "/health"]:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rate_limit:{client_ip}"

            try:
                async with redis_client.pipeline() as pipe:
                    await pipe.incr(key)
                    await pipe.expire(key, RATE_WINDOW, nx=True)
                    results = await pipe.execute()

                current_requests = results[0]
                if current_requests > RATE_LIMIT:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "status": "error",
                            "message": f"请求过于频繁，限制为 {RATE_LIMIT}次/{RATE_WINDOW}秒。",
                        },
                    )
            except Exception as e:
                print(f"⚠️ [Rate Limiter] Redis 限流器异常: {e}")

        return await call_next(request)

    @app.middleware("http")
    async def slow_request_middleware(request: Request, call_next):
        """监控慢请求 (>1.5s)"""
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        if process_time > 1.5 and not request.url.path.startswith("/api/chat"):
            print(f"🐢 [Slow Request] {request.method} {request.url.path} 耗时: {process_time:.2f}s")
            asyncio.create_task(
                asyncio.to_thread(
                    system_monitor_service._save_performance_log,
                    "slow_request",
                    process_time * 1000,
                    f"{request.method} {request.url.path}",
                )
            )
        return response
