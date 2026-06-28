"""
审计日志中间件
自动记录关键操作到审计日志
"""

from typing import Callable, Dict

from fastapi import Request, Response

from backend.core.database import get_db
from backend.services.audit_service import log_audit

# 需要审计的操作映射（路径 + 方法 -> 操作类型）
AUDITABLE_OPERATIONS: Dict[str, str] = {
    # 认证相关
    "/api/v1/auth/login": "login",
    "/api/v1/auth/logout": "logout",
    "/api/v1/auth/register": "register",
    # 订单相关
    "/api/v1/trade/order": "order_simulate",
    "/api/v1/oms/order": "order_execute",
    # 策略相关
    "/api/v1/strategy": "strategy_create",
    "/api/v1/strategy/": "strategy_modify",
    # 设置相关
    "/api/v1/settings": "settings_change",
}


async def audit_middleware(request: Request, call_next: Callable) -> Response:
    """
    审计中间件：自动记录关键操作

    注意：这个中间件会记录所有请求，但只审计 AUDITABLE_OPERATIONS 中定义的操作
    """
    # 只处理 POST、PUT、DELETE 请求（读操作通常不审计）
    if request.method not in ["POST", "PUT", "DELETE"]:
        return await call_next(request)

    # 获取请求路径
    path = request.url.path

    # 检查是否需要审计
    action = None
    for audit_path, audit_action in AUDITABLE_OPERATIONS.items():
        if path.startswith(audit_path):
            action = audit_action
            break

    # 如果不是需要审计的操作，直接放行
    if not action:
        return await call_next(request)

    # 执行请求
    response = await call_next(request)

    # 只审计成功的请求（状态码 2xx）
    if 200 <= response.status_code < 300:
        try:
            # 获取数据库会话
            db = next(get_db())

            # 提取请求体（如果有）
            detail = {}
            if request.method in ["POST", "PUT"]:
                # 注意：请求体只能读取一次，这里需要在实际使用中调整
                # 建议在路由函数中直接调用 log_audit
                pass

            # 记录审计日志
            log_audit(db=db, action=action, detail=detail, request=request)
        except Exception as e:
            # 审计日志失败不应影响主流程
            print(f"审计日志写入失败: {e}")

    return response
