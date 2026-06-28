"""
内部通信安全模块测试
测试 HMAC-SHA256 签名生成和验证功能
"""
import sys
import os

# 在导入其他模块之前先加载 .env 文件
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.security import (
    generate_internal_signature,
    verify_internal_signature,
    INTERNAL_SIG_EXPIRY,
)
import time


def test_generate_signature():
    """测试签名生成"""
    method = "GET"
    path = "/api/v1/internal/health"
    
    signature = generate_internal_signature(method, path)
    
    # 验证签名格式：timestamp.signature
    parts = signature.split(".")
    assert len(parts) == 2, "签名格式错误"
    
    timestamp = int(parts[0])
    sig = parts[1]
    
    # 验证时间戳是合理的（在当前时间的±10秒内）
    current_time = int(time.time())
    assert abs(timestamp - current_time) < 10, "时间戳异常"
    
    # 验证签名不为空
    assert len(sig) > 0, "签名不能为空"
    
    print("✅ test_generate_signature 通过")


def test_verify_signature_valid():
    """测试验证有效签名"""
    method = "POST"
    path = "/api/v1/internal/cache/clear"
    
    # 生成签名
    signature = generate_internal_signature(method, path)
    
    # 验证签名
    is_valid, error_msg = verify_internal_signature(method, path, signature)
    
    assert is_valid is True, f"验证失败: {error_msg}"
    assert error_msg is None, "错误信息应为 None"
    
    print("✅ test_verify_signature_valid 通过")


def test_verify_signature_invalid():
    """测试验证无效签名"""
    method = "GET"
    path = "/api/v1/internal/health"
    
    # 使用错误的路径验证
    signature = generate_internal_signature(method, path)
    is_valid, error_msg = verify_internal_signature(method, "/wrong/path", signature)
    
    assert is_valid is False, "应该验证失败"
    assert error_msg is not None, "应该返回错误信息"
    
    print("✅ test_verify_signature_invalid 通过")


def test_verify_signature_expired():
    """测试验证过期签名"""
    method = "GET"
    path = "/api/v1/internal/health"
    
    # 生成一个过期的签名（时间戳设为 10 分钟前）
    old_timestamp = int(time.time()) - 600  # 10 分钟前
    signature = generate_internal_signature(method, path, timestamp=old_timestamp)
    
    # 验证签名（应该失败，因为已过期）
    is_valid, error_msg = verify_internal_signature(method, path, signature)
    
    assert is_valid is False, "过期签名应该验证失败"
    assert "expired" in error_msg.lower(), "错误信息应包含 'expired'"
    
    print("✅ test_verify_signature_expired 通过")


def test_verify_signature_wrong_format():
    """测试验证格式错误的签名"""
    method = "GET"
    path = "/api/v1/internal/health"
    
    # 格式错误：缺少时间戳
    is_valid, error_msg = verify_internal_signature(method, path, "invalid-signature")
    assert is_valid is False, "格式错误的签名应该验证失败"
    
    # 格式错误：时间戳不是数字
    is_valid, error_msg = verify_internal_signature(method, path, "abc.signature")
    assert is_valid is False, "时间戳不是数字的签名应该验证失败"
    
    print("✅ test_verify_signature_wrong_format 通过")


def test_case_sensitivity():
    """测试方法名大小写敏感性"""
    path = "/api/v1/internal/health"
    
    # 生成时使用小写
    signature = generate_internal_signature("get", path)
    
    # 验证时使用大写
    is_valid, error_msg = verify_internal_signature("GET", path, signature)
    
    assert is_valid is True, f"方法名大小写应该不敏感: {error_msg}"
    
    print("✅ test_case_sensitivity 通过")


if __name__ == "__main__":
    print("开始测试内部通信安全模块...")
    print("=" * 50)
    
    test_generate_signature()
    test_verify_signature_valid()
    test_verify_signature_invalid()
    test_verify_signature_expired()
    test_verify_signature_wrong_format()
    test_case_sensitivity()
    
    print("=" * 50)
    print("✅ 所有测试通过！")
