"""Quant Agent 自定义异常层级单元测试 (零 backend 依赖)"""

from fastapi import HTTPException

from data_subservice._internal.error_codes import ErrorCode
from data_subservice._internal.exceptions import (
    AppError,
    AuthMissingError,
    CircuitBreakerOpenError,
    FutuDisconnectedError,
    HmacInvalidError,
    PermissionDeniedError,
    QuantBaseException,
    RedisUnavailableError,
    ResourceNotFoundError,
    TokenExpiredError,
    TokenInvalidError,
    ValidationError,
)


class TestQuantBaseException:
    def test_base_default(self):
        e = QuantBaseException()
        assert e.code == int(ErrorCode.INTERNAL_ERROR)
        assert e.msg == "内部未知错误"
        assert e.data is None
        assert e.trace_id is None
        assert str(e) == "内部未知错误"

    def test_base_custom(self):
        e = QuantBaseException(code=ErrorCode.VALIDATION_FAILED, msg="bad", data={"x": 1}, trace_id="tid")
        assert e.code == int(ErrorCode.VALIDATION_FAILED)
        assert e.msg == "bad"
        assert e.data == {"x": 1}
        assert e.trace_id == "tid"

    def test_subclasses_use_correct_code(self):
        cases = [
            (AuthMissingError, ErrorCode.TOKEN_MISSING),
            (TokenExpiredError, ErrorCode.TOKEN_EXPIRED),
            (TokenInvalidError, ErrorCode.TOKEN_INVALID),
            (PermissionDeniedError, ErrorCode.PERMISSION_DENIED),
            (HmacInvalidError, ErrorCode.HMAC_INVALID),
            (ValidationError, ErrorCode.VALIDATION_FAILED),
            (ResourceNotFoundError, ErrorCode.RESOURCE_NOT_FOUND),
            (FutuDisconnectedError, ErrorCode.FUTU_DISCONNECTED),
            (RedisUnavailableError, ErrorCode.REDIS_UNAVAILABLE),
        ]
        for cls, code in cases:
            inst = cls()
            assert isinstance(inst, QuantBaseException)
            assert inst.code == int(code)

    def test_validation_error_carries_data(self):
        e = ValidationError(msg="invalid", data={"field": "price"})
        assert e.data == {"field": "price"}

    def test_circuit_breaker_open_error_has_service(self):
        e = CircuitBreakerOpenError(msg="boom", service="yfinance")
        assert isinstance(e, QuantBaseException)
        assert e.code == int(ErrorCode.CIRCUIT_BREAKER_OPEN)
        assert e.data == {"service": "yfinance"}


class TestAppError:
    def test_default(self):
        e = AppError()
        assert e.status_code == 400
        assert e.code == 400
        assert e.msg == ""
        assert isinstance(e, HTTPException)

    def test_custom(self):
        e = AppError(status_code=404, detail="not found", data={"id": 1}, code=999, trace_id="t")
        assert e.status_code == 404
        assert e.code == 999
        assert e.msg == "not found"
        assert e.data == {"id": 1}
        assert e.trace_id == "t"
