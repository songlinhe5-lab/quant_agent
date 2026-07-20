"""
系统健康检查 & 基础设施端点
从 main.py 迁出 (ARCH-01): health / cluster / metrics / monitor / webhook / root
"""

import asyncio
import os
import secrets
from typing import Optional

import prometheus_client
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from backend.core.redis_client import redis_client
from backend.services.notification_service import notification_service
from backend.services.system_monitor_service import system_monitor_service

router = APIRouter(tags=["System Health"])

# 根级路由 (无前缀)
root_router = APIRouter(tags=["Root"])

# ==========================================
# --- Prometheus 指标 (Basic Auth 保护) ---
# ==========================================
metrics_security = HTTPBasic()


def verify_metrics_auth(credentials: HTTPBasicCredentials = Depends(metrics_security)) -> str:
    current_user_bytes = credentials.username.encode("utf-8")
    current_pass_bytes = credentials.password.encode("utf-8")
    env_user_bytes = os.getenv("METRICS_USER", "admin").encode("utf-8")
    env_pass_bytes = os.getenv("METRICS_PASS", "admin").encode("utf-8")

    correct_username = secrets.compare_digest(current_user_bytes, env_user_bytes)
    correct_password = secrets.compare_digest(current_pass_bytes, env_pass_bytes)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized metrics access",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@root_router.get("/metrics", include_in_schema=False)
def metrics(username: str = Depends(verify_metrics_auth)):
    return Response(
        content=prometheus_client.generate_latest(),
        media_type=prometheus_client.CONTENT_TYPE_LATEST,
    )


# ==========================================
# --- 健康检查 & 集群状态 ---
# ==========================================
@router.get("/health")
async def health_check():
    """系统健康检查接口 (供 Docker / K8s Liveness Probe 使用)"""
    components = {}
    status_code = 200
    overall_status = "healthy"

    # 1. Redis
    try:
        await redis_client.ping()
        components["redis"] = "connected"
    except Exception as e:
        components["redis"] = f"disconnected ({e})"
        overall_status = "unhealthy"
        status_code = 503

    # 2. Futu (跳过，可能在远程节点)
    components["futu"] = "skipped (may run on remote slave nodes)"

    # 3. YFinance (跳过，防限流)
    components["yfinance"] = "skipped (prevent rate limits)"

    # 4. asyncio 线程池
    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None and hasattr(executor, "_max_workers"):
        components["asyncio_thread_pool"] = {
            "max_workers": executor._max_workers,
            "spawned_threads": len(executor._threads),
            "pending_tasks": executor._work_queue.qsize(),
        }
    else:
        components["asyncio_thread_pool"] = "idle (lazy initialized)"

    # 5. FastAPI/AnyIO 线程池
    try:
        from anyio.to_thread import current_default_thread_limiter

        limiter = current_default_thread_limiter()
        components["fastapi_thread_pool"] = {
            "max_workers": limiter.total_tokens,
            "idle_workers": limiter.available_tokens,
            "busy_workers": limiter.total_tokens - limiter.available_tokens,
        }
    except Exception as e:
        components["fastapi_thread_pool"] = f"unknown ({e})"

    response_data = {"status": overall_status, "components": components}
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=response_data)
    return response_data


@router.get("/cluster")
async def cluster_status():
    """节点状态概览"""
    from backend.workers.collector_registry import get_enabled_collectors

    return {
        "mode": "standalone",
        "collectors": get_enabled_collectors(),
    }


# ==========================================
# --- MCP 探针 & Webhook ---
# ==========================================
@root_router.get("/mcp")
async def mcp_health_check(session_id: Optional[str] = None):
    """兼容 Uptime Kuma 等监控工具的 MCP 探针"""
    return {
        "status": "success",
        "message": "MCP endpoint is online",
        "session_id": session_id,
    }


@router.post("/webhook/uptime-kuma")
async def uptime_kuma_webhook(payload: dict):
    """接收 Uptime Kuma 的 Webhook 报警，触发前端全局通知"""
    monitor_name = payload.get("monitor", {}).get("name", "Unknown Service")
    status = payload.get("heartbeat", {}).get("status", 0)
    msg = payload.get("msg", "")

    if status == 0:
        alert_msg = f"🚨 [服务宕机报警] 核心系统离线: {monitor_name}\n详情: {msg}"
    else:
        alert_msg = f"✅ [服务恢复通知] 核心系统已重新上线: {monitor_name}"

    asyncio.create_task(notification_service.send_alert(alert_msg))
    return {"status": "success"}


# ==========================================
# --- 根路由 & 前端 SPA 代理 ---
# ==========================================
@root_router.get("/")
async def root():
    """默认根路由"""
    return {
        "status": "success",
        "message": "Quant Agent 主网关已启动。请访问 /docs 查看接口文档。",
    }


# 前端编译产物路径
_dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))


@root_router.get("/monitor")
async def monitor_page():
    """代理 React 编译后的入口 index.html"""
    html_path = os.path.join(_dist_dir, "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="前端编译文件不存在，请先执行 npm run build")
    return FileResponse(html_path)
