"""
Quant Agent 统一响应封装（对齐 docs/10 §1.2 通用响应结构）

所有 REST API 统一返回：
  {"code": 0, "msg": "ok", "data": {...}, "ts": 1719475200000}

路由中直接使用：
    from backend.core.response import success, error
    return success(data={"price": 123.45})
    return error(code=ErrorCode.VALIDATION_FAILED, msg="symbol 字段缺失")
"""
import time
from typing import Any, Optional

from fastapi.responses import JSONResponse

from backend.core.error_codes import ERROR_CODE_TO_HTTP_STATUS, ErrorCode


def _now_ms() -> int:
    """当前 UTC 毫秒时间戳"""
    return int(time.time() * 1000)


def success(data: Any = None, msg: str = "ok") -> dict:
    """
    构造成功响应字典（供路由直接 return）。

    FastAPI 会自动将 dict 序列化为 JSON，且 status_code=200。
    """
    return {
        "code": 0,
        "msg": msg,
        "data": data,
        "ts": _now_ms(),
    }


def error(
    code: int | ErrorCode = ErrorCode.INTERNAL_ERROR,
    msg: str = "内部未知错误",
    data: Any = None,
    *,
    http_status: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> JSONResponse:
    """
    构造错误响应 JSONResponse（供路由直接 return）。

    - code:     业务错误码（见 ErrorCode 枚举）
    - msg:      可读错误描述
    - data:     附加数据（如字段级校验错误列表）
    - http_status:  自定义 HTTP 状态码（默认根据 code 自动映射）
    - trace_id:     链路追踪 ID（可选）
    """
    code_int = int(code)
    status = http_status or ERROR_CODE_TO_HTTP_STATUS.get(code_int, 500)

    body: dict = {
        "code": code_int,
        "msg": msg,
        "data": data,
        "ts": _now_ms(),
    }
    if trace_id:
        body["trace_id"] = trace_id

    return JSONResponse(status_code=status, content=body)
