"""
Quant Agent 全局错误码定义（对齐 docs/10 §1.4 错误码表）

错误码分域：
  0     = 成功
  1xxx  = 认证 / 鉴权
  2xxx  = 请求参数 / 资源
  3xxx  = 外部依赖 / 基础设施
  5xxx  = 内部未知错误
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    # ===== 成功 =====
    OK = 0

    # ===== 1xxx 认证 / 鉴权 =====
    TOKEN_MISSING = 1001
    TOKEN_EXPIRED = 1002
    TOKEN_INVALID = 1003
    PERMISSION_DENIED = 1004
    HMAC_INVALID = 1005

    # ===== 2xxx 请求 / 资源 =====
    VALIDATION_FAILED = 2001
    RESOURCE_NOT_FOUND = 2002

    # ===== 3xxx 基础设施 =====
    FUTU_DISCONNECTED = 3001
    REDIS_UNAVAILABLE = 3002
    CIRCUIT_BREAKER_OPEN = 3003

    # ===== 5xxx 内部错误 =====
    INTERNAL_ERROR = 5000


# HTTP 状态码映射表（FastAPI 异常处理器用）
ERROR_CODE_TO_HTTP_STATUS: dict[int, int] = {
    ErrorCode.OK: 200,
    ErrorCode.TOKEN_MISSING: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.HMAC_INVALID: 403,
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.FUTU_DISCONNECTED: 503,
    ErrorCode.REDIS_UNAVAILABLE: 503,
    ErrorCode.CIRCUIT_BREAKER_OPEN: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}
