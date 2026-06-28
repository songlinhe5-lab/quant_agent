"""
审计日志查询接口
提供审计日志的查询功能
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.services.audit_service import get_audit_logs

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/logs")
def read_audit_logs(
    action: Optional[str] = Query(None, description="按操作类型过滤"),
    user_id: Optional[int] = Query(None, description="按用户 ID 过滤"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录数"),
    db: Session = Depends(get_db)
):
    """
    查询审计日志

    Args:
        action: 操作类型（'login', 'logout', 'change_password', etc.）
        user_id: 用户 ID
        skip: 跳过记录数
        limit: 返回记录数

    Returns:
        审计日志列表
    """
    logs = get_audit_logs(
        db=db,
        action=action,
        user_id=user_id,
        skip=skip,
        limit=limit
    )

    return [
        {
            "id": log.id,
            "action": log.action,
            "detail": log.detail,
            "ip": log.ip,
            "trace_id": log.trace_id,
            "user_id": log.user_id,
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]
