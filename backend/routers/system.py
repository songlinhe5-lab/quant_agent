"""
System APM 路由 — 系统性能监控与聚合仪表盘
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

from backend.core.database import SessionLocal
from backend.core.logger import logger
from backend.core.models import PerformanceLog
from backend.routers._grafana_dashboard import build_grafana_dashboard
from backend.routers.auth import get_current_user

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter(prefix="/system", tags=["system"])


async def _fetch_fmp_credit(daily_budget: int) -> dict:
    """经 HTTP 拉取 data_subservice /metrics，解析 FMP credit 指标。

    credit 权威值在子服务（_internal/fmp + prometheus metrics），主服务不再持有私有全局。
    子服务不可达时回退到主服务本地 collector_runtime() 估算值（仅展示用）。
    """
    import httpx

    url = os.getenv("FMP_REMOTE_URL", "http://localhost:8001").rstrip("/") + "/metrics"
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return {"error": f"子服务 /metrics HTTP {r.status_code}"}
        text = r.text
        # 解析 prometheus 文本：fmp_credit_spent_total / fmp_credit_remaining / fmp_credit_limit
        spent = _parse_prom_metric(text, "fmp_credit_spent_total")
        remaining = _parse_prom_metric(text, "fmp_credit_remaining")
        limit = _parse_prom_metric(text, "fmp_credit_limit")
        if spent is None and remaining is None:
            return {"error": "子服务 /metrics 未暴露 fmp_credit_* 指标"}
        eff_remaining = remaining if remaining is not None else max((limit or daily_budget) - (spent or 0), 0)
        eff_spent = spent if spent is not None else max((limit or daily_budget) - eff_remaining, 0)
        return {
            "spent_today": eff_spent,
            "prometheus_total": spent,
            "remaining": eff_remaining,
            "daily_budget": limit or daily_budget,
            "budget_used_rate": round(eff_spent / (limit or daily_budget), 4) if (limit or daily_budget) else None,
            "source": "data_subservice /metrics",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[System] 拉取子服务 FMP credit 失败，回退本地估算: {e}")
        from backend.workers.collectors.fmp import collector_runtime

        rt = collector_runtime()
        return {
            "spent_today": rt.get("credit_spent_today", 0),
            "remaining": max(daily_budget - rt.get("credit_spent_today", 0), 0),
            "daily_budget": daily_budget,
            "budget_used_rate": round(rt.get("credit_spent_today", 0) / daily_budget, 4) if daily_budget else None,
            "source": "local estimate (subservice unreachable)",
        }


def _parse_prom_metric(text: str, name: str) -> Optional[float]:
    """从 prometheus 文本中解析指定指标值（支持无 label 的 gauge/counter）。"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith(name + " ") or line.startswith(name + "{"):
            try:
                return float(line.split()[-1])
            except (ValueError, IndexError):
                return None
    return None


# ==========================================
#  0.1 可观测性总览（tick_cache + FMP credit 一页看板）
# ==========================================
@router.get("/observability")
async def get_observability(
    format: str = Query(default="json", description="json=即时快照 | grafana=导出 Grafana dashboard JSON"),
    username: str = Depends(get_current_user),
):
    """
    数据源实时价覆盖率 + FMP credit 消耗一页总览，供 APM 前端单页聚合。
    各指标同时暴露在 /metrics（Prometheus），本接口为前端即时快照。
    传 ?format=grafana 返回可直接导入 Grafana 的 dashboard JSON（前端亦可据此渲染面板）。
    """
    overview: dict[str, Any] = {}

    # 1. Finnhub WS 实时价命中/降级（BE-ARCH-07: 经推送平面统一入口）
    try:
        from backend.services.datasource.subscription import subscription_service

        overview["tick_cache"] = subscription_service.stats()
    except Exception as e:  # noqa: BLE001
        overview["tick_cache"] = {"error": str(e)}

    # 2. FMP collector credit 消耗（当日，含预算对账）+ 运行态
    # credit 权威值在 data_subservice /metrics (fmp_credit_*)，主服务经 HTTP 拉取，不再持有私有全局。
    try:
        from backend.workers.collectors.fmp import collector_runtime

        runtime = collector_runtime()
        daily_budget = int(os.environ.get("FMP_COLLECTOR_DAILY_CREDIT", "200"))

        # 解析子服务 /metrics 文本（prometheus 格式）
        credit = await _fetch_fmp_credit(daily_budget)
        overview["fmp_credit"] = credit
        overview["runtime"] = runtime
    except Exception as e:  # noqa: BLE001
        overview["fmp_credit"] = {"error": str(e)}
        overview["runtime"] = {"error": str(e)}

    if format == "grafana":
        return build_grafana_dashboard(overview)

    return {
        "status": "success",
        "message": "observability overview",
        "data": overview,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ==========================================
#  0. 数据质量看板（DQ-04 · SVC-04 汇总）
# ==========================================
@router.get("/data-quality")
async def get_data_quality(username: str = Depends(get_current_user)):
    """
    SVC-04 校验结果汇总：按数据源展示脏数据率 / 完整率 / 价格异常 / 过期计数。
    Grafana 独立面板订阅 Prometheus 同名指标；本接口供前端/运维即时查看。
    """
    from backend.services.data_quality.monitor import quality_overview

    return {
        "status": "success",
        "message": "data quality overview",
        "data": quality_overview(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "grafana": {
            "dashboard": "Data Quality (DQ-04)",
            "folder": "Quant Agent 监控",
            "metrics": [
                "quant_data_quality_dirty_rate",
                "quant_data_quality_completeness_rate",
                "quant_data_quality_price_anomaly_count",
                "quant_data_quality_stale_count",
            ],
        },
    }


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

            logs = query.order_by(PerformanceLog.timestamp.desc()).limit(limit).all()
            return [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
                    if log.timestamp
                    else "",
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
    - health / cluster / metrics / performance_stats
    """
    from backend.app.system_app import build_apm_dashboard

    data = await build_apm_dashboard()
    return {"status": "success", "data": data}


# ---- 兼容旧内部调用（转发至 system_app）----


async def _build_health_snapshot() -> dict:
    from backend.app.system_app import build_health_snapshot

    return await build_health_snapshot()


async def _build_cluster_snapshot() -> dict:
    from backend.app.system_app import build_cluster_snapshot

    return await build_cluster_snapshot()


def _build_metrics_snapshot() -> dict:
    from backend.app.system_app import build_metrics_snapshot

    return build_metrics_snapshot()


async def _build_perf_stats() -> dict:
    from backend.app.system_app import build_perf_stats

    return await build_perf_stats()
