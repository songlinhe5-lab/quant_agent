"""
==========================================
Datasource Rate Limit Router - 数据源限流查询路由
==========================================

提供数据源限流频率分析查询 API（读 RateLimitRegistry，非源实例表）：
  - GET /datasource/{name}/rate-limit-analysis  限流频率分析
  - GET /datasource/{name}/rate-limit-status    实时退避状态
  - GET /datasource/rate-limit-overview         所有数据源限流总览

设计文档: docs/14 §12.3, §12.4 · BE-ARCH-04
"""

import asyncio
import inspect
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket
from fastapi.websockets import WebSocketDisconnect
from jose import jwt as _jwt

from backend.core.logger import logger
from backend.services.datasource import datasource_registry, rate_limit_registry

router = APIRouter(prefix="/datasource", tags=["DataSource Rate Limit"])

# window 参数解析正则：支持 "24h", "7d", "1h" 等格式
_WINDOW_PATTERN = re.compile(r"^(\d+)([hd])$")


def _parse_window_seconds(window: Optional[str]) -> Optional[float]:
    """
    解析 window 查询参数为秒数。

    支持格式: "24h", "7d", "1h" 等
    返回 None 表示使用默认窗口。
    """
    if not window:
        return None

    match = _WINDOW_PATTERN.match(window.lower())
    if not match:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 window 参数: {window!r}，支持格式: 24h, 7d",
        )

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return value * 3600
    elif unit == "d":
        return value * 86400
    return None


@router.get("/{name}/rate-limit-analysis")
async def get_rate_limit_analysis(
    name: str,
    window: Optional[str] = Query(
        None,
        description="分析窗口，如 24h, 7d。默认 24h",
        examples=["24h", "7d"],
    ),
):
    """
    查询指定数据源的限流频率分析结果。

    返回:
    - estimated_limit_rpm:      推测的限流阈值 RPM
    - recommended_interval_seconds: 推荐安全请求间隔
    - peak_hours:               限流高峰时段
    - avg_recovery_seconds:     平均恢复时间
    - confidence:               推测可信度 (0~1)
    - history:                  每小时统计明细
    """
    analyzer = rate_limit_registry.get_analyzer(name)
    window_seconds = _parse_window_seconds(window)
    analysis = analyzer.analyze(window_seconds=window_seconds)

    logger.debug(f"[RateLimit] 查询 {name} 限流分析: window={window}, confidence={analysis.confidence:.2f}")

    return analysis.to_dict()


@router.get("/{name}/rate-limit-status")
async def get_rate_limit_status(name: str):
    """
    查询指定数据源的实时退避状态。

    返回:
    - is_throttled:           是否处于退避期
    - throttle_until:         退避截止时间戳
    - consecutive_rate_limits: 连续限流次数
    - estimated_rpm:          当前有效 RPM
    - backoff_strategy:       退避策略
    """
    if not rate_limit_registry.has(name):
        # 即使未注册也返回默认状态（不报错）
        throttler = rate_limit_registry.get_throttler(name)
    else:
        throttler = rate_limit_registry.get_throttler(name)

    status = throttler.get_status()
    return {
        "source": name,
        **status.to_dict(),
    }


@router.get("/rate-limit-overview")
async def get_rate_limit_overview():
    """
    获取所有数据源的限流状态总览。

    返回每个数据源的:
    - 是否退避中
    - 连续限流次数
    - 过去 1h 限流次数
    - 推测 RPM
    """
    entries = rate_limit_registry.list_all()

    if not entries:
        return {"sources": [], "total": 0}

    sources = []
    for name, entry in entries.items():
        throttler_status = entry.throttler.get_status()
        sources.append(
            {
                "source": name,
                "is_throttled": throttler_status.is_throttled,
                "consecutive_rate_limits": throttler_status.consecutive_rate_limits,
                "total_rate_limits_1h": throttler_status.total_rate_limits_1h,
                "estimated_limit_rpm": throttler_status.estimated_limit_rpm,
                "backoff_strategy": throttler_status.backoff_strategy,
            }
        )

    return {
        "sources": sources,
        "total": len(sources),
    }


