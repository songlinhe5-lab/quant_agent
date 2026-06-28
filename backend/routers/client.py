"""
客户端 APM 心跳接收端点（BE-08）

接收 Flutter / Web / Desktop 客户端上报的 APM 心跳数据，
写入 PostgreSQL client_heartbeats 表供 Dashboard 展示。

POST /api/v1/client/heartbeat
GET  /api/v1/client/heartbeat/stats
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import get_db
from backend.core.error_codes import ErrorCode
from backend.core.logger import logger
from backend.core.metrics import CLIENT_HEARTBEAT_TOTAL
from backend.core.response import error, success
from backend.schemas.domain import ClientHeartbeatModel

router = APIRouter(prefix="/client", tags=["Client APM"])


@router.post("/heartbeat")
async def receive_heartbeat(
    payload: ClientHeartbeatModel,
    db: Session = Depends(get_db),
):
    """
    接收客户端 APM 心跳并写入 PostgreSQL。

    客户端应每 30 秒上报一次心跳，Dashboard 可据此展示：
    - 在线设备数
    - 平均 FPS
    - 平均内存占用
    - WebSocket 延迟分布
    """
    try:
        record = models.ClientHeartbeat(
            platform=payload.platform,
            app_version=payload.app_version,
            device_id=payload.device_id,
            fps=payload.fps,
            memory_mb=payload.memory_mb,
            ws_latency_ms=payload.ws_latency_ms,
        )
        db.add(record)
        db.commit()

        # BE-06: 客户端 APM 指标埋点
        CLIENT_HEARTBEAT_TOTAL.labels(platform=payload.platform).inc()

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

    返回各平台的平均 FPS、内存、WS 延迟和活跃设备数。
    """
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
            )
            .filter(models.ClientHeartbeat.created_at >= since)
            .group_by(models.ClientHeartbeat.platform)
            .all()
        )

        result = []
        for row in stats:
            result.append({
                "platform": row.platform,
                "total_heartbeats": row.total_heartbeats,
                "active_devices": row.active_devices or 0,
                "avg_fps": round(float(row.avg_fps or 0), 1),
                "avg_memory_mb": round(float(row.avg_memory_mb or 0), 1),
                "avg_ws_latency_ms": round(float(row.avg_ws_latency_ms or 0), 0),
            })

        return success(data={
            "window_minutes": minutes,
            "platforms": result,
        })
    except Exception as e:
        logger.error(f"[Heartbeat Stats] 查询失败: {e}")
        return error(code=ErrorCode.INTERNAL_ERROR, msg="统计查询失败")
