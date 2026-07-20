"""
全局异常处理器
从 main.py 迁出 (ARCH-01): QuantBaseException / HTTPException / ValidationError / 兜底
"""

import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.core.error_codes import ERROR_CODE_TO_HTTP_STATUS, ErrorCode
from backend.core.exceptions import QuantBaseException
from backend.core.logger import logger


async def quant_exception_handler(request: Request, exc: QuantBaseException):
    """捕获所有 QuantBaseException 子类，统一转换为 {code, msg, data, ts} 格式"""
    http_status = ERROR_CODE_TO_HTTP_STATUS.get(exc.code, 500)
    body = {
        "code": exc.code,
        "msg": exc.msg,
        "data": exc.data,
        "ts": int(time.time() * 1000),
    }
    if exc.trace_id:
        body["trace_id"] = exc.trace_id
    return JSONResponse(status_code=http_status, content=body)


async def http_exception_handler(request: Request, exc: HTTPException):
    """捕获 FastAPI 原生 HTTPException，统一转换为 {code, msg, data, ts} 格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "msg": exc.detail,
            "data": None,
            "ts": int(time.time() * 1000),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """捕获 Pydantic 请求参数校验失败，转换为 code=2001 的统一格式"""
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err["loc"]) if err.get("loc") else ""
        errors.append({"field": loc, "msg": err.get("msg", ""), "type": err.get("type", "")})
    body = {
        "code": int(ErrorCode.VALIDATION_FAILED),
        "msg": f"请求参数校验失败: {exc.errors()[0]['msg']}" if exc.errors() else "请求参数校验失败",
        "data": errors,
        "ts": int(time.time() * 1000),
    }
    return JSONResponse(status_code=422, content=body)


async def global_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器：捕获所有未预料的异常，返回 code=5000"""
    trace_id = str(uuid.uuid4())[:16]
    logger.error(
        f"[UnhandledException] {request.method} {request.url.path} trace_id={trace_id} error={exc}",
        exc_info=True,
    )
    body = {
        "code": int(ErrorCode.INTERNAL_ERROR),
        "msg": f"内部服务器错误 (trace_id: {trace_id})",
        "data": None,
        "ts": int(time.time() * 1000),
        "trace_id": trace_id,
    }
    return JSONResponse(status_code=500, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""
    app.add_exception_handler(QuantBaseException, quant_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
