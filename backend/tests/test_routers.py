"""
路由层单元测试
覆盖: auth, preferences, internal, search, audit, chat, trade routers
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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

from backend.core import models
from backend.core.database import Base, get_db
from backend.main import app

# 测试数据库配置
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


class TestAuthRoutes:
    def setup_method(self):
        app.dependency_overrides[get_db] = override_get_db  # 防止被其他测试文件覆盖
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        from backend.routers.auth import get_password_hash

        db = TestingSessionLocal()
        user = models.User(
            username="testuser",
            email="test@example.com",
            hashed_password=get_password_hash("testpass"),
        )
        db.add(user)
        db.commit()
        db.close()

    def teardown_method(self):
        Base.metadata.drop_all(bind=engine)

    def test_login_success(self):
        resp = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        # Response wrapped by envelope middleware
        assert data["data"]["access_token"]
        assert data["data"]["token_type"] == "bearer"

    def test_login_wrong_password(self):
        resp = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "wrongpass"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self):
        resp = self.client.post("/api/v1/auth/login", data={"username": "nobody", "password": "pass"})
        assert resp.status_code == 401

    def test_me_endpoint(self):
        login_resp = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "testpass"})
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["username"] == "testuser"

    def test_me_without_token(self):
        resp = self.client.get("/api/v1/auth/me")
        assert resp.status_code in (401, 403)

    def test_me_with_invalid_token(self):
        headers = {"Authorization": "Bearer invalid.token.here"}
        resp = self.client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_change_password(self):
        login_resp = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "testpass"})
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "testpass", "new_password": "newpass123"},
            headers=headers,
        )
        assert resp.status_code == 200

    def test_change_password_wrong_old(self):
        login_resp = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "testpass"})
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "wrongold", "new_password": "newpass123"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_logout(self):
        resp = self.client.post("/api/v1/auth/logout")
        assert resp.status_code == 200


class TestAuthPasswordHelpers:
    def test_get_password_hash(self):
        from backend.routers.auth import get_password_hash

        hashed = get_password_hash("mypassword")
        assert hashed != "mypassword"
        assert len(hashed) > 0

    def test_verify_password_correct(self):
        from backend.routers.auth import get_password_hash, verify_password

        hashed = get_password_hash("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_verify_password_incorrect(self):
        from backend.routers.auth import get_password_hash, verify_password

        hashed = get_password_hash("mypassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_create_access_token(self):
        from datetime import timedelta

        from backend.routers.auth import create_access_token

        token = create_access_token(data={"sub": "testuser"}, expires_delta=timedelta(minutes=5))
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self):
        from datetime import timedelta

        from backend.routers.auth import create_refresh_token

        token = create_refresh_token(data={"sub": "testuser"}, expires_delta=timedelta(days=1))
        assert isinstance(token, str)

    def test_get_current_user_invalid_token(self):
        from fastapi import HTTPException

        from backend.routers.auth import get_current_user

        mock_db = MagicMock()
        with pytest.raises(HTTPException):
            get_current_user(token="invalid.token", db=mock_db)


class TestPreferencesRoutes:
    def setup_method(self):
        app.dependency_overrides[get_db] = override_get_db  # 防止被其他测试文件覆盖
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        from backend.routers.auth import get_password_hash

        db = TestingSessionLocal()
        user = models.User(
            username="prefuser",
            email="pref@example.com",
            hashed_password=get_password_hash("prefpass"),
        )
        db.add(user)
        db.commit()
        db.close()
        login_resp = self.client.post("/api/v1/auth/login", data={"username": "prefuser", "password": "prefpass"})
        self.token = login_resp.json()["data"]["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def teardown_method(self):
        Base.metadata.drop_all(bind=engine)

    @patch("backend.routers.preferences.l1_cached_redis")
    @patch("backend.routers.preferences.redis_client")
    def test_get_preferences_default(self, mock_redis, mock_l1):
        mock_redis.get = AsyncMock(return_value=None)
        mock_l1.get = AsyncMock(return_value=None)
        resp = self.client.get("/api/v1/settings/preferences", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()["data"]["data"]
        assert data["theme"] == "dark"

    @patch("backend.routers.preferences.l1_cached_redis")
    @patch("backend.routers.preferences.redis_client")
    def test_get_news_tags(self, mock_redis, mock_l1):
        mock_redis.get = AsyncMock(return_value=None)
        resp = self.client.get("/api/v1/settings/news-tags", headers=self.headers)
        assert resp.status_code == 200

    @patch("backend.routers.preferences.l1_cached_redis")
    @patch("backend.routers.preferences.redis_client")
    def test_post_news_tags_valid(self, mock_redis, mock_l1):
        mock_l1.set = AsyncMock()
        resp = self.client.post(
            "/api/v1/settings/news-tags",
            json={"FED": r"\bfed\b"},
            headers=self.headers,
        )
        assert resp.status_code == 200

    @patch("backend.routers.preferences.l1_cached_redis")
    @patch("backend.routers.preferences.redis_client")
    def test_post_news_tags_invalid_regex(self, mock_redis, mock_l1):
        resp = self.client.post(
            "/api/v1/settings/news-tags",
            json={"BAD": "[invalid regex"},
            headers=self.headers,
        )
        assert resp.status_code == 400


class TestInternalRoutes:
    def test_health_check_with_valid_sig(self):
        from backend.core.security import generate_internal_signature

        sig = generate_internal_signature("GET", "/api/v1/internal/health")
        headers = {"X-Internal-Sig": sig}
        client = TestClient(app)
        resp = client.get("/api/v1/internal/health", headers=headers)
        assert resp.status_code == 200

    def test_health_check_without_sig(self):
        client = TestClient(app)
        resp = client.get("/api/v1/internal/health")
        assert resp.status_code == 401

    def test_health_check_with_invalid_sig(self):
        headers = {"X-Internal-Sig": "12345.invalidsignature"}
        client = TestClient(app)
        resp = client.get("/api/v1/internal/health", headers=headers)
        assert resp.status_code == 401

    def test_cache_clear_with_valid_sig(self):
        from backend.core.security import generate_internal_signature

        sig = generate_internal_signature("POST", "/api/v1/internal/cache/clear")
        headers = {"X-Internal-Sig": sig}
        client = TestClient(app)
        resp = client.post("/api/v1/internal/cache/clear", headers=headers)
        assert resp.status_code == 200


class TestSecurityHelpers:
    def test_add_internal_signature(self):
        from backend.core.security import add_internal_signature_to_headers

        headers = {}
        result = add_internal_signature_to_headers(headers, "GET", "/test/path")
        assert "X-Internal-Sig" in result
        assert "." in result["X-Internal-Sig"]

    def test_verify_internal_request_missing_header(self):
        import asyncio

        from fastapi import HTTPException
        from starlette.requests import Request

        from backend.core.security import verify_internal_request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(verify_internal_request(request))
        assert exc_info.value.status_code == 401


class TestAuditRoutes:
    def setup_method(self):
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)

    def teardown_method(self):
        Base.metadata.drop_all(bind=engine)

    def test_get_audit_logs(self):
        resp = self.client.get("/api/v1/audit/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_get_audit_logs_with_filters(self):
        resp = self.client.get("/api/v1/audit/logs?action=login&user_id=1&skip=0&limit=10")
        assert resp.status_code == 200


class TestSearchRoutes:
    @patch("backend.routers.search.search_service")
    def test_web_search(self, mock_search):
        mock_search.web_search = AsyncMock(return_value={"status": "success", "data": []})
        client = TestClient(app)
        resp = client.post("/api/v1/search/web", json={"query": "test query", "max_results": 5})
        assert resp.status_code == 200


class TestChatRoutes:
    def test_chat_data_models(self):
        from backend.routers.chat import ChatAttachment, ChatMessage, ChatRequest

        att = ChatAttachment(name="test.pdf", url="data:application/pdf;base64,abc", type="application/pdf")
        assert att.name == "test.pdf"

        msg = ChatMessage(role="user", content="hello", attachments=[att])
        assert msg.role == "user"
        assert len(msg.attachments) == 1

        req = ChatRequest(session_id="s1", messages=[msg])
        assert len(req.messages) == 1


class TestTradeRoutes:
    @patch("backend.routers.trade.futu_service")
    @patch("backend.routers.trade.redis_client")
    def test_get_portfolio(self, mock_redis, mock_futu):
        mock_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 1000000})
        mock_redis.get = AsyncMock(return_value=None)
        client = TestClient(app)
        resp = client.get("/api/v1/trade/portfolio")
        assert resp.status_code == 200
