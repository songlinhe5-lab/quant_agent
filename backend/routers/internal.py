"""
内部 API 路由示例
所有内部 API 都需要通过 HMAC-SHA256 签名验证
"""
from fastapi import APIRouter, Depends, Request

from backend.core.security import verify_internal_request

router = APIRouter(prefix="/internal", tags=["Internal"])


@router.get("/health")
async def internal_health_check(
    request: Request,
    _: None = Depends(verify_internal_request)
):
    """
    内部健康检查接口（需要 HMAC 签名验证）

    使用方法：
        1. 客户端生成签名：generate_internal_signature("GET", "/api/v1/internal/health")
        2. 在请求头中添加：X-Internal-Sig: <signature>
    """
    return {"status": "ok", "message": "Internal API is working"}


@router.post("/cache/clear")
async def internal_clear_cache(
    request: Request,
    _: None = Depends(verify_internal_request)
):
    """
    内部缓存清理接口（需要 HMAC 签名验证）
    """
    # TODO: 实现缓存清理逻辑
    return {"status": "ok", "message": "Cache cleared"}