@router.get("/finnhub/health")
async def get_finnhub_health():
    """
    Finnhub 数据源健康检查（限流感知，SVC-08）。

    被动探测：基于 API Key 配置 + 限流退避状态，不主动消耗免费配额。
    经 DataSourceRegistry 取 FinnhubDataSource 并调用 health()（BE-ARCH-05），
    禁止直连 FinnhubService（BE-ARCH-01 边界约束）。
    限流实时状态另见 GET /datasource/finnhub/rate-limit-status（通用路由已覆盖）。
    """
    from backend.services.datasource import datasource_registry
    from backend.services.datasource.adapters.finnhub import ensure_finnhub_registered

    ensure_finnhub_registered()
    source = datasource_registry.get("finnhub")
    if source is None:
        rl_status = rate_limit_registry.get_throttler("finnhub").get_status()
        return {
            "source": "finnhub",
            "healthy": False,
            "mode": "external_rest",
            "connected": False,
            "last_error": "Finnhub 数据源未注册",
            "rate_limit_status": rl_status.to_dict(),
        }

    info = await source.health()
    return {"source": "finnhub", **info.to_dict()}


# ════════════════════════════════════════════════════════════════
#  COMM-01 数据源健康度统一看板
# ════════════════════════════════════════════════════════════════

# 超过该秒数无成功响应即判定为 STALE（数据源失联）
_STALE_SECONDS = 300
# 链接测试主动探测使用的轻量行情标的（仅用于测量真实网络往返延迟）
_LINK_TEST_TICKER = "AAPL"


async def _build_health_card(name: str) -> Dict[str, Any]:
    """聚合单数据源健康卡片数据（status / 延迟 / 今日调用量 / 成功率 / 限流次数）。"""
    throttler = rate_limit_registry.get_throttler(name)
    analyzer = rate_limit_registry.get_analyzer(name)
    rl_status = throttler.get_status()
    metrics = analyzer.get_health_metrics()
    mounted = datasource_registry.has(name)
    # 取首个 available 实例（is_available 已反映真实 key/连通），无则无法感知真实健康
    source = datasource_registry.get(name)
    health_info = await source.health() if source is not None else None
    # BE-ARCH-05: connected 必须 = 已挂载 AND 真实可用（key 缺失/未连通即 False，实现可感知）
    connected = mounted and (health_info.connected if health_info is not None else False)
    health_error = (
        health_info.last_error if health_info is not None else ("API key 未配置或实例不可用" if mounted else "未注册")
    )
    now = time.time()

    if rl_status.is_throttled:
        status = "throttled"
    elif metrics["last_success_ts"] and (now - metrics["last_success_ts"] > _STALE_SECONDS):
        status = "stale"
    elif metrics["today_errors"] > 0 and metrics["today_success"] == 0:
        status = "error"
    elif metrics["last_request_ts"] == 0:
        status = "idle"
    else:
        status = "healthy"

    return {
        "source": name,
        "status": status,
        "connected": connected,
        "latency_ms": metrics["last_latency_ms"],
        "today_calls": metrics["today_requests"],
        "success_rate": metrics["success_rate"],
        "rate_limit_count": metrics["today_rate_limits"],
        "last_request_ts": metrics["last_request_ts"],
        "last_success_ts": metrics["last_success_ts"],
        "is_throttled": rl_status.is_throttled,
        "consecutive_rate_limits": rl_status.consecutive_rate_limits,
        "backoff_strategy": rl_status.backoff_strategy,
        "latency_avg_ms": metrics["latency_avg_ms"],
        "latency_p95_ms": metrics["latency_p95_ms"],
        "latency_min_ms": metrics["latency_min_ms"],
        "latency_max_ms": metrics["latency_max_ms"],
        "latency_samples": metrics["latency_samples"],
        "health_error": health_error,
    }


@router.get("/health-overview")
async def get_health_overview() -> Dict[str, Any]:
    """
    COMM-01 数据源健康度统一看板数据源（卡片矩阵）。
    前端 DataSourceHealthDashboard 轮询 / 订阅 WS 渲染。
    """
    # 确保数据源适配器已注册，使其出现在健康看板（可感知 / 可挂载）
    # BE-ARCH-05: futu / akshare 已实现 DataSourceInterface 薄适配，惰性注册
    from backend.services.datasource.adapters.akshare import ensure_akshare_registered
    from backend.services.datasource.adapters.futu import ensure_futu_registered
    from backend.services.datasource.adapters.macro import ensure_macro_sources_registered
    from backend.services.datasource.adapters.search import ensure_search_sources_registered

    ensure_macro_sources_registered()
    ensure_futu_registered()
    ensure_akshare_registered()
    ensure_search_sources_registered()

    names = datasource_registry.list_names()
    cards = await asyncio.gather(*[_build_health_card(n) for n in names])
    return {"sources": cards, "total": len(cards), "generated_at": time.time()}


@router.get("/{name}/health")
async def get_source_health(name: str) -> Dict[str, Any]:
    """COMM-01 单数据源健康详情。"""
    if not datasource_registry.has(name):
        raise HTTPException(status_code=404, detail=f"unknown source: {name}")
    return await _build_health_card(name)


