"""
内部通信安全模块
提供 HMAC-SHA256 签名生成和验证功能，防止内网横向渗透
"""
import hmac
import hashlib
import time
import base64
from typing import Optional, Tuple
from fastapi import Request, HTTPException

from backend.core.config import settings


# HMAC 签名过期时间（秒）
INTERNAL_SIG_EXPIRY = 300  # 5 分钟


def generate_internal_signature(
    method: str,
    path: str,
    timestamp: Optional[int] = None,
    secret: Optional[str] = None
) -> str:
    """
    生成内部通信 HMAC-SHA256 签名
    
    Args:
        method: HTTP 方法（GET, POST, etc.）
        path: 请求路径
        timestamp: 时间戳（如不提供则使用当前时间）
        secret: 签名密钥（如不提供则使用配置中的 INTERNAL_API_SECRET）
    
    Returns:
        签名字符串（格式：timestamp.signature）
    """
    if secret is None:
        secret = getattr(settings, 'INTERNAL_API_SECRET', 'default-internal-secret-change-me')
    
    if timestamp is None:
        timestamp = int(time.time())
    
    # 构造签名字符串：method + path + timestamp
    message = f"{method.upper()}{path}{timestamp}".encode("utf-8")
    
    # 生成 HMAC-SHA256 签名
    signature = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256
    ).digest()
    
    # Base64 编码
    signature_b64 = base64.b64encode(signature).decode("utf-8")
    
    # 返回格式：timestamp.signature
    return f"{timestamp}.{signature_b64}"


def verify_internal_signature(
    method: str,
    path: str,
    signature_header: str,
    secret: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    验证内部通信 HMAC-SHA256 签名
    
    Args:
        method: HTTP 方法（GET, POST, etc.）
        path: 请求路径
        signature_header: 签名头（格式：timestamp.signature）
        secret: 签名密钥（如不提供则使用配置中的 INTERNAL_API_SECRET）
    
    Returns:
        (验证是否通过, 错误信息)
    """
    if secret is None:
        secret = getattr(settings, 'INTERNAL_API_SECRET', 'default-internal-secret-change-me')
    
    try:
        # 解析签名头
        parts = signature_header.split(".")
        if len(parts) != 2:
            return False, "Invalid signature format"
        
        timestamp = int(parts[0])
        received_signature = parts[1]
        
        # 检查时间戳是否过期
        current_time = int(time.time())
        if current_time - timestamp > INTERNAL_SIG_EXPIRY:
            return False, "Signature expired"
        
        # 重新计算签名
        message = f"{method.upper()}{path}{timestamp}".encode("utf-8")
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            message,
            hashlib.sha256
        ).digest()
        expected_signature_b64 = base64.b64encode(expected_signature).decode("utf-8")
        
        # 比较签名（使用 hmac.compare_digest 防止时序攻击）
        if not hmac.compare_digest(received_signature, expected_signature_b64):
            return False, "Invalid signature"
        
        return True, None
        
    except Exception as e:
        return False, f"Signature verification failed: {str(e)}"


async def verify_internal_request(request: Request) -> None:
    """
    验证内部请求的 HMAC 签名（FastAPI 依赖）
    
    使用方法：
        @app.post("/internal/api")
        async def internal_api(request: Request, _: None = Depends(verify_internal_request)):
            ...
    """
    # 从请求头获取签名
    signature_header = request.headers.get("X-Internal-Sig")
    if not signature_header:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Internal-Sig header"
        )
    
    # 验证签名
    method = request.method
    path = str(request.url.path)
    is_valid, error_msg = verify_internal_signature(method, path, signature_header)
    
    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid internal signature: {error_msg}"
        )


def add_internal_signature_to_headers(
    headers: dict,
    method: str,
    path: str,
    secret: Optional[str] = None
) -> dict:
    """
    为请求头添加 HMAC 签名（用于内部服务间调用）
    
    Args:
        headers: 原始请求头
        method: HTTP 方法
        path: 请求路径
        secret: 签名密钥
    
    Returns:
        添加了 X-Internal-Sig 的请求头
    """
    signature = generate_internal_signature(method, path, secret=secret)
    headers["X-Internal-Sig"] = signature
    return headers
