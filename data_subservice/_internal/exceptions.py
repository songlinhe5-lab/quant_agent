"""Quant Agent 自定义异常层级（复制自 backend.core.exceptions，物理解耦）

所有业务异常都继承自 QuantBaseException，便于全局异常处理器统一捕获。
"""

from typing import Any, Optional

from fastapi import HTTPException

from data_subservice._internal.error_codes import ErrorCode


class QuantBaseException(Exception):
    """Quant Agent 所有业务异常的基类"""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        msg: str = "内部未知错误",
        data: Any = None,
        *,
        trace_id: Optional[str] = None,
    ):
        self.code = int(code)
        self.msg = msg
        self.data = data
        self.trace_id = trace_id
        super().__init__(msg)


class AuthMissingError(QuantBaseException):
    def __init__(self, msg: str = "Token 缺失，请重新登录", **kw):
        super().__init__(code=ErrorCode.TOKEN_MISSING, msg=msg, **kw)


class TokenExpiredError(QuantBaseException):
    def __init__(self, msg: str = "Token 已过期，请使用 Refresh Token 续期", **kw):
        super().__init__(code=ErrorCode.TOKEN_EXPIRED, msg=msg, **kw)


class TokenInvalidError(QuantBaseException):
    def __init__(self, msg: str = "Token 无效或已被篡改", **kw):
        super().__init__(code=ErrorCode.TOKEN_INVALID, msg=msg, **kw)


class PermissionDeniedError(QuantBaseException):
    def __init__(self, msg: str = "权限不足，请检查账户角色", **kw):
        super().__init__(code=ErrorCode.PERMISSION_DENIED, msg=msg, **kw)


class HmacInvalidError(QuantBaseException):
    def __init__(self, msg: str = "HMAC 签名校验失败", **kw):
        super().__init__(code=ErrorCode.HMAC_INVALID, msg=msg, **kw)


class ValidationError(QuantBaseException):
    def __init__(self, msg: str = "请求参数校验失败", data: Any = None, **kw):
        super().__init__(code=ErrorCode.VALIDATION_FAILED, msg=msg, data=data, **kw)


class ResourceNotFoundError(QuantBaseException):
    def __init__(self, msg: str = "请求的资源不存在", **kw):
        super().__init__(code=ErrorCode.RESOURCE_NOT_FOUND, msg=msg, **kw)


class FutuDisconnectedError(QuantBaseException):
    def __init__(self, msg: str = "Futu OpenD 连接断开，等待自动重连", **kw):
        super().__init__(code=ErrorCode.FUTU_DISCONNECTED, msg=msg, **kw)


class RedisUnavailableError(QuantBaseException):
    def __init__(self, msg: str = "Redis 不可用，请检查服务状态", **kw):
        super().__init__(code=ErrorCode.REDIS_UNAVAILABLE, msg=msg, **kw)


class CircuitBreakerOpenError(QuantBaseException):
    def __init__(self, msg: str = "外部 API 熔断中，请稍后重试", service: str = "unknown", **kw):  # noqa: E501
        super().__init__(
            code=ErrorCode.CIRCUIT_BREAKER_OPEN,
            msg=msg,
            data={"service": service},
            **kw,
        )  # noqa: E501


class AppError(HTTPException):
    """应用编排层抛出的业务错误"""

    def __init__(
        self,
        status_code: int = 400,
        detail: str = "",
        data: Any = None,
        *,
        code: Optional[int] = None,
        trace_id: Optional[str] = None,
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code if code is not None else status_code
        self.msg = detail
        self.data = data
        self.trace_id = trace_id
