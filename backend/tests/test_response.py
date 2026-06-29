"""
统一响应封装单元测试（对齐 docs/10 §1.2）

覆盖：
- success() 成功响应结构
- error() 错误响应结构
- HTTP 状态码映射
- trace_id 透传
- 时间戳字段存在性
"""

import time

import pytest
from fastapi.responses import JSONResponse

from backend.core.error_codes import ErrorCode
from backend.core.response import error, success


class TestSuccess:
    """success() 成功响应"""

    def test_returns_dict(self):
        result = success(data={"price": 123.45})
        assert isinstance(result, dict)

    def test_default_msg(self):
        result = success(data={"key": "val"})
        assert result["msg"] == "ok"

    def test_custom_msg(self):
        result = success(data={}, msg="自定义消息")
        assert result["msg"] == "自定义消息"

    def test_code_always_zero(self):
        result = success(data=None)
        assert result["code"] == 0

    def test_data_field(self):
        data = {"symbol": "AAPL", "price": 150.0}
        result = success(data=data)
        assert result["data"] == data

    def test_data_none(self):
        result = success(data=None)
        assert result["data"] is None

    def test_ts_is_recent(self):
        now_ms = int(time.time() * 1000)
        result = success(data={})
        assert isinstance(result["ts"], int)
        # 时间戳应在最近 5 秒内
        assert abs(result["ts"] - now_ms) < 5000

    def test_required_keys(self):
        result = success(data={})
        assert set(result.keys()) == {"code", "msg", "data", "ts"}


class TestError:
    """error() 错误响应"""

    def test_returns_json_response(self):
        result = error(code=ErrorCode.TOKEN_INVALID, msg="token 无效")
        assert isinstance(result, JSONResponse)

    def test_default_http_status(self):
        """未指定 http_status 时根据错误码自动映射"""
        result = error(code=ErrorCode.VALIDATION_FAILED, msg="参数错误")
        assert result.status_code == 400

    def test_custom_http_status(self):
        result = error(code=ErrorCode.INTERNAL_ERROR, msg="内部错误", http_status=503)
        assert result.status_code == 503

    def test_body_structure(self):
        result = error(code=ErrorCode.TOKEN_MISSING, msg="token 缺失")
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert "code" in parsed
        assert "msg" in parsed
        assert "data" in parsed
        assert "ts" in parsed

    def test_error_code_int(self):
        """ErrorCode 枚举自动转为 int"""
        result = error(code=ErrorCode.RESOURCE_NOT_FOUND, msg="未找到")
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert isinstance(parsed["code"], int)

    def test_data_field_in_error(self):
        result = error(code=ErrorCode.VALIDATION_FAILED, msg="错误", data={"field": "symbol"})
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert parsed["data"] == {"field": "symbol"}

    def test_trace_id_included(self):
        result = error(code=ErrorCode.INTERNAL_ERROR, msg="错误", trace_id="abc-123")
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert parsed["trace_id"] == "abc-123"

    def test_trace_id_absent_when_none(self):
        result = error(code=ErrorCode.INTERNAL_ERROR, msg="错误")
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert "trace_id" not in parsed

    def test_ts_in_error_response(self):
        result = error(code=ErrorCode.INTERNAL_ERROR, msg="错误")
        body = result.body.decode("utf-8")
        import json

        parsed = json.loads(body)
        assert isinstance(parsed["ts"], int)


class TestErrorCodeMapping:
    """错误码 -> HTTP 状态码映射"""

    def test_validation_failed_maps_to_400(self):
        result = error(code=ErrorCode.VALIDATION_FAILED, msg="错误")
        assert result.status_code == 400

    def test_token_missing_maps_to_401(self):
        result = error(code=ErrorCode.TOKEN_MISSING, msg="错误")
        assert result.status_code == 401

    def test_token_expired_maps_to_401(self):
        result = error(code=ErrorCode.TOKEN_EXPIRED, msg="错误")
        assert result.status_code == 401

    def test_resource_not_found_maps_to_404(self):
        result = error(code=ErrorCode.RESOURCE_NOT_FOUND, msg="错误")
        assert result.status_code == 404

    def test_internal_error_maps_to_500(self):
        result = error(code=ErrorCode.INTERNAL_ERROR, msg="错误")
        assert result.status_code == 500

    def test_circuit_breaker_open_maps_to_503(self):
        result = error(code=ErrorCode.CIRCUIT_BREAKER_OPEN, msg="熔断")
        assert result.status_code == 503
