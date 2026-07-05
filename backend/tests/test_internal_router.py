"""
单元测试：内部 API 路由 (routers/internal.py)
测试需要 HMAC 签名验证的内部接口
"""

import time
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.security import generate_internal_signature, verify_internal_signature
from backend.routers.internal import router


@pytest.fixture
def app():
    """创建测试 FastAPI 应用"""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def internal_secret():
    """获取内部 API 密钥"""
    return "test-internal-secret"


@pytest.fixture(autouse=True)
def override_settings(internal_secret):
    """覆盖全局设置以使用测试密钥"""
    # Mock backend.core.config.settings
    with mock.patch("backend.core.config.settings") as mock_settings:
        mock_settings.internal_api_secret = internal_secret
        mock_settings.quant_env = "development"
        yield mock_settings


@pytest.fixture(autouse=True)
def override_security_settings(internal_secret):
    """覆盖 security.py 中的 settings"""
    with mock.patch("backend.core.security.settings") as mock_settings:
        # security.py 使用 getattr(settings, "INTERNAL_API_SECRET", ...)
        # 所以我们需要设置 INTERNAL_API_SECRET 属性
        mock_settings.INTERNAL_API_SECRET = internal_secret
        mock_settings.internal_api_secret = internal_secret
        yield mock_settings


class TestSignatureGenerationAndVerification:
    """测试签名生成和验证"""

    def test_generate_and_verify_valid(self, internal_secret):
        """测试生成和验证有效签名"""
        method = "GET"
        path = "/api/v1/internal/health"
        timestamp = int(time.time())

        # 生成签名
        signature = generate_internal_signature(method, path, timestamp, internal_secret)

        # 验证签名
        valid, error = verify_internal_signature(method, path, signature, internal_secret)
        assert valid is True
        assert error is None

    def test_verify_invalid_signature(self, internal_secret):
        """测试验证无效签名"""
        method = "GET"
        path = "/api/v1/internal/health"
        timestamp = int(time.time())

        # 生成签名
        signature = generate_internal_signature(method, path, timestamp, internal_secret)

        # 篡改签名
        parts = signature.split(".")
        tampered_signature = f"{parts[0]}.tampered_signature"

        # 验证签名
        valid, error = verify_internal_signature(method, path, tampered_signature, internal_secret)
        assert valid is False
        assert error == "Invalid signature"

    def test_verify_expired_signature(self, internal_secret):
        """测试验证过期签名"""
        method = "GET"
        path = "/api/v1/internal/health"
        expired_timestamp = int(time.time()) - 400  # 过期

        # 生成签名
        signature = generate_internal_signature(method, path, expired_timestamp, internal_secret)

        # 验证签名
        valid, error = verify_internal_signature(method, path, signature, internal_secret)
        assert valid is False
        assert error == "Signature expired"

    def test_signature_format(self, internal_secret):
        """测试签名格式正确"""
        method = "GET"
        path = "/api/v1/internal/health"
        timestamp = int(time.time())

        signature = generate_internal_signature(method, path, timestamp, internal_secret)

        # 验证签名格式：timestamp.signature
        parts = signature.split(".")
        assert len(parts) == 2
        assert parts[0] == str(timestamp)

        # 验证签名是有效的 Base64 字符串
        import base64

        try:
            base64.b64decode(parts[1])
        except Exception:
            pytest.fail("Signature is not valid Base64")


class TestInternalHealthCheck:
    """测试内部健康检查接口"""

    def test_without_signature(self, client):
        """测试无签名时返回 401"""
        response = client.get("/api/v1/internal/health")
        assert response.status_code == 401
        assert "Missing X-Internal-Sig header" in response.json()["detail"]

    def test_with_valid_signature(self, client, internal_secret):
        """测试有效签名时返回 200"""
        method = "GET"
        path = "/api/v1/internal/health"
        timestamp = int(time.time())

        # 生成签名
        signature = generate_internal_signature(method, path, timestamp, internal_secret)

        response = client.get(
            "/api/v1/internal/health",
            headers={
                "X-Internal-Sig": signature,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_with_invalid_signature_format(self, client):
        """测试签名格式错误时返回 401"""
        response = client.get(
            "/api/v1/internal/health",
            headers={
                "X-Internal-Sig": "invalid-signature-format",  # 缺少时间戳
            },
        )
        assert response.status_code == 401
        assert "Invalid signature format" in response.json()["detail"]


class TestInternalCacheClear:
    """测试内部缓存清理接口"""

    def test_with_valid_signature(self, client, internal_secret):
        """测试有效签名时返回 200"""
        method = "POST"
        path = "/api/v1/internal/cache/clear"
        timestamp = int(time.time())

        # 生成签名
        signature = generate_internal_signature(method, path, timestamp, internal_secret)

        response = client.post(
            "/api/v1/internal/cache/clear",
            headers={
                "X-Internal-Sig": signature,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
