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

import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.core.logger import logger
from backend.services.datasource import rate_limit_registry

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
    返回结构对齐 docs/14 §12 的 HealthInfo（含 rate_limit_status）。
    限流实时状态另见 GET /datasource/finnhub/rate-limit-status（通用路由已覆盖）。
    """
    from backend.services.datasource import HealthInfo
    from backend.services.finnhub_service import finnhub_service

    api_key = finnhub_service._get_api_key()
    throttler = rate_limit_registry.get_throttler("finnhub")
    rl_status = throttler.get_status()

    healthy = bool(api_key) and not rl_status.is_throttled
    last_error = None
    if not api_key:
        last_error = "FINNHUB_API_KEY 未配置"
    elif rl_status.is_throttled:
        last_error = "Finnhub 处于限流退避期"

    info = HealthInfo(
        healthy=healthy,
        mode="external_rest",
        connected=bool(api_key),
        last_error=last_error,
        rate_limit_status=rl_status,
    )
    return {"source": "finnhub", **info.to_dict()}
