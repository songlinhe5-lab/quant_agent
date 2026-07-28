"""
系统健康检查 & 基础设施端点
从 main.py 迁出 (ARCH-01): health / cluster / metrics / monitor / webhook / root
"""

import asyncio
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

import prometheus_client
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text

from backend.core.database import async_engine
from backend.core.redis_client import redis_client
from backend.services.alert.notification import notification_service

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
# ==========================================
# ARCH-05: 分级健康检查 (liveness / readiness / deep)
# ==========================================
_START_TIME = time.monotonic()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _check_postgres() -> tuple[bool, str]:
    """轻量 PG 连通性探测：SELECT 1（异步引擎，非阻塞事件循环）"""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as e:  # noqa: BLE001
        return False, f"disconnected ({type(e).__name__}: {e})"


async def _check_data_sources() -> tuple[bool, dict[str, Any]]:
    """
    至少一个数据源连通：
    - 主行情网关 market_data.status == "CONNECTED"，或
    - 数据源注册表 (DataSourceRegistry) 中任一源 health().healthy == True
    返回 (ready, detail)
    """
    detail: dict[str, Any] = {}

    # 1) 主行情网关（Futu / 兼容壳）
    try:
        from backend.app.market_data import market_data

        ds_status = getattr(market_data, "status", "unknown")
        detail["market_gateway"] = ds_status
        if ds_status == "CONNECTED":
            return True, detail
    except Exception as e:  # noqa: BLE001
        detail["market_gateway"] = f"error ({e})"

    # 2) 通用数据源注册表（Futu/YFinance/AKShare/Finnhub 等）
    try:
        from backend.services.datasource import datasource_registry

        names = datasource_registry.list_names()
        detail["registered_sources"] = names
        for name in names:
            source = datasource_registry.get(name)
            if source is None:
                continue
            try:
                info = await asyncio.wait_for(source.health(), timeout=2.0)
                healthy = getattr(info, "healthy", False)
                detail[f"source:{name}"] = "healthy" if healthy else "unhealthy"
                if healthy:
                    return True, detail
            except Exception as e:  # noqa: BLE001
                detail[f"source:{name}"] = f"error ({e})"
    except Exception as e:  # noqa: BLE001
        detail["registry_error"] = str(e)

    return False, detail


async def _measure_event_loop_lag() -> float:
    """事件循环延迟（秒）：让出控制权后多久被重新调度，粗略反映事件循环拥塞度"""
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.sleep(0)
    return round(loop.time() - start, 6)


async def _collector_heartbeats() -> dict[str, Any]:
    """采集器心跳：本地已启用采集器 + 各注册数据源实时健康状态"""
    from backend.app.system_app import build_cluster_snapshot

    cluster = await build_cluster_snapshot()
    heartbeats: dict[str, Any] = {}
    try:
        from backend.services.datasource import datasource_registry

        for name in datasource_registry.list_names():
            source = datasource_registry.get(name)
            if source is None:
                continue
            try:
                info = await asyncio.wait_for(source.health(), timeout=2.0)
                heartbeats[name] = (
                    info.to_dict() if hasattr(info, "to_dict") else {"healthy": getattr(info, "healthy", False)}
                )
            except Exception as e:  # noqa: BLE001
                heartbeats[name] = {"healthy": False, "error": str(e)}
    except Exception:  # noqa: BLE001
        pass
    return {
        "mode": cluster.get("mode", "standalone"),
        "enabled_collectors": cluster.get("collectors", []),
        "data_source_heartbeats": heartbeats,
    }


@router.get("/health", summary="健康检查 (liveness - 始终 200)")
async def health_check():
    """
    主健康检查 (AGENTS §10.4)：只验证进程自身，不依赖任何外部依赖。
    即使所有数据源/Redis 不可用，只要进程能响应 HTTP 即返回 200 healthy，
    供 Docker/K8s liveness 探针使用。依赖就绪情况见 /health/ready，全链路诊断见 /health/deep。
    """
    return {
        "status": "healthy",
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "timestamp": _now_iso(),
    }


