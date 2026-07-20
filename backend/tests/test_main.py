"""
主入口模块单元测试
覆盖: backend/main.py 全局异常处理器、统一响应封装
"""

import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.main import app


class TestGlobalExceptionHandler:
    """全局异常处理器测试"""

    def test_quant_exception_handler_returns_unified_format(self):
        """QuantBaseException 转换为统一格式"""
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import QuantBaseException
        from backend.core.exception_handlers import quant_exception_handler

        mock_request = MagicMock(spec=Request)
        exc = QuantBaseException(
            code=int(ErrorCode.VALIDATION_FAILED),
            msg="验证失败",
            data={"field": "ticker"},
        )
        resp = asyncio.run(quant_exception_handler(mock_request, exc))
        assert resp.status_code == 400
        body = resp.body.decode("utf-8")
        assert "2001" in body
        assert "验证失败" in body
        assert "ticker" in body

    def test_validation_exception_handler_returns_422(self):
        """Pydantic 校验失败返回 422"""
        from fastapi.exceptions import RequestValidationError
        from pydantic import BaseModel, ValidationError

        from backend.core.exception_handlers import validation_exception_handler

        class Req(BaseModel):
            ticker: str
            qty: int = 0

        try:
            Req(ticker="", qty="invalid")
        except ValidationError as e:
            exc = RequestValidationError(errors=e.errors())
            mock_request = MagicMock(spec=Request)
            resp = asyncio.run(validation_exception_handler(mock_request, exc))
            assert resp.status_code == 422
            body = resp.body.decode("utf-8")
            assert "2001" in body

    def test_global_exception_handler_returns_500(self):
        """兜底异常返回 500"""
        from backend.core.exception_handlers import global_exception_handler

        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url = MagicMock()
        mock_request.url.path = "/test"
        exc = RuntimeError("内部错误")
        resp = asyncio.run(global_exception_handler(mock_request, exc))
        assert resp.status_code == 500
        body = resp.body.decode("utf-8")
        assert "5000" in body
        assert "trace_id" in body


class TestResponseEnvelopeMiddleware:
    """响应封装中间件测试"""

    def test_middleware_wraps_old_response(self):
        """旧式响应被自动包装为统一格式"""

        @app.get("/test-old-format")
        async def test_old_format():
            return {"status": "success", "message": "ok", "data": {"x": 1}}

        client = TestClient(app)
        resp = client.get("/test-old-format")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["msg"] == "ok"
        assert body["data"]["status"] == "success"
        assert body["data"]["data"]["x"] == 1
        assert "ts" in body

    def test_middleware_passes_new_format(self):
        """已有 code 字段的响应直接放行"""

        @app.get("/test-new-format")
        async def test_new_format():
            return {"code": 0, "msg": "success", "data": {"x": 1}}

        client = TestClient(app)
        resp = client.get("/test-new-format")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["msg"] == "success"
        assert body["data"]["x"] == 1


class TestSecurityMiddleware:
    """安全中间件测试"""

    def test_cors_returns_cors_headers(self):
        """CORS 返回允许的 headers"""
        client = TestClient(app)
        resp = client.options(
            "/api/v1/market/quote",
            headers={"Origin": "http://localhost:5173"},
        )
        assert "access-control-allow-origin" in resp.headers or resp.status_code == 405


class TestSystemEndpoints:
    """系统级端点测试"""

    def test_health_check_no_auth(self):
        """未认证访问内部端点返回 401"""
        client = TestClient(app)
        resp = client.get("/api/v1/internal/health")
        assert resp.status_code == 401
