"""
客户端 APM 心跳接收端点（BE-08 + OBS-03）

接收 Flutter / Web / Desktop 客户端上报的 APM 心跳与 Web Vitals，
写入 PostgreSQL client_heartbeats，并导出 Prometheus 直方图。

POST /api/v1/client/heartbeat
GET  /api/v1/client/heartbeat/stats
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import engine, get_db
from backend.core.error_codes import ErrorCode
from backend.core.logger import logger
from backend.core.metrics import (
    CLIENT_HEARTBEAT_TOTAL,
    CLIENT_WEB_VITAL_CLS,
    CLIENT_WEB_VITAL_INP,
    CLIENT_WEB_VITAL_LCP,
    CLIENT_WEB_VITAL_TTFB,
)
from backend.core.response import error, success
from backend.schemas.domain import ClientHeartbeatModel

router = APIRouter(prefix="/client", tags=["Client APM"])

_VITALS_COLUMNS_ENSURED = False


def ensure_heartbeat_vitals_columns(bind=None) -> None:
    """为已有库补齐 Web Vitals 可空列（create_all 不会 ALTER）。"""
    global _VITALS_COLUMNS_ENSURED
    if _VITALS_COLUMNS_ENSURED:
        return
    target = bind or engine
    try:
        insp = inspect(target)
        if "client_heartbeats" not in insp.get_table_names():
            _VITALS_COLUMNS_ENSURED = True
            return
        existing = {c["name"] for c in insp.get_columns("client_heartbeats")}
        needed = ("lcp_ms", "cls", "inp_ms", "ttfb_ms")
        missing = [c for c in needed if c not in existing]
        if missing:
            with target.begin() as conn:
                for col in missing:
                    conn.execute(text(f"ALTER TABLE client_heartbeats ADD COLUMN {col} FLOAT"))
            logger.info(f"[Heartbeat] Web Vitals columns added: {missing}")
        _VITALS_COLUMNS_ENSURED = True
    except Exception as e:
        logger.warning(f"[Heartbeat] ensure vitals columns failed: {e}")


def _observe_web_vitals(platform: str, payload: ClientHeartbeatModel) -> None:
    if payload.lcp_ms is not None and payload.lcp_ms >= 0:
        CLIENT_WEB_VITAL_LCP.labels(platform=platform).observe(payload.lcp_ms / 1000.0)
    if payload.cls is not None and payload.cls >= 0:
        CLIENT_WEB_VITAL_CLS.labels(platform=platform).observe(payload.cls)
    if payload.inp_ms is not None and payload.inp_ms >= 0:
        CLIENT_WEB_VITAL_INP.labels(platform=platform).observe(payload.inp_ms / 1000.0)
    if payload.ttfb_ms is not None and payload.ttfb_ms >= 0:
        CLIENT_WEB_VITAL_TTFB.labels(platform=platform).observe(payload.ttfb_ms / 1000.0)


@router.post("/heartbeat")
async def receive_heartbeat(
    payload: ClientHeartbeatModel,
    db: Session = Depends(get_db),
):
    """
    接收客户端 APM 心跳并写入 PostgreSQL。

    客户端应每 30 秒上报一次心跳，Dashboard 可据此展示：
    - 在线设备数 / 平均 FPS / 内存 / WS 延迟
    - Web 端额外：LCP / CLS / INP / TTFB（OBS-03）
    """
    ensure_heartbeat_vitals_columns(db.get_bind())
    try:
        record = models.ClientHeartbeat(
            platform=payload.platform,
            app_version=payload.app_version,
            device_id=payload.device_id,
            fps=payload.fps,
            memory_mb=payload.memory_mb,
            ws_latency_ms=payload.ws_latency_ms,
            lcp_ms=payload.lcp_ms,
            cls=payload.cls,
            inp_ms=payload.inp_ms,
            ttfb_ms=payload.ttfb_ms,
        )
        db.add(record)
        db.commit()

        CLIENT_HEARTBEAT_TOTAL.labels(platform=payload.platform).inc()
        _observe_web_vitals(payload.platform, payload)

        return success(data={"received_at": int(datetime.now().timestamp() * 1000)})
    except Exception as e:
        logger.error(f"[Heartbeat] 写入失败: {e}")
        return error(code=ErrorCode.INTERNAL_ERROR, msg="心跳写入失败")


@router.get("/heartbeat/stats")
async def heartbeat_stats(
    minutes: int = 30,
    db: Session = Depends(get_db),
):
    """
    获取最近 N 分钟的客户端 APM 统计摘要。

    返回各平台的平均 FPS、内存、WS 延迟、Web Vitals 和活跃设备数。
    """
    ensure_heartbeat_vitals_columns(db.get_bind())
    since = datetime.utcnow() - timedelta(minutes=minutes)

    try:
        stats = (
            db.query(
                models.ClientHeartbeat.platform,
                func.count(models.ClientHeartbeat.id).label("total_heartbeats"),
                func.count(func.distinct(models.ClientHeartbeat.device_id)).label("active_devices"),
                func.avg(models.ClientHeartbeat.fps).label("avg_fps"),
                func.avg(models.ClientHeartbeat.memory_mb).label("avg_memory_mb"),
                func.avg(models.ClientHeartbeat.ws_latency_ms).label("avg_ws_latency_ms"),
                func.avg(models.ClientHeartbeat.lcp_ms).label("avg_lcp_ms"),
                func.avg(models.ClientHeartbeat.cls).label("avg_cls"),
                func.avg(models.ClientHeartbeat.inp_ms).label("avg_inp_ms"),
                func.avg(models.ClientHeartbeat.ttfb_ms).label("avg_ttfb_ms"),
            )
            .filter(models.ClientHeartbeat.created_at >= since)
            .group_by(models.ClientHeartbeat.platform)
            .all()
        )

        result = []
        for row in stats:
            result.append(
                {
                    "platform": row.platform,
                    "total_heartbeats": row.total_heartbeats,
                    "active_devices": row.active_devices or 0,
                    "avg_fps": round(float(row.avg_fps or 0), 1),
                    "avg_memory_mb": round(float(row.avg_memory_mb or 0), 1),
                    "avg_ws_latency_ms": round(float(row.avg_ws_latency_ms or 0), 0),
                    "avg_lcp_ms": round(float(row.avg_lcp_ms or 0), 1),
                    "avg_cls": round(float(row.avg_cls or 0), 4),
                    "avg_inp_ms": round(float(row.avg_inp_ms or 0), 1),
                    "avg_ttfb_ms": round(float(row.avg_ttfb_ms or 0), 1),
                }
            )

        return success(
            data={
                "window_minutes": minutes,
                "platforms": result,
            }
        )
    except Exception as e:
        logger.error(f"[Heartbeat Stats] 查询失败: {e}")
        return error(code=ErrorCode.INTERNAL_ERROR, msg="统计查询失败")
