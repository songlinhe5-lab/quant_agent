"""main.py 全局异常处理器单元测试
覆盖: quant_exception_handler, validation_exception_handler, global_exception_handler
"""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.core.exceptions import QuantBaseException
from backend.main import app
from backend.routers.auth import get_current_user

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@pytest.fixture
def client():
    """创建测试客户端，并覆盖认证依赖"""
    # 使用 dependency_overrides 覆盖认证
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=1, username="testuser", email="test@test.com"
    )
    # raise_server_exceptions=False 让 TestClient 不重新抛出异常，而是返回响应
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def _unwrap(resp):
    """解析响应，返回响应体"""
    body = resp.json()
    # 如果响应被包装成统一格式，返回 data 字段
    if "code" in body and "data" in body:
        return body["data"]
    return body


class TestQuantExceptionHandler:
    """QuantBaseException 全局异常处理器测试"""

    def test_quant_exception_returns_custom_format(self, client):
        """正常路径：QuantBaseException 被正确封装为统一格式"""

        @app.get("/test-quant-exc")
        def test_quant_exc_endpoint():
            raise QuantBaseException(
                code=5000,  # 使用 INTERNAL_ERROR，映射到 HTTP 500
                msg="测试异常",
                data={"detail": "测试数据"},
            )

        resp = client.get("/test-quant-exc")
        # code=5000 映射到 HTTP 500
        assert resp.status_code == 500
        body = resp.json()
        # 检查统一格式
        assert body["code"] == 5000
        assert body["msg"] == "测试异常"
        assert body["data"]["detail"] == "测试数据"
        assert "ts" in body

    def test_quant_exception_with_trace_id(self, client):
        """带 trace_id 的异常被正确携带"""

        @app.get("/test-quant-exc-trace")
        def test_quant_exc_trace_endpoint():
            raise QuantBaseException(
                code=1002,
                msg="测试异常",
                data={},
                trace_id="abc123",
            )

        resp = client.get("/test-quant-exc-trace")
        body = resp.json()
        assert body["trace_id"] == "abc123"


class TestValidationExceptionHandler:
    """RequestValidationError 参数校验异常处理器测试"""

    def test_validation_error_returns_code_2001(self, client):
        """参数校验失败返回 code=2001"""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            required_field: str

        @app.post("/test-validation")
        def test_validation_endpoint(data: TestModel):
            return {"status": "success"}

        resp = client.post("/test-validation", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 2001
        assert "请求参数校验失败" in body["msg"]
        assert isinstance(body["data"], list)

    def test_validation_error_includes_field_details(self, client):
        """校验错误包含字段位置和错误信息"""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            age: int

        @app.post("/test-validation-detail")
        def test_validation_detail_endpoint(data: TestModel):
            return {"status": "success"}

        resp = client.post("/test-validation-detail", json={"name": "test", "age": "invalid"})
        assert resp.status_code == 422
        body = resp.json()
        # 验证统一格式
        assert body["code"] == 2001
        errors = body["data"]
        assert isinstance(errors, list)
        assert len(errors) >= 1
        # 检查是否有 age 字段的错误
        assert any("age" in str(e.get("field", "")) for e in errors)


class TestGlobalExceptionHandler:
    """兜底异常处理器测试"""

    def test_unknown_exception_returns_500(self, client):
        """未知异常被捕获并返回统一格式"""

        # 使用唯一的路由路径避免冲突
        @app.get("/test-unknown-exc-unique")
        def test_unknown_exc_endpoint():
            raise RuntimeError("意外运行时错误")

        resp = client.get("/test-unknown-exc-unique")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == 5000
        assert "error" in body["msg"].lower() or "内部" in body["msg"]
        assert "trace_id" in body

    def test_value_error_returns_500(self, client):
        """ValueError 被兜底处理器捕获"""

        # 使用唯一的路由路径避免冲突
        @app.get("/test-value-exc-unique")
        def test_value_exc_endpoint():
            raise ValueError("值错误")

        resp = client.get("/test-value-exc-unique")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == 5000