@router.post("/{name}/test-link")
async def test_datasource_link(name: str) -> Dict[str, Any]:
    """
    COMM-01 数据源链路主动探测（链接测试）。

    - 调用 source.health() 获取被动状态（兼容同步/异步实现）
    - 若数据源支持 quote action，发起一次真实轻量行情请求测量真实网络往返延迟
    - 将测量结果回写 analyzer，驱动「调用延迟数据验证」
    """
    source = datasource_registry.get(name)
    if source is None:
        raise HTTPException(status_code=404, detail=f"unknown source: {name}")

    start = time.perf_counter()
    probed = False
    error: Optional[str] = None
    connected = False
    healthy = False
    status = "unknown"
    try:
        raw = source.health()
        info = await raw if inspect.isawaitable(raw) else raw
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        connected = bool(getattr(info, "connected", False))
        healthy = bool(getattr(info, "healthy", connected))
        status = getattr(info, "status", "ok")
        error = getattr(info, "last_error", None)

        # 主动真实探测：按 capability 发起一次轻量请求，测量真实网络往返延迟
        caps = getattr(source, "capabilities", []) or []
        probe_action: str | None = None
        probe_params: dict[str, Any] = {}
        if "quote" in caps:
            # 绕过缓存测量真实上游延迟，避免命中 Redis 热缓存后误报 0ms 假阳性
            probe_action, probe_params = "quote", {"ticker": _LINK_TEST_TICKER, "skip_cache": True}
        elif "WEB_SEARCH" in caps:
            probe_action, probe_params = "WEB_SEARCH", {"query": "quant agent test", "max_results": 1}
        elif "WEB_SCRAPE" in caps:
            # 同样绕过缓存测量真实抓取延迟
            probe_action, probe_params = "WEB_SCRAPE", {"url": "https://example.com", "skip_cache": True}
        elif "economic_calendar" in caps or "macro_series" in caps:
            # 宏观源(fred/dbnomics/rbi)此前无探针分支 → 永远显示 health()≈0；
            # 现发真实上游探针并绕过缓存，使其延迟可感知
            probe_action, probe_params = "economic_calendar", {"days_ahead": 1, "skip_cache": True}
        if probe_action:
            try:
                probe_start = time.perf_counter()
                await source.fetch(probe_action, probe_params)
                latency_ms = round((time.perf_counter() - probe_start) * 1000, 2)
                probed = True
            except Exception as pe:
                # 探测失败仅作信息提示，不翻转被动健康结论（标的可能不被该源支持）
                probed = False
                error = f"主动探测失败（被动健康仍有效）: {pe}"

        rate_limit_registry.get_analyzer(name).record_request(is_error=not connected, latency_ms=latency_ms)
        return {
            "source": name,
            "connected": connected,
            "healthy": healthy,
            "status": status,
            "latency_ms": latency_ms,
            "probed": probed,
            "validated": True,
            "error": error,
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        rate_limit_registry.get_analyzer(name).record_request(is_error=True, latency_ms=latency_ms)
        return {
            "source": name,
            "connected": False,
            "healthy": False,
            "status": "error",
            "latency_ms": latency_ms,
            "probed": False,
            "validated": True,
            "error": str(e),
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }


@router.websocket("/ws/health")
async def datasource_health_ws(websocket: WebSocket) -> None:
    """
    COMM-01 实时推送健康看板 + STALE 报警。鉴权：?token=<jwt>（HS256）。
    每 15s 推送一次 overview；当某数据源由非 STALE 转为 STALE 时额外推送 alert。
    """
    token = websocket.query_params.get("token")
    try:
        _secret = os.getenv("WS_JWT_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret"))
        if token:
            _jwt.decode(token, _secret, algorithms=["HS256"])
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_status: Dict[str, str] = {}
    try:
        while True:
            names = datasource_registry.list_names()
            cards = [_build_health_card(n) for n in names]
            alerts: List[Dict[str, Any]] = []
            for c in cards:
                prev = last_status.get(c["source"])
                if prev is not None and prev != "stale" and c["status"] == "stale":
                    alerts.append(
                        {
                            "source": c["source"],
                            "type": "stale",
                            "message": f"{c['source']} 超过 {_STALE_SECONDS}s 无成功响应",
                        }
                    )
                last_status[c["source"]] = c["status"]
            await websocket.send_text(
                json.dumps(
                    {"type": "overview", "sources": cards, "generated_at": time.time()},
                    ensure_ascii=False,
                )
            )
            for a in alerts:
                await websocket.send_text(json.dumps({"type": "alert", **a}, ensure_ascii=False))
            await asyncio.sleep(15)
    except WebSocketDisconnect:
        return
    except Exception:
        return
