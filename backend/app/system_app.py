"""
系统 APM 用例（BE-ARCH-02）

聚合 health / cluster / Prometheus / 24h 性能统计，供 APM Dashboard。
`/api/v1/health` 仍保持 composition-root 薄实现（AGENTS §10.4）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from backend.core.database import SessionLocal
from backend.core.logger import logger
from backend.core.models import PerformanceLog
from backend.core.redis_client import redis_client


async def build_health_snapshot() -> dict[str, Any]:
    components: dict[str, Any] = {}
    overall = "healthy"

    try:
        await redis_client.ping()
        components["redis"] = "connected"
    except Exception as e:
        components["redis"] = f"disconnected ({e})"
        overall = "unhealthy"

    try:
        from backend.app.market_data import market_data

        components["futu"] = market_data.status
        if market_data.status != "CONNECTED" and overall == "healthy":
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


async def build_cluster_snapshot() -> dict[str, Any]:
    from backend.workers.collector_registry import get_enabled_collectors

    return {
        "mode": "standalone",
        "collectors": get_enabled_collectors(),
    }


def build_metrics_snapshot() -> dict[str, Any]:
    try:
        from backend.core.metrics import (
            CIRCUIT_BREAKER_STATE,
            MARKET_QUOTE_TOTAL,
            REDIS_QUEUE_DEPTH,
            WS_ACTIVE_CONNECTIONS,
            WS_MESSAGES_DROPPED,
            WS_MESSAGES_SENT,
            WS_SUBSCRIPTIONS,
        )

        def _gauge_val(metric: Any) -> float:
            try:
                samples = metric.collect()[0].samples
                for s in samples:
                    if s.name.endswith("_total") or not s.name.endswith("_created"):
                        return s.value
                return 0
            except Exception:
                return 0

        def _counter_val(metric: Any) -> int:
            try:
                total = 0
                for s in metric.collect()[0].samples:
                    if s.name.endswith("_total"):
                        total += s.value
                return int(total)
            except Exception:
                return 0

        redis_depth: dict[str, Any] = {}
        try:
            for sample in REDIS_QUEUE_DEPTH.collect()[0].samples:
                if "queue" in sample.labels:
                    redis_depth[sample.labels["queue"]] = sample.value
        except Exception:
            pass

        cb_states: dict[str, Any] = {}
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


async def build_perf_stats() -> dict[str, Any]:
    try:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

        def fetch() -> Any:
            with SessionLocal() as db:
                return (
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

        rows = await asyncio.to_thread(fetch)
        result: dict[str, Any] = {
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
        return {
            "slow_request_count": 0,
            "event_loop_block_count": 0,
            "avg_duration_ms": 0.0,
            "max_duration_ms": 0.0,
            "total_count": 0,
        }


async def build_apm_dashboard() -> dict[str, Any]:
    """一次聚合 APM 面板所需全部数据。"""
    health_data = await build_health_snapshot()
    cluster_data = await build_cluster_snapshot()
    metrics_data = build_metrics_snapshot()
    perf_stats = await build_perf_stats()
    return {
        "health": health_data,
        "cluster": cluster_data,
        "metrics": metrics_data,
        "performance_stats": perf_stats,
    }
