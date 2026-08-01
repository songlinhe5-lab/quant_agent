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
from backend.routers.auth import get_current_user

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter(prefix="/system", tags=["system"])


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

    # 1. Finnhub WS 实时价命中/降级
    try:
        from backend.services.finnhub.ws_ingest import tick_cache_stats

        overview["tick_cache"] = tick_cache_stats()
    except Exception as e:  # noqa: BLE001
        overview["tick_cache"] = {"error": str(e)}

    # 2. FMP collector credit 消耗（当日，含预算对账）+ 运行态
    try:
        from backend.core.metrics import FMP_CREDIT_SPENT_TOTAL
        from backend.workers.collectors.fmp import _credit_spent_today, collector_runtime

        daily_budget = int(os.environ.get("FMP_COLLECTOR_DAILY_CREDIT", "200"))
        prom_value = FMP_CREDIT_SPENT_TOTAL._value.get()  # noqa: SLF001 非公开属性，监控读值专用
        runtime = collector_runtime()
        overview["fmp_credit"] = {
            "spent_today": _credit_spent_today,
            "prometheus_total": prom_value,
            "daily_budget": daily_budget,
            "remaining": max(daily_budget - _credit_spent_today, 0),
            "budget_used_rate": round(_credit_spent_today / daily_budget, 4) if daily_budget else None,
        }
        overview["runtime"] = runtime
    except Exception as e:  # noqa: BLE001
        overview["fmp_credit"] = {"error": str(e)}
        overview["runtime"] = {"error": str(e)}

    if format == "grafana":
        return _build_grafana_dashboard(overview)

    return {
        "status": "success",
        "message": "observability overview",
        "data": overview,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _build_grafana_dashboard(overview: dict[str, Any]) -> dict[str, Any]:
    """生成可直接导入 Grafana 的 dashboard JSON（Prometheus datasource 从 /metrics 拉）。

    - Panel 1: tick_cache 命中率 Gauge（quant_tick_cache_hit_rate）
    - Panel 2: credit 预算进度 Bar（当日 spent vs budget）
    """
    budget = (overview.get("fmp_credit") or {}).get("daily_budget", 200)
    return {
        "title": "Quant Agent - 数据源可观测性",
        "uid": "quant-observability",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "panels": [
            {
                "id": 1,
                "title": "Finnhub WS 实时价命中率",
                "type": "gauge",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                "targets": [
                    {
                        "expr": "quant_tick_cache_hit_rate",
                        "legendFormat": "hit_rate",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "min": 0,
                        "max": 1,
                        "unit": "percentunit",
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": 0},
                                {"color": "yellow", "value": 0.5},
                                {"color": "green", "value": 0.8},
                            ]
                        },
                    }
                },
            },
            {
                "id": 2,
                "title": "FMP 每日 credit 预算消耗",
                "type": "bargauge",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_credit_spent_total",
                        "legendFormat": "spent",
                        "refId": "A",
                    }
                ],
                "options": {
                    "displayMode": "gradient",
                    "max": budget,
                },
                "fieldConfig": {
                    "defaults": {
                        "min": 0,
                        "max": budget,
                        "unit": "short",
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "yellow", "value": budget * 0.8},
                                {"color": "red", "value": budget},
                            ]
                        },
                    }
                },
            },
            {
                "id": 3,
                "title": "tick_cache 命中速率 (hits/s)",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                "targets": [
                    {
                        "expr": "rate(quant_tick_cache_hits_total[5m])",
                        "legendFormat": "hits/s",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "ops",
                        "color": {"mode": "palette-classic"},
                    }
                },
            },
            {
                "id": 4,
                "title": "tick_cache 降级速率 (miss/s) · WS断流信号",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                "targets": [
                    {
                        "expr": "rate(quant_tick_cache_misses_total[5m])",
                        "legendFormat": "miss/s",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "ops",
                        "color": {"mode": "palette-classic"},
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "red", "value": 0.01},
                            ]
                        },
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 4,
                    "name": "FMP-WS 断流：tick_cache miss 速率持续 2m 超阈值",
                    "frequency": "1m",
                    "for": "2m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "5m", "now"]},
                            "evaluator": {"type": "gt", "params": [0.01]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "Finnhub WS 实时价降级速率持续 2 分钟 > 0.01/s，疑似 WS 断流",
                        "description": "rate(quant_tick_cache_misses_total[5m]) > 0.01 持续 2m，实时价覆盖率下降，quote 已降级 REST 快照。",
                    },
                    "labels": {"severity": "critical", "service": "quant-agent"},
                },
            },
            {
                "id": 5,
                "title": "FMP Collector 守护状态",
                "type": "stat",
                "gridPos": {"h": 8, "w": 24, "x": 0, "y": 16},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_paused",
                        "legendFormat": "paused",
                        "refId": "A",
                    }
                ],
                "options": {
                    "reduceOptions": {"calcs": ["lastNotNull"]},
                    "colorMode": "background",
                    "graphMode": "none",
                    "justifyMode": "auto",
                    "values": True,
                },
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "mappings": [
                            {"type": "value", "options": {"0": {"text": "运行中", "color": "green"}}},
                            {"type": "value", "options": {"1": {"text": "已暂停·Redis故障自愈中", "color": "red"}}},
                        ],
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "red", "value": 1},
                            ]
                        },
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 5,
                    "name": "FMP Collector 守护暂停（Redis 故障自愈中）",
                    "frequency": "1m",
                    "for": "2m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "5m", "now"]},
                            "evaluator": {"type": "gt", "params": [0]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP collector 守护已暂停（Redis 持久化连续失败），credit 进度停止持久化，30s 自愈轮询待恢复",
                        "description": "quant_fmp_collector_paused == 1 持续 2m，守护处于暂停态，待 Redis 恢复后自愈重启。",
                    },
                    "labels": {"severity": "critical", "service": "quant-agent"},
                },
            },
            {
                "id": 6,
                "title": "FMP Redis 持久化连续失败数 + PING 延迟分位 (Redis 稳定性)",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 24, "x": 0, "y": 24},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_persist_fails",
                        "legendFormat": "persist_fails",
                        "refId": "A",
                        "dataLinks": [
                            {
                                "title": "下钻：聚焦此处时间窗看延迟/P95/P99",
                                "url": "/d/quant-observability/quant-observability?orgId=1&from=${__value.time}&to=${__value.time}&var-DS_PROMETHEUS=${DS_PROMETHEUS}",
                                "targetBlank": False,
                            }
                        ],
                    },
                    {
                        "expr": "quant_fmp_collector_redis_ping_latency_seconds",
                        "legendFormat": "redis_ping_latency_s (即时)",
                        "refId": "B",
                    },
                    {
                        "expr": "histogram_quantile(0.95, sum(rate(quant_fmp_collector_redis_ping_latency_seconds_hist_bucket[$__range])) by (le))",
                        "legendFormat": "P95 延迟",
                        "refId": "C",
                    },
                    {
                        "expr": "histogram_quantile(0.99, sum(rate(quant_fmp_collector_redis_ping_latency_seconds_hist_bucket[$__range])) by (le))",
                        "legendFormat": "P99 延迟",
                        "refId": "D",
                    },
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "color": {"mode": "thresholds"},
                        "min": 0,
                        "custom": {"lineWidth": 2, "axisPlacement": "auto"},
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "yellow", "value": 0.1},
                                {"color": "red", "value": 0.5},
                            ]
                        },
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 6,
                    "name": "FMP Redis 持久化连续失败逼近阈值",
                    "frequency": "1m",
                    "for": "2m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "5m", "now"]},
                            "evaluator": {"type": "gte", "params": [3]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP Redis 持久化连续失败数 ≥ 3，Redis 稳定性恶化，逼近暂停阈值 5",
                        "description": "quant_fmp_collector_persist_fails >= 3 持续 2m，需警惕 Redis 连接质量，避免守护暂停。",
                    },
                    "labels": {"severity": "warning", "service": "quant-agent"},
                },
            },
            {
                "id": 7,
                "title": "FMP 自愈退避倒计时 (下次探测间隔)",
                "type": "timeseries",
                "gridPos": {"h": 8, "w": 24, "x": 0, "y": 32},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_heal_backoff_seconds",
                        "legendFormat": "heal_backoff_s",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "color": {"mode": "thresholds"},
                        "min": 0,
                        "custom": {"lineWidth": 2},
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "yellow", "value": 30},
                                {"color": "red", "value": 300},
                            ]
                        },
                    }
                },
            },
        ],
        "annotations": {"list": []},
        "templating": {
            "list": [
                {
                    "name": "DS_PROMETHEUS",
                    "type": "datasource",
                    "label": "Prometheus 数据源",
                    "query": "prometheus",
                    "current": {"text": "prometheus", "value": "prometheus"},
                    "hide": 0,
                }
            ]
        },
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
