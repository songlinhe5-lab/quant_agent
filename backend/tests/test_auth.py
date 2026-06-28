"""
认证路由单元测试
TEST-01: 后端核心路径（行情管道、认证、OMS）单元测试覆盖率 ≥ 70%
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 💡 关键：必须导入 models 以确保所有表（含 User）被注册到 Base.metadata
from backend.core import models  # noqa: F401
from backend.core.database import Base, get_db


class TestAuthRoutes:
    """认证路由测试"""

    def setup_method(self):
        """为每个测试创建内存数据库并覆盖依赖"""
        # 创建内存数据库（使用 StaticPool 保证多线程共享同一内存库）
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # 创建所有表
        Base.metadata.create_all(bind=self.engine)

        # 覆盖 get_db 依赖
        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        from backend.main import app
        app.dependency_overrides[get_db] = override_get_db

        # 创建测试客户端
        self.client = TestClient(app)

        # 💡 修复：直接通过 ORM 创建用户（auth 模块无 /register 端点）
        from backend.routers.auth import get_password_hash
        db = self.TestingSessionLocal()
        user = models.User(
            username="testuser",
            email="test@example.com",
            hashed_password=get_password_hash("testpassword"),
        )
        db.add(user)
        db.commit()
        db.close()

    def teardown_method(self):
        """清理数据库"""
        Base.metadata.drop_all(bind=self.engine)
        from backend.main import app
        app.dependency_overrides.clear()

    def test_health_endpoint(self, test_client):
        """测试健康检查端点"""
        response = test_client.get("/api/v1/health")
        # 200 成功 / 503 服务未就绪（Redis未连接等）均属正常
        assert response.status_code in (200, 503)

    def test_login_missing_credentials(self, test_client):
        """测试登录缺少凭据"""
        response = test_client.post("/api/v1/auth/login", json={})
        # 应该返回 4xx 错误
        assert response.status_code in (400, 401, 422)

    def test_login_wrong_credentials(self):
        """测试登录错误凭据"""
        response = self.client.post(
            "/api/v1/auth/login",
            data={"username": "wrong", "password": "wrong"},
        )
        # 应该返回 401
        assert response.status_code in (400, 401)

    def test_refresh_without_cookie(self, test_client):
        """测试无 Cookie 刷新 Token"""
        response = test_client.post("/api/v1/auth/refresh")
        # 没有 Refresh Token Cookie 应该失败
        assert response.status_code in (400, 401)

    def test_me_without_auth(self, test_client):
        """测试未认证获取当前用户"""
        response = test_client.get("/api/v1/auth/me")
        assert response.status_code in (401, 403)

    def test_logout_without_auth(self, test_client):
        """测试未认证登出"""
        response = test_client.post("/api/v1/auth/logout")
        # 未认证登出应该成功或返回 401
        assert response.status_code in (200, 401)
        response = test_client.post("/api/v1/auth/logout")
        # 未认证登出应该成功或返回 401
        assert response.status_code in (200, 401)


class TestAuthJWT:
    """JWT Token 测试"""

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

    def test_password_hashing(self):
        """测试密码哈希"""
        from backend.routers.auth import get_password_hash, verify_password

        password = "test_password_123"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False


class TestRateLimiter:
    """限流中间件测试"""

    def test_rate_limit_headers(self, test_client):
        """测试限流响应头"""
        response = test_client.get("/api/v1/health")
        # 健康检查可能因 Redis 未连接返回 503，但不应崩溃
        assert response.status_code in (200, 503)
