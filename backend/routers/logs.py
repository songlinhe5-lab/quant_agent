"""
前端日志路由 (FE-05b)
======================

POST /api/v1/logs — 接收前端批量日志
GET  /api/v1/logs — 查询前端日志（支持 level 筛选、时间范围、分页）
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.logger import logger
from backend.routers.auth import get_current_user_optional

router = APIRouter(prefix="/logs", tags=["Frontend Logs"])


# ─── Schema ────────────────────────────────────────────────────────


class LogEntrySchema(BaseModel):
    """单条前端日志"""

    timestamp: str = Field(description="ISO 8601 时间戳")
    level: int = Field(description="日志级别: 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR")
    message: str = Field(max_length=2048)
    context: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, str]] = None


class LogBatchSchema(BaseModel):
    """批量日志请求体"""

    logs: List[LogEntrySchema] = Field(min_length=1, max_length=100)


class LogResponseSchema(BaseModel):
    """日志响应"""

    id: int
    timestamp: str
    level: str
    message: str
    context: Optional[Dict[str, Any]] = None
    page_url: Optional[str] = None
    user_agent: Optional[str] = None


# ─── 级别映射 ──────────────────────────────────────────────────────

LEVEL_MAP = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR"}
LEVEL_NAMES = list(LEVEL_MAP.values())


# ─── POST /logs — 接收前端日志 ─────────────────────────────────────


@router.post("", status_code=201)
async def receive_frontend_logs(
    body: LogBatchSchema,
    request: Request,
    username: Optional[str] = Depends(get_current_user_optional),
):
    """接收前端批量日志，写入 PostgreSQL"""
    from backend.core.database import SessionLocal
    from backend.core.models import FrontendLog

    user_agent = request.headers.get("user-agent", "")[:512]
    page_url = request.headers.get("referer", "")[:512]

    records = []
    for entry in body.logs:
        level_name = LEVEL_MAP.get(entry.level, "INFO")
        # 拼接 error 信息到 message
        message = entry.message
        if entry.error:
            error_detail = entry.error.get("message", "")
            if error_detail:
                message = f"{message} | {error_detail}"

        records.append(
            FrontendLog(
                level=level_name,
                message=message[:2048],
                context=entry.context,
                user_agent=user_agent,
                page_url=page_url,
            )
        )

    def _write():
        with SessionLocal() as db:
            db.bulk_save_objects(records)
            db.commit()
            return len(records)

    try:
        count = await asyncio.to_thread(_write)
        logger.info(f"[FrontendLogs] 接收 {count} 条日志")
        return {"status": "success", "data": {"received": count}}
    except Exception as e:
        logger.error(f"[FrontendLogs] 写入失败: {e}")
        raise HTTPException(status_code=500, detail="日志写入失败")


# ─── GET /logs — 查询前端日志 ──────────────────────────────────────


@router.get("")
async def query_frontend_logs(
    level: Optional[str] = Query(None, description="按级别筛选: DEBUG / INFO / WARN / ERROR"),
    since: Optional[str] = Query(None, description="ISO 时间戳，只返回此时间之后的日志"),
    until: Optional[str] = Query(None, description="ISO 时间戳，只返回此时间之前的日志"),
    limit: int = Query(100, le=500, description="返回条数上限"),
    offset: int = Query(0, description="分页偏移量"),
    username: Optional[str] = Depends(get_current_user_optional),
):
    """查询前端日志（支持 level 筛选、时间范围、分页）"""
    from backend.core.database import SessionLocal
    from backend.core.models import FrontendLog

    if level and level.upper() not in LEVEL_NAMES:
        raise HTTPException(status_code=400, detail=f"无效的 level: {level}，可选值: {LEVEL_NAMES}")

    def _query():
        with SessionLocal() as db:
            q = db.query(FrontendLog)

            if level:
                q = q.filter(FrontendLog.level == level.upper())

            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    q = q.filter(FrontendLog.timestamp >= since_dt)
                except ValueError:
                    pass

            if until:
                try:
                    until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                    q = q.filter(FrontendLog.timestamp <= until_dt)
                except ValueError:
                    pass

            total = q.count()
            logs = q.order_by(FrontendLog.timestamp.desc()).offset(offset).limit(limit).all()

            return {
                "total": total,
                "items": [
                    {
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                        "level": log.level,
                        "message": log.message,
                        "context": log.context,
                        "page_url": log.page_url,
                        "user_agent": log.user_agent,
                    }
                    for log in logs
                ],
            }

    try:
        data = await asyncio.to_thread(_query)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"[FrontendLogs] 查询失败: {e}")
        raise HTTPException(status_code=500, detail="日志查询失败")
