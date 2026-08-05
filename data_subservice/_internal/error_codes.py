"""Quant Agent 全局错误码定义（对齐 docs/10 §1.4 错误码表）

（复制自 backend.core.error_codes，物理解耦，零 backend 依赖）
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0

    TOKEN_MISSING = 1001
    TOKEN_EXPIRED = 1002
    TOKEN_INVALID = 1003
    PERMISSION_DENIED = 1004
    HMAC_INVALID = 1005

    VALIDATION_FAILED = 2001
    RESOURCE_NOT_FOUND = 2002

    FUTU_DISCONNECTED = 3001
    REDIS_UNAVAILABLE = 3002
    CIRCUIT_BREAKER_OPEN = 3003

    INTERNAL_ERROR = 5000


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
