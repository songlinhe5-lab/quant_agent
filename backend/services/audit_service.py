"""
审计日志服务层
提供审计日志的写入和查询功能
"""
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import Request
import uuid

from sqlalchemy.orm import Session
from core.models import AuditLog


def get_client_ip(request: Optional[Request] = None) -> Optional[str]:
    """获取客户端 IP 地址"""
    if request is None:
        return None
    
    # 尝试从代理头获取真实 IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # 回退到直接连接 IP
    if request.client:
        return request.client.host
    
    return None


def generate_trace_id() -> str:
    """生成追踪 ID"""
    return str(uuid.uuid4())


def log_audit(
    db: Session,
    action: str,
    detail: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
    user_id: Optional[int] = None,
    trace_id: Optional[str] = None
) -> AuditLog:
    """
    记录审计日志
    
    Args:
        db: 数据库会话
        action: 操作类型（'login', 'logout', 'order_simulate', 'order_execute', 'settings_change', etc.）
        detail: 操作详情（字典，会转为 JSON）
        request: FastAPI Request 对象（用于提取 IP）
        user_id: 用户 ID
        trace_id: 追踪 ID（如不提供则自动生成）
    
    Returns:
        AuditLog: 创建的审计日志对象
    """
    ip = get_client_ip(request) if request else None
    
    audit_log = AuditLog(
        action=action,
        detail=detail or {},
        ip=ip,
        trace_id=trace_id or generate_trace_id(),
        user_id=user_id,
        created_at=datetime.utcnow()
    )
    
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    
    return audit_log


def get_audit_logs(
    db: Session,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
):
    """
    查询审计日志
    
    Args:
        db: 数据库会话
        action: 按操作类型过滤
        user_id: 按用户 ID 过滤
        skip: 跳过记录数
        limit: 返回记录数
    
    Returns:
        List[AuditLog]: 审计日志列表
    """
    query = db.query(AuditLog)
    
    if action:
        query = query.filter(AuditLog.action == action)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    return query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
