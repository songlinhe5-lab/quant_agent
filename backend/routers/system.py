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

    # 1. Finnhub WS 实时价命中/降级
    try:
        from backend.services.finnhub.ws_ingest import tick_cache_stats

        overview["tick_cache"] = tick_cache_stats()
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
                    {
                        "expr": "quant_fmp_collector_heal_p99_seconds",
                        "legendFormat": "滑动窗口P99(后端估算·交叉校验)",
                        "refId": "E",
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
                        "dataLinks": [
                            {
                                "title": "反向联动：跳失败数+延迟联合视图",
                                "url": "/d/quant-observability/quant-observability?orgId=1&from=${__value.time}&to=${__value.time}&var-DS_PROMETHEUS=${DS_PROMETHEUS}",
                                "targetBlank": False,
                            }
                        ],
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
            {
                "id": 8,
                "title": "FMP Redis P99 延迟智能告警 (>0.5s 持续 5m)",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 40},
                "hidden": False,
                "targets": [
                    {
                        "expr": "histogram_quantile(0.99, sum(rate(quant_fmp_collector_redis_ping_latency_seconds_hist_bucket[$__range])) by (le))",
                        "legendFormat": "P99 延迟",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "color": {"mode": "thresholds"},
                        "min": 0,
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
                    "id": 8,
                    "name": "FMP Redis P99 延迟持续劣化 (>0.5s 达 5m)",
                    "frequency": "1m",
                    "for": "5m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "5m", "now"]},
                            "evaluator": {"type": "gt", "params": [0.5]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP Redis P99 延迟 > 0.5s 持续 5 分钟，判定为持续劣化（非偶发毛刺），Redis 性能或网络链路恶化",
                        "description": "histogram_quantile(0.99, ...) > 0.5s 持续 5m 才触发，单点毛刺因 for:5m 自动过滤，劣化必报。注：后端 _self_heal_loop 另有 Python 侧动态归因告警（P1），触发时附同窗 persist_fails 与 PING P99，自动区分网络抖 vs 写链路慢；本 Panel 告警为该能力在 Grafana 的可视化冗余。退避天花板由 FMP_HEAL_BACKOFF_CAP env 控制（默认 300s，对应 HEAL_BACKOFF_CAP 变量）。",
                    },
                    "labels": {"severity": "critical", "service": "quant-agent"},
                },
            },
            {
                "id": 9,
                "title": "FMP Redis 网络抖瞬态失败数 (不触发暂停)",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 46},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_persist_jitter_fails",
                        "legendFormat": "jitter_fails (毛刺·不暂停)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "thresholds"},
                        "min": 0,
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "yellow", "value": 1},
                                {"color": "orange", "value": 10},
                            ]
                        },
                    }
                },
            },
            {
                "id": 10,
                "title": "FMP 归因信号 (lat_degraded: 写链路慢=1 / 网络抖=0)",
                "type": "stat",
                "gridPos": {"h": 6, "w": 12, "x": 0, "y": 52},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_lat_degraded",
                        "legendFormat": "lat_degraded",
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
                            {"type": "value", "options": {"0": {"text": "网络抖窗口(不暂停)", "color": "green"}}},
                            {"type": "value", "options": {"1": {"text": "写链路慢(可暂停)", "color": "red"}}},
                        ],
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": 0},
                                {"color": "red", "value": 1},
                            ]
                        },
                    }
                },
            },
            {
                "id": 11,
                "title": "FMP 归因全貌联动 (degraded / paused / jitter 同窗)",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 12, "x": 12, "y": 52},
                "targets": [
                    {"expr": "quant_fmp_collector_lat_degraded", "legendFormat": "lat_degraded", "refId": "A"},
                    {"expr": "quant_fmp_collector_paused", "legendFormat": "paused", "refId": "B"},
                    {
                        "expr": "quant_fmp_collector_persist_jitter_fails",
                        "legendFormat": "jitter_fails",
                        "refId": "C",
                    },
                ],
                "fieldConfig": {"defaults": {"unit": "short", "color": {"mode": "thresholds"}, "min": 0}},
            },
            {
                "id": 12,
                "title": "抖动重试挽回 (累计 + 每小时速率)",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 58},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_jitter_retry_recovered_total",
                        "legendFormat": "retry_recovered (累计)",
                        "refId": "A",
                    },
                    {
                        "expr": "rate(quant_fmp_collector_jitter_retry_recovered_total[1h]) * 3600",
                        "legendFormat": "retry_recovered_每小时",
                        "refId": "B",
                    },
                ],
                "options": {
                    "reduceOptions": {"calcs": ["lastNotNull"]},
                    "colorMode": "value",
                    "graphMode": "area",
                    "justifyMode": "auto",
                    "values": True,
                },
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "steps": [
                                {"color": "gray", "value": 0},
                                {"color": "green", "value": 1},
                            ]
                        },
                    }
                },
            },
            {
                "id": 13,
                "title": "抖动重试成功率 (recovered速率 / jitter失败速率)",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 64},
                "targets": [
                    {
                        "expr": "rate(quant_fmp_collector_jitter_retry_recovered_total[1h]) / clamp_min(rate(quant_fmp_collector_persist_jitter_fails[1h]), 0.0001)",
                        "legendFormat": "重试成功率 (挽回/抖动失败)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "percentunit",
                        "color": {"mode": "thresholds"},
                        "min": 0,
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": 0},
                                {"color": "yellow", "value": 0.5},
                                {"color": "green", "value": 0.8},
                            ]
                        },
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 13,
                    "name": "FMP 抖动重试性价比低 (成功率<50% 持续 10m)",
                    "frequency": "1m",
                    "for": "10m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "10m", "now"]},
                            "evaluator": {"type": "lt", "params": [0.5]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP 抖动重试成功率 < 50% 持续 10 分钟，重试性价比低，建议下调 FMP_JITTER_RETRY",
                        "description": "rate(recovered[1h]) / rate(jitter_fails[1h]) < 0.5 持续 10m，说明 Redis 抖动顽固、重试难救，建议降配重试次数（控制器会自动下调，本告警用于人工复核）。",
                    },
                    "labels": {"severity": "warning", "service": "quant-agent"},
                },
            },
            {
                "id": 14,
                "title": "抖动重试次数自适应轨迹 (控制器生效值) · 与成功率拐点对照",
                "type": "timeseries",
                "gridPos": {"h": 6, "w": 24, "x": 0, "y": 70},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_jitter_retry_active",
                        "legendFormat": "当前生效 FMP_JITTER_RETRY (自适应)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "thresholds"},
                        "min": 1,
                        "thresholds": {
                            "steps": [
                                {"color": "#64748b", "value": 1},
                                {"color": "#f59e0b", "value": 4},
                                {"color": "#10b981", "value": 6},
                            ]
                        },
                    }
                },
            },
            {
                "id": 15,
                "title": "FMP watchlist 为空告警 (静默兜底)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 0, "y": 76},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_watchlist_empty",
                        "legendFormat": "watchlist 空 (1=静默兜底未拉财报)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "background"},
                        "thresholds": {
                            "steps": [
                                {"color": "#10b981", "value": 0},
                                {"color": "#ef4444", "value": 1},
                            ]
                        },
                    }
                },
                "dataLinks": [
                    {
                        "title": "反向联动：跳 watchlist 标的池大小，确认是配置遗漏(size=0)还是文件读取失败",
                        "type": "link",
                        "url": "${__url_time_range}&viewPanel=16",
                        "internal": {"datasourceUid": "${DS_PROMETHEUS}", "query": {"queryType": "timeseries"}},
                    }
                ],
                "alertThreshold": True,
                "alert": {
                    "id": 15,
                    "name": "FMP watchlist 为空 (所有标的源未配置)",
                    "frequency": "1m",
                    "for": "5m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "5m", "now"]},
                            "evaluator": {"type": "eq", "params": [1]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP watchlist 为空持续 5 分钟，守护静默兜底未拉取任何财报",
                        "description": "FMP_COLLECTOR_SYMBOLS / PORTFOLIO_SYMBOLS / WATCHLIST / FINNHUB_WS_SYMBOLS 均未配置任何标的源，盘后守护不会拉任何财报（硬默认 4 只已废弃）。需配置至少一个源，否则财报缓存为空。",
                    },
                    "labels": {"severity": "critical", "service": "quant-agent"},
                },
            },
            {
                "id": 16,
                "title": "FMP watchlist 标的池大小 (多源并集)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 8, "y": 76},
                "targets": [
                    {
                        "expr": "quant_fmp_collector_watchlist_size",
                        "legendFormat": "当前生效标的池大小 (个)",
                        "refId": "A",
                    },
                    {
                        "expr": "increase(quant_fmp_collector_watchlist_size_shift_total[1h])",
                        "legendFormat": "近1h标的池突变次数 (±50%)",
                        "refId": "B",
                    },
                    {
                        "expr": "increase(quant_fmp_collector_watchlist_file_deleted_total[1h])",
                        "legendFormat": "近1h文件被删除次数 (根因:删文件)",
                        "refId": "C",
                    },
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "background"},
                        "thresholds": {
                            "steps": [
                                {"color": "#ef4444", "value": 0},
                                {"color": "#64748b", "value": 1},
                                {"color": "#10b981", "value": 5},
                            ]
                        },
                    }
                },
                "dataLinks": [
                    {
                        "title": "反向联动：跳回空告警 Panel，确认 size 突变是否引发静默兜底",
                        "type": "link",
                        "url": "${__url_time_range}&viewPanel=15",
                        "internal": {"datasourceUid": "${DS_PROMETHEUS}", "query": {"queryType": "timeseries"}},
                    }
                ],
                "alertThreshold": True,
                "alert": {
                    "id": 16,
                    "name": "FMP watchlist 标的池突变 (±50% 提示调仓异常/文件误删)",
                    "frequency": "1m",
                    "for": "0m",
                    "noDataState": "no_data",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["B", "1h", "now"]},
                            "evaluator": {"type": "gt", "params": [0]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP watchlist 标的池短时发生 ±50% 突变",
                        "description": "近 1h 内 watchlist 标的池大小相对上一轮变化超过 ±50%（FMP_WATCHLIST_SIZE_SHIFT 计数 >0），提示账户调仓异常、文件误删或 stale 池重置。可点 Panel 反向联动跳回 Panel 15 确认是否连带触发空告警。",
                    },
                    "labels": {"severity": "warning", "service": "quant-agent"},
                },
            },
            {
                "id": 17,
                "title": "突变根因比率 (删文件占比 = 误操作频率)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 16, "y": 76},
                "targets": [
                    {
                        "expr": "increase(quant_fmp_collector_watchlist_file_deleted_total[1h]) / (increase(quant_fmp_collector_watchlist_file_deleted_total[1h]) + increase(quant_fmp_collector_watchlist_size_shift_total[1h]))",
                        "legendFormat": "突变中删文件导致占比 (0=纯调仓, 1=纯误删, N/A=近1h无突变)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "percentunit",
                        "noValue": "N/A",
                        "color": {"mode": "background"},
                        "thresholds": {
                            "steps": [
                                {"color": "#10b981", "value": 0},
                                {"color": "#f59e0b", "value": 0.3},
                                {"color": "#ef4444", "value": 0.7},
                            ]
                        },
                        "min": 0,
                        "max": 1,
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 17,
                    "name": "FMP watchlist 突变主要由文件误删导致 (误操作频率偏高)",
                    "frequency": "5m",
                    "for": "15m",
                    "noDataState": "ok",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "1h", "now"]},
                            "evaluator": {"type": "gt", "params": [0.7]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "FMP watchlist 突变中删文件占比 > 70%",
                        "description": "近 1h 内 watchlist 突变事件主要由监听文件被删除触发（file_deleted / (file_deleted + size_shift) > 0.7），提示运维误操作（误删 portfolio/watchlist 文件）频率偏高，应排查文件管理流程而非账户调仓。",
                    },
                    "labels": {"severity": "warning", "service": "quant-agent"},
                },
            },
            {
                "id": 18,
                "title": "FMP watchlist Counter 失真兜底告警 (Gauge变但shift无增量)",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 0, "y": 80},
                "targets": [
                    {
                        "expr": "((changes(quant_fmp_collector_watchlist_size[1h]) >= 2) and (increase(quant_fmp_collector_watchlist_size_shift_total[1h]) == 0)) == 1",
                        "legendFormat": "Counter重启归零失真标志 (1=Gauge变但shift无增量)",
                        "refId": "A",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "short",
                        "color": {"mode": "background"},
                        "thresholds": {
                            "steps": [
                                {"color": "#10b981", "value": 0},
                                {"color": "#ef4444", "value": 1},
                            ]
                        },
                        "min": 0,
                        "max": 1,
                    }
                },
                "alertThreshold": True,
                "alert": {
                    "id": 18,
                    "name": "FMP watchlist size 变化但 shift Counter 无增量 (Counter 可能重启归零)",
                    "frequency": "5m",
                    "for": "5m",
                    "noDataState": "ok",
                    "execErrState": "alerting",
                    "conditions": [
                        {
                            "type": "query",
                            "reducerType": "last",
                            "query": {"params": ["A", "1h", "now"]},
                            "evaluator": {"type": "gt", "params": [0]},
                            "operator": {"type": "and"},
                        }
                    ],
                    "annotations": {
                        "summary": "watchlist size Gauge 近 1h 有变化但 shift Counter 无增量",
                        "description": "quant_fmp_collector_watchlist_size 在近 1h 至少发生 2 次变更（changes>=2，过滤热重载重复 set 同值的单次抖动误报），但 FMP_WATCHLIST_SIZE_SHIFT Counter 的 increase 为 0，提示 exporter 进程可能重启导致 Counter 归零，Panel 16/17 的比率与突变计数已失真。按主脑权衡：保留 Counter 直查 + 本 Panel 兜底组合，不切 Gauge delta（单副本 simplicity 优先）。应改用 recording rule 的 Gauge 派生 delta（fmp:watchlist_size_delta5m）或检查 exporter 健康。",
                    },
                    "labels": {"severity": "warning", "service": "quant-agent"},
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
                },
                {
                    "name": "HEAL_BACKOFF_CAP",
                    "type": "text",
                    "label": "自愈退避天花板(秒, 仅展示锚点 · 生效见 FMP_HEAL_BACKOFF_CAP env)",
                    "query": "300",
                    "current": {"text": "300", "value": "300"},
                    "hide": 0,
                },
                {
                    "name": "JITTER_RETRY",
                    "type": "text",
                    "label": "抖动重试次数(仅展示锚点 · 生效见 FMP_JITTER_RETRY env)",
                    "query": "3",
                    "current": {"text": "3", "value": "3"},
                    "hide": 0,
                },
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
