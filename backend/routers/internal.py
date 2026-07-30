"""
内部 API 路由示例
所有内部 API 都需要通过 HMAC-SHA256 签名验证
"""

from fastapi import APIRouter, Depends, Request

from backend.core.cache_manager import clear_cache
from backend.core.security import verify_internal_request

router = APIRouter(prefix="/internal", tags=["Internal"])


@router.get("/health")
async def internal_health_check(request: Request, _: None = Depends(verify_internal_request)):
    """
    内部健康检查接口（需要 HMAC 签名验证）

    使用方法：
        1. 客户端生成签名：generate_internal_signature("GET", "/api/v1/internal/health")
        2. 在请求头中添加：X-Internal-Sig: <signature>
    """
    return {"status": "ok", "message": "Internal API is working"}


@router.post("/cache/clear")
async def internal_clear_cache(request: Request, _: None = Depends(verify_internal_request)):
    """
    内部缓存清理接口（需要 HMAC 签名验证）

    默认清理业务缓存（行情 / K 线 / 新闻 / 宏观 / insider 等），
    绝不触碰交易态数据（活动挂单 / 持仓 / OMS 状态）。
    可通过请求体 `{"prefixes": ["quant:kline:*"]}` 指定待清理前缀。
    """
    prefixes: list[str] | None = None
    try:
        body = await request.json()
        if isinstance(body, dict) and isinstance(body.get("prefixes"), list):
            prefixes = [str(p) for p in body["prefixes"]]
    except Exception:
        # 无请求体或解析失败时按默认业务缓存清理
        pass

    try:
        cleared = await clear_cache(prefixes)
        return {"status": "ok", "cleared": cleared}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"缓存清理失败: {e}"}
