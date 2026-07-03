"""
System APM 路由 — 系统性能监控与聚合仪表盘
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

from backend.core.database import SessionLocal
from backend.core.models import PerformanceLog
from backend.core.redis_client import redis_client
from backend.core.logger import logger
from backend.routers.auth import get_current_user

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter(prefix="/system", tags=["system"])


# ==========================================
#  1. 性能日志列表（带筛选 + 分页）
# ==========================================
@router.get("/performance-logs")
async def get_performance_logs(
    limit: int = Query(100, le=500, description="返回条数上限"),
    log_type: Optional[str] = Query(None, description="按类型筛选: slow_request / event_loop_block"),
    since: Optional[str] = Query(None, description="ISO 时间戳，只返回此时间之后的日志"),
    username: str = Depends(get_current_user),
):
    """获取系统性能监控日志（慢请求与事件循环卡顿）"""

    def fetch_logs():
        with SessionLocal() as db:
            query = db.query(PerformanceLog)

            if log_type:
                query = query.filter(PerformanceLog.log_type == log_type)

            if since:
                try:
                    since_dt = datetime.fromisoformat(since)
                    query = query.filter(PerformanceLog.timestamp >= since_dt)
                except ValueError:
                    pass  # 忽略无效时间格式

            logs = (
                query.order_by(PerformanceLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
                    "log_type": log.log_type,
                    "duration_ms": log.duration_ms,
                    "endpoint": log.endpoint,
                    "details": log.details,
                }
                for log in logs
            ]

    try:
        data = await asyncio.to_thread(fetch_logs)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error("获取性能日志失败: %s", e)
        raise


# ==========================================
#  2. 性能统计聚合（24h）
# ==========================================
@router.get("/performance-stats")
async def get_performance_stats(
    hours: int = Query(24, le=168, description="统计时间窗口（小时）"),
    username: str = Depends(get_current_user),
):
    """返回指定时间窗口内的性能聚合统计"""

    def fetch_stats():
        since_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        with SessionLocal() as db:
            rows = (
                db.query(
                    PerformanceLog.log_type,
                    func.count(PerformanceLog.id).label("cnt"),
                    func.avg(PerformanceLog.duration_ms).label("avg_ms"),
                    func.max(PerformanceLog.duration_ms).label("max_ms"),
                )
                .filter(PerformanceLog.timestamp >= since_dt)
                .group_by(PerformanceLog.log_type)
                .all()
            )

            stats = {
                "slow_request_count": 0,
                "event_loop_block_count": 0,
                "avg_duration_ms": 0.0,
                "max_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
                "total_count": 0,
            }

            all_durations: list[float] = []
            for row in rows:
                stats["total_count"] += row.cnt
                if row.log_type == "slow_request":
                    stats["slow_request_count"] = row.cnt
                elif row.log_type == "event_loop_block":
                    stats["event_loop_block_count"] = row.cnt
                if row.avg_ms is not None:
                    all_durations.extend([row.avg_ms] * row.cnt)
                if row.max_ms is not None and row.max_ms > stats["max_duration_ms"]:
                    stats["max_duration_ms"] = row.max_ms

            if all_durations:
                stats["avg_duration_ms"] = round(sum(all_durations) / len(all_durations), 2)
                sorted_d = sorted(all_durations)
                p95_idx = int(len(sorted_d) * 0.95)
                stats["p95_duration_ms"] = round(sorted_d[min(p95_idx, len(sorted_d) - 1)], 2)

            return stats

    try:
        data = await asyncio.to_thread(fetch_stats)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error("获取性能统计失败: %s", e)
        raise


# ==========================================
#  3. APM 聚合仪表盘
# ==========================================
@router.get("/apm-dashboard")
async def apm_dashboard(username: str = Depends(get_current_user)):
    """
    一次请求返回 APM 面板所需的全部数据：
    - health: 组件健康状态
    - cluster: 集群拓扑
    - metrics: Prometheus 指标快照
    - performance_stats: 24h 性能统计
    """
    health_data = await _build_health_snapshot()
    cluster_data = await _build_cluster_snapshot()
    metrics_data = _build_metrics_snapshot()
    perf_stats = await _build_perf_stats()

    return {
        "status": "success",
        "data": {
            "health": health_data,
            "cluster": cluster_data,
            "metrics": metrics_data,
            "performance_stats": perf_stats,
        },
    }


# ---- 内部辅助函数 ----

async def _build_health_snapshot() -> dict:
    """复用 health_check 逻辑，返回组件状态"""
    components: dict = {}
    overall = "healthy"

    try:
        await redis_client.ping()
        components["redis"] = "connected"
    except Exception as e:
        components["redis"] = f"disconnected ({e})"
        overall = "unhealthy"

    try:
        from backend.services.futu import futu_service
        components["futu"] = futu_service.status
        if futu_service.status != "CONNECTED" and overall == "healthy":
            overall = "degraded"
    except Exception:
        components["futu"] = "unknown"

    components["yfinance"] = "skipped (prevent rate limits)"

    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None and hasattr(executor, "_max_workers"):
        components["asyncio_thread_pool"] = {
            "max_workers": executor._max_workers,
            "spawned_threads": len(executor._threads),
            "pending_tasks": executor._work_queue.qsize(),
        }
    else:
        components["asyncio_thread_pool"] = "idle"

    try:
        from anyio.to_thread import current_default_thread_limiter
        limiter = current_default_thread_limiter()
        components["fastapi_thread_pool"] = {
            "max_workers": limiter.total_tokens,
            "idle_workers": limiter.available_tokens,
            "busy_workers": limiter.total_tokens - limiter.available_tokens,
        }
    except Exception:
        components["fastapi_thread_pool"] = "unknown"

    return {"status": overall, "components": components}


async def _build_cluster_snapshot() -> dict:
    """复用 cluster_manager 逻辑"""
    try:
        from backend.workers.cluster_manager import cluster_manager
        return cluster_manager.get_cluster_status()
    except Exception as e:
        return {"error": str(e), "master": {"collectors": []}, "slaves": [], "pools": {}}


def _build_metrics_snapshot() -> dict:
    """从 Prometheus registry 读取关键指标快照"""
    try:
        from backend.core.metrics import (
            WS_ACTIVE_CONNECTIONS,
            WS_MESSAGES_SENT,
            WS_MESSAGES_DROPPED,
            WS_SUBSCRIPTIONS,
            REDIS_QUEUE_DEPTH,
            CIRCUIT_BREAKER_STATE,
            MARKET_QUOTE_TOTAL,
        )

        def _gauge_val(metric):
            try:
                # 取所有 label 组合中的第一个值
                samples = metric.collect()[0].samples
                for s in samples:
                    if s.name.endswith("_total") or not s.name.endswith("_created"):
                        return s.value
                return 0
            except Exception:
                return 0

        def _counter_val(metric):
            try:
                total = 0
                for s in metric.collect()[0].samples:
                    if s.name.endswith("_total"):
                        total += s.value
                return int(total)
            except Exception:
                return 0

        # Redis 队列深度 — 按 queue label 分组
        redis_depth: dict = {}
        try:
            for sample in REDIS_QUEUE_DEPTH.collect()[0].samples:
                if "queue" in sample.labels:
                    redis_depth[sample.labels["queue"]] = sample.value
        except Exception:
            pass

        # 熔断器状态 — 按 service label 分组
        cb_states: dict = {}
        try:
            for sample in CIRCUIT_BREAKER_STATE.collect()[0].samples:
                if "service" in sample.labels:
                    cb_states[sample.labels["service"]] = int(sample.value)
        except Exception:
            pass

        return {
            "ws_connections": _gauge_val(WS_ACTIVE_CONNECTIONS),
            "ws_messages_sent": _counter_val(WS_MESSAGES_SENT),
            "ws_messages_dropped": _counter_val(WS_MESSAGES_DROPPED),
            "ws_subscriptions": _gauge_val(WS_SUBSCRIPTIONS),
            "redis_queue_depth": redis_depth,
            "circuit_breaker_states": cb_states,
            "market_quote_total": _counter_val(MARKET_QUOTE_TOTAL),
        }
    except Exception as e:
        logger.warning("读取 Prometheus 指标快照失败: %s", e)
        return {}


async def _build_perf_stats() -> dict:
    """24h 性能统计"""
    try:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

        def fetch():
            with SessionLocal() as db:
                rows = (
                    db.query(
                        PerformanceLog.log_type,
                        func.count(PerformanceLog.id).label("cnt"),
                        func.avg(PerformanceLog.duration_ms).label("avg_ms"),
                        func.max(PerformanceLog.duration_ms).label("max_ms"),
                    )
                    .filter(PerformanceLog.timestamp >= since_dt)
                    .group_by(PerformanceLog.log_type)
                    .all()
                )
                return rows

        rows = await asyncio.to_thread(fetch)

        result = {
            "slow_request_count": 0,
            "event_loop_block_count": 0,
            "avg_duration_ms": 0.0,
            "max_duration_ms": 0.0,
            "total_count": 0,
        }
        all_durations: list[float] = []
        for row in rows:
            result["total_count"] += row.cnt
            if row.log_type == "slow_request":
                result["slow_request_count"] = row.cnt
            elif row.log_type == "event_loop_block":
                result["event_loop_block_count"] = row.cnt
            if row.avg_ms is not None:
                all_durations.extend([row.avg_ms] * row.cnt)
            if row.max_ms is not None and row.max_ms > result["max_duration_ms"]:
                result["max_duration_ms"] = row.max_ms

        if all_durations:
            result["avg_duration_ms"] = round(sum(all_durations) / len(all_durations), 2)

        return result
    except Exception as e:
        logger.warning("获取性能统计失败: %s", e)
        return {"slow_request_count": 0, "event_loop_block_count": 0, "avg_duration_ms": 0.0, "max_duration_ms": 0.0, "total_count": 0}
