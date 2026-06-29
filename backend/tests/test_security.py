"""
内部通信安全模块单元测试（HMAC-SHA256）

覆盖：
- generate_internal_signature() 签名生成
- verify_internal_signature() 签名验证
- verify_internal_request() FastAPI 依赖
- add_internal_signature_to_headers() 请求头签名
- 异常路径：格式错误、签名过期、签名不匹配
"""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.requests import Request

from backend.core.security import (
    INTERNAL_SIG_EXPIRY,
    add_internal_signature_to_headers,
    generate_internal_signature,
    verify_internal_request,
    verify_internal_signature,
)


class TestGenerateInternalSignature:
    """generate_internal_signature() 签名生成"""

    def test_returns_timestamp_and_signature(self):
        """返回格式：timestamp.signature"""
        result = generate_internal_signature("GET", "/api/test")
        parts = result.split(".")
        assert len(parts) == 2
        assert int(parts[0])  # timestamp 是整数
        assert len(parts[1]) > 0  # signature 非空

    def test_different_calls_have_different_timestamps(self):
        """使用不同时间戳生成不同的签名"""
        ts1 = int(time.time())
        ts2 = ts1 + 1  # 使用不同的时间戳
        result1 = generate_internal_signature("GET", "/api/test", timestamp=ts1)
        result2 = generate_internal_signature("GET", "/api/test", timestamp=ts2)
        assert result1 != result2

    def test_custom_secret(self):
        """使用自定义密钥生成签名"""
        result1 = generate_internal_signature("GET", "/api/test", secret="secret1")
        result2 = generate_internal_signature("GET", "/api/test", secret="secret2")
        assert result1 != result2

    def test_custom_timestamp(self):
        """使用自定义时间戳生成签名"""
        ts = 1234567890
        result = generate_internal_signature("GET", "/api/test", timestamp=ts)
        assert result.startswith(f"{ts}.")


class TestVerifyInternalSignature:
    """verify_internal_signature() 签名验证"""

    def test_valid_signature(self):
        """有效签名验证通过"""
        signature = generate_internal_signature("GET", "/api/test")
        is_valid, error = verify_internal_signature("GET", "/api/test", signature)
        assert is_valid is True
        assert error is None

    def test_invalid_format_too_few_parts(self):
        """格式错误：部分数不足"""
        is_valid, error = verify_internal_signature("GET", "/api/test", "invalid")
        assert is_valid is False
        assert "Invalid signature format" in error

    def test_invalid_format_too_many_parts(self):
        """格式错误：部分数过多"""
        is_valid, error = verify_internal_signature("GET", "/api/test", "1.2.3")
        assert is_valid is False
        assert "Invalid signature format" in error

    def test_expired_signature(self):
        """过期签名验证失败"""
        old_ts = int(time.time()) - INTERNAL_SIG_EXPIRY - 10
        signature = generate_internal_signature("GET", "/api/test", timestamp=old_ts)
        is_valid, error = verify_internal_signature("GET", "/api/test", signature)
        assert is_valid is False
        assert "expired" in error.lower()

    def test_invalid_signature(self):
        """签名不匹配验证失败"""
        signature = generate_internal_signature("GET", "/api/test")
        # 篡改签名
        parts = signature.split(".")
        tampered_signature = f"{parts[0]}.invalid_signature"
        is_valid, error = verify_internal_signature("GET", "/api/test", tampered_signature)
        assert is_valid is False
        assert "Invalid signature" in error

    def test_different_method_fails(self):
        """不同 HTTP 方法验证失败"""
        signature = generate_internal_signature("GET", "/api/test")
        is_valid, error = verify_internal_signature("POST", "/api/test", signature)
        assert is_valid is False

    def test_different_path_fails(self):
        """不同路径验证失败"""
        signature = generate_internal_signature("GET", "/api/test")
        is_valid, error = verify_internal_signature("GET", "/api/test/other", signature)
        assert is_valid is False

    def test_custom_secret(self):
        """使用自定义密钥验证"""
        signature = generate_internal_signature("GET", "/api/test", secret="my-secret")
        is_valid, error = verify_internal_signature("GET", "/api/test", signature, secret="my-secret")
        assert is_valid is True

    def test_exception_handling_invalid_timestamp(self):
        """时间戳格式错误时触发异常捕获"""
        # 时间戳不是整数，会触发异常
        is_valid, error = verify_internal_signature("GET", "/api/test", "not-a-number.signature")
        assert is_valid is False
        assert "Signature verification failed" in error


class TestVerifyInternalRequest:
    """verify_internal_request() FastAPI 依赖"""

    def test_valid_request(self):
        """有效请求通过验证"""
        signature = generate_internal_signature("GET", "/api/test")
        request = MagicMock(spec=Request)
        request.headers = {"X-Internal-Sig": signature}
        request.method = "GET"
        request.url.path = "/api/test"

        # 不应抛出异常
        import asyncio
        asyncio.get_event_loop().run_until_complete(verify_internal_request(request))

    def test_missing_signature_header(self):
        """缺少签名头抛出异常"""
        request = MagicMock(spec=Request)
        request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(verify_internal_request(request))

        assert exc_info.value.status_code == 401
        assert "Missing X-Internal-Sig" in exc_info.value.detail

    def test_invalid_signature(self):
        """无效签名抛出异常"""
        request = MagicMock(spec=Request)
        request.headers = {"X-Internal-Sig": "invalid"}
        request.method = "GET"
        request.url.path = "/api/test"

        with pytest.raises(HTTPException) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(verify_internal_request(request))

        assert exc_info.value.status_code == 401
        assert "Invalid internal signature" in exc_info.value.detail


class TestAddInternalSignatureToHeaders:
    """add_internal_signature_to_headers() 请求头签名"""

    def test_adds_signature_to_headers(self):
        """成功添加签名到请求头"""
        headers = {"Content-Type": "application/json"}
        result = add_internal_signature_to_headers(headers, "GET", "/api/test")
        assert "X-Internal-Sig" in result
        assert result["Content-Type"] == "application/json"

    def test_adds_signature_to_headers(self):
        """成功添加签名到请求头"""
        headers = {"Content-Type": "application/json"}
        result = add_internal_signature_to_headers(headers, "GET", "/api/test")
        # 原始 headers 也会被修改（函数直接修改传入的 dict）
        assert "X-Internal-Sig" in headers
        assert "X-Internal-Sig" in result
        # 原始 headers 的其他字段应保留
        assert result["Content-Type"] == "application/json"
        # 返回的是同一个对象
        assert result is headers

    def test_signature_can_be_verified(self):
        """添加的签名可以被验证"""
        headers = {}
        result = add_internal_signature_to_headers(headers, "GET", "/api/test")
        signature = result["X-Internal-Sig"]
        is_valid, error = verify_internal_signature("GET", "/api/test", signature)
        assert is_valid is True
