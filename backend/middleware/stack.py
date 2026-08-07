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
from backend.workers.monitor.system_monitor import system_monitor_service

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

# 限流配置 (ARCH-07: 分级限流协议)
_IS_DEV = os.getenv("QUANT_ENV", "production") == "development"

# Gateway 级别限流 (全局防御层)
GATEWAY_RATE_LIMIT = 2000 if _IS_DEV else 200
GATEWAY_RATE_WINDOW = 60

# API 级别限流 (按接口细分，单位：req/window)
API_SPECIFIC_LIMITS = {
    "/api/v1/market/quote": (60, 60),  # Futu: 1req/sec (防限流)
    "/api/v1/macro/calendar": (30, 60),  # 宏观日历：30req/min
    "/api/v1/screener/screen": (20, 60),  # 筛选器：高成本操作
    "/api/v1/chat/completions": (10, 60),  # AI 对话：低配额
    "/api/v1/backtest/run": (5, 60),  # 回测引擎：极低配额
}

# 豁免路径 (Gateway 层跳过检查)
SKIP_PATHS = (
    "/assets",
    "/monitor",
    "/health",
    "/metrics",
    "/mcp",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/market/quotes/ws",
    "/api/v1/macro/quotes/ws",
    "/api/v1/oms/quotes/ws",
    "/api/v1/chat/",
    "/api/v1/sse/",
)


def register_middleware(app: FastAPI) -> None:
    """注册所有全局 HTTP 中间件 (注意: FastAPI middleware 执行顺序为后注册先执行)"""

    # ARCH-06: 请求级超时与取消传播 (注册为最外层，覆盖整条中间件链)
    from backend.core.request_timeout import request_timeout_middleware

    app.middleware("http")(request_timeout_middleware)

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
            "msg": "ok"
            if 200 <= response.status_code < 300
            else (data.get("message", "error") if isinstance(data, dict) else "error"),
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
        """分级限流中间件 (Gateway + API Specific)"""
        path = request.url.path

        # Step 1: 豁免路径直接放行 (Gateway 防御层)
        if any(path.startswith(prefix) for prefix in SKIP_PATHS):
            return await call_next(request)

        # Step 2: 尝试获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # Step 3: API 特定限流优先于 Gateway 限流
        api_limit, api_window = None, None
        for pattern, (limit, window) in API_SPECIFIC_LIMITS.items():
            if path.startswith(pattern) or path.endswith(pattern.split("/")[-1]):
                api_limit, api_window = limit, window
                break

        limit = api_limit if api_limit is not None else GATEWAY_RATE_LIMIT
        window = api_window if api_window is not None else GATEWAY_RATE_WINDOW

        # Step 4: 构建限流 Key (区分不同 API)
        key = f"rate_limit:{path}:{client_ip}"

        try:
            async with redis_client.pipeline() as pipe:
                await pipe.incr(key)
                await pipe.expire(key, window, nx=True)
                results = await pipe.execute()

            current = results[0]
            if current > limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "status": "error",
                        "message": f"请求过于频繁，{path}接口限制为{limit}次/{window}秒。",
                        "retry_after": window,
                    },
                )
        except Exception as e:
            # FAIL-SAFE: Redis 异常处理
            _env = os.getenv("QUANT_ENV", "production")
            if _env == "testing":
                # 测试环境: Redis 不可用时放行，避免阻塞单元测试
                return await call_next(request)
            # 生产/开发环境: 拒绝非豁免请求 (防暴力攻击)
            print(f"⚠️ [Rate Limiter] Redis 服务不可用，拒绝请求：{e}")
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=f"限流服务不可用 ({path})，请检查 Redis 连接")

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