@router.get("/health/live", summary="存活探针 (liveness)")
async def health_live():
    """Liveness 探针：进程存活即 200，不依赖任何外部依赖（K8s livenessProbe）"""
    return {
        "status": "alive",
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "timestamp": _now_iso(),
    }


@router.get("/health/ready", summary="就绪探针 (readiness)")
async def health_ready(response: Response):
    """
    Readiness 探针：Redis + Postgres + 至少一个数据源连通才返回 200，
    否则返回 503（K8s readinessProbe：不就绪则不接流量）。
    """
    checks: dict[str, Any] = {}

    # Redis（核心基础设施：Pub/Sub + 缓存 + 限流）
    redis_ok = False
    try:
        await redis_client.ping()
        redis_ok = True
        checks["redis"] = "connected"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"disconnected ({e})"

    # Postgres（读写依赖）
    pg_ok, pg_msg = await _check_postgres()
    checks["postgres"] = pg_msg

    # 数据源（至少一个连通）
    ds_ok, ds_detail = await _check_data_sources()
    checks["data_sources"] = ds_detail

    # RL-11: 限流告警消费器健康（辅助探针，不计入 ready 门槛，避免阻断业务流量）
    try:
        from backend.services.datasource.alert_monitor import rate_limit_alert_monitor

        checks["alert_queue"] = "healthy" if rate_limit_alert_monitor.is_healthy() else "unhealthy"
    except Exception:  # noqa: BLE001
        checks["alert_queue"] = "unknown"

    ready = redis_ok and pg_ok and ds_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "timestamp": _now_iso(),
    }


@router.get("/health/deep", summary="全链路诊断 (deep)")
async def health_deep():
    """
    全链路诊断：组件健康 + PG + 数据源就绪 + 采集器心跳
    + WS 连接数 + 线程池使用率 + 事件循环 lag + 熔断器状态。
    """
    from backend.app.system_app import build_health_snapshot, build_metrics_snapshot

    component = await build_health_snapshot()
    metrics = build_metrics_snapshot()
    pg_ok, pg_msg = await _check_postgres()
    ds_ok, ds_detail = await _check_data_sources()
    collectors = await _collector_heartbeats()
    event_loop_lag = await _measure_event_loop_lag()

    # RL-11: 限流告警后台消费器健康探针（辅助组件，不阻断业务流量）
    # 暴露「后台告警队列是否真在跑」，防止 start() 静默失败无人知晓
    alert_monitor_detail = {"healthy": False, "started": False, "consumer_done": None}
    try:
        from backend.services.datasource.alert_monitor import rate_limit_alert_monitor

        alert_monitor_healthy = rate_limit_alert_monitor.is_healthy()
        alert_monitor_detail = {
            "healthy": alert_monitor_healthy,
            "started": rate_limit_alert_monitor._started,
            "consumer_done": (
                rate_limit_alert_monitor._consumer_task is not None and rate_limit_alert_monitor._consumer_task.done()
            ),
        }
    except Exception:  # noqa: BLE001
        alert_monitor_detail["error"] = "probe_failed"

    components = component.get("components", {})
    overall = "healthy"
    if not pg_ok or not ds_ok:
        overall = "degraded"
    elif component.get("status") == "unhealthy":
        overall = "degraded"

    return {
        "status": overall,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "timestamp": _now_iso(),
        "components": {
            "redis": components.get("redis"),
            "futu": components.get("futu"),
            "postgres": pg_msg,
            "data_sources_ready": ds_ok,
            "alert_queue": alert_monitor_detail,
        },
        "data_source_detail": ds_detail,
        "collectors": collectors,
        "websocket": {
            "active_connections": metrics.get("ws_connections"),
            "messages_sent": metrics.get("ws_messages_sent"),
            "messages_dropped": metrics.get("ws_messages_dropped"),
            "subscriptions": metrics.get("ws_subscriptions"),
        },
        "thread_pools": {
            "asyncio_default": components.get("asyncio_thread_pool"),
            "fastapi_anyio": components.get("fastapi_thread_pool"),
        },
        "redis_queue_depth": metrics.get("redis_queue_depth"),
        "circuit_breaker_states": metrics.get("circuit_breaker_states"),
        "event_loop_lag_seconds": event_loop_lag,
    }


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
