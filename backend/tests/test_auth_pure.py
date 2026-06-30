"""
认证模块纯函数测试（不依赖 TestClient，启动极快）

测试目标：
- get_password_hash() / verify_password()
- create_access_token() / create_refresh_token()
- JWT decode

优化说明：
- 不导入 TestClient，避免加载整个 FastAPI 应用
- 不使用需要数据库或 Redis 的 fixtures
- 适合快速单元测试
"""

import os
import sys
import time

# 🚀 强制在导入任何模块之前设置 bcrypt 低成本（必须放在最顶部）
os.environ["BCRYPT_ROUNDS"] = "4"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


class TestPasswordHash:
    """密码哈希纯函数测试（无 setup，耗时 <0.05s）"""

    def test_hash_and_verify(self):
        """测试密码哈希与验证"""
        from backend.routers.auth import get_password_hash, verify_password

        password = "test_password_123"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_hash_speed(self):
        """确认 BCRYPT_ROUNDS=4 生效（耗时应 <0.01s）"""
        from backend.routers.auth import get_password_hash

        start = time.perf_counter()
        get_password_hash("benchmark")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"bcrypt 太慢: {elapsed:.3f}s (BCRYPT_ROUNDS 未生效?)"


class TestJWTToken:
    """JWT Token 纯函数测试"""

    def test_create_access_token(self):
        """测试创建 Access Token"""
        from backend.routers.auth import create_access_token

        token = create_access_token(data={"sub": "test_user"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self):
        """测试创建 Refresh Token"""
        from backend.routers.auth import create_refresh_token

        token = create_refresh_token(data={"sub": "test_user"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_token(self):
        """测试解码 Token"""
        from jose import jwt

        from backend.routers.auth import ALGORITHM, SECRET_KEY, create_access_token

        token = create_access_token(data={"sub": "test_user"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload.get("sub") == "test_user"

    def test_decode_invalid_token(self):
        """测试解码无效 Token"""
        from jose import JWTError, jwt

        from backend.routers.auth import ALGORITHM, SECRET_KEY

        with pytest.raises(JWTError):
            jwt.decode("invalid.token.here", SECRET_KEY, algorithms=[ALGORITHM])
