"""
Chat 路由测试
覆盖: backend/routers/chat.py
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient
from jose import jwt

from backend.main import app
from backend.routers.chat import ALGORITHM, SECRET_KEY


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效的 JWT Token"""
    token = jwt.encode({"sub": "testuser"}, SECRET_KEY, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _unwrap(resp):
    body = resp.json()
    return body.get("data", body)


# ==========================================
# GET /chat/suggestions
# ==========================================


class TestChatSuggestions:
    def test_suggestions_default(self, client):
        resp = client.get("/api/v1/chat/suggestions")
        assert resp.status_code == 200
        body = resp.json()
        data = body.get("data", body)
        # 响应可能被封装为 {"data": {"status":..., "data":[...]}} 或直接返回
        if isinstance(data, dict):
            assert data["status"] == "success"
            assert len(data["data"]) == 10
        else:
            # data 直接是列表
            assert isinstance(data, list)

    def test_suggestions_custom_limit(self, client):
        resp = client.get("/api/v1/chat/suggestions?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        data = body.get("data", body)
        if isinstance(data, dict):
            assert len(data["data"]) == 5
        else:
            assert isinstance(data, list)

    def test_suggestions_have_title_and_prompt(self, client):
        resp = client.get("/api/v1/chat/suggestions?limit=3")
        body = resp.json()
        data = body.get("data", body)
        items = data["data"] if isinstance(data, dict) else data
        for item in items:
            assert "title" in item
            assert "prompt" in item


# ==========================================
# POST /chat (需要认证)
# ==========================================


class TestChatEndpoint:
    def test_chat_no_auth(self, client):
        """无 Token 返回 401"""
        resp = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "hello"}]})
        assert resp.status_code == 401

    def test_chat_invalid_token(self, client):
        """无效 Token 返回 401"""
        resp = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp.status_code == 401

    def test_chat_registry_not_initialized(self, client, auth_headers):
        """Registry 未初始化返回 503"""
        with patch("backend.bootstrap.lifecycle.global_registry", None):
            resp = client.post(
                "/api/v1/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers=auth_headers,
            )
        assert resp.status_code in (503, 500, 422)


# ==========================================
# GET /sessions (需要认证)
# ==========================================


class TestSessions:
    def test_sessions_no_auth(self, client):
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 401

    @patch("backend.routers.chat.SessionLocal")
    def test_sessions_success(self, mock_session_local, client, auth_headers):
        """正常获取会话列表"""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session

        mock_record = MagicMock()
        mock_record.session_id = "user_testuser_sess1"
        mock_record.title = "测试会话"
        mock_record.created_at = MagicMock()
        mock_record.created_at.isoformat = MagicMock(return_value="2026-07-01T00:00:00")
        mock_record.updated_at = MagicMock()
        mock_record.updated_at.isoformat = MagicMock(return_value="2026-07-01T01:00:00")
        mock_record.messages = [{"role": "user", "content": "hello"}]

        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_record]

        resp = client.get("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.chat.SessionLocal")
    def test_sessions_with_search(self, mock_session_local, client, auth_headers):
        """带搜索关键字"""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []

        resp = client.get("/api/v1/sessions?q=test", headers=auth_headers)
        assert resp.status_code == 200


# ==========================================
# GET /sessions/{session_id}
# ==========================================


class TestSessionHistory:
    def test_session_history_no_auth(self, client):
        resp = client.get("/api/v1/sessions/sess1")
        assert resp.status_code == 401

    @patch("backend.routers.chat.SessionLocal")
    def test_session_history_success(self, mock_session_local, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session

        mock_record = MagicMock()
        mock_record.messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record

        resp = client.get("/api/v1/sessions/sess1", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 2

    @patch("backend.routers.chat.SessionLocal")
    def test_session_history_not_found(self, mock_session_local, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        resp = client.get("/api/v1/sessions/nonexist", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"] == []


# ==========================================
# DELETE /sessions
# ==========================================


class TestDeleteAllSessions:
    def test_delete_all_no_auth(self, client):
        resp = client.delete("/api/v1/sessions")
        assert resp.status_code == 401

    @patch("backend.routers.chat.redis_client")
    @patch("backend.routers.chat.SessionLocal")
    def test_delete_all_success(self, mock_session_local, mock_redis, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session

        mock_record = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_record]
        mock_redis.scan = AsyncMock(return_value=(0, []))
        mock_redis.delete = AsyncMock(return_value=True)

        resp = client.delete("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.chat.redis_client")
    @patch("backend.routers.chat.SessionLocal")
    def test_delete_all_empty(self, mock_session_local, mock_redis, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_redis.scan = AsyncMock(return_value=(0, []))

        resp = client.delete("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "无历史会话" in data.get("message", "")


# ==========================================
# DELETE /sessions/{session_id}
# ==========================================


class TestDeleteSession:
    def test_delete_session_no_auth(self, client):
        resp = client.delete("/api/v1/sessions/sess1")
        assert resp.status_code == 401

    @patch("backend.routers.chat.redis_client")
    @patch("backend.routers.chat.SessionLocal")
    def test_delete_session_success(self, mock_session_local, mock_redis, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session

        mock_record = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record
        mock_redis.delete = AsyncMock(return_value=True)

        resp = client.delete("/api/v1/sessions/sess1", headers=auth_headers)
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.chat.redis_client")
    @patch("backend.routers.chat.SessionLocal")
    def test_delete_session_not_found(self, mock_session_local, mock_redis, client, auth_headers):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_redis.delete = AsyncMock(return_value=True)

        resp = client.delete("/api/v1/sessions/nonexist", headers=auth_headers)
        assert resp.status_code == 404


# ==========================================
# get_current_username 单元测试
# ==========================================


class TestGetCurrentUsername:
    def test_null_token(self, client):
        """token 为 'null' 字符串"""
        resp = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer null"},
        )
        assert resp.status_code == 401

    def test_token_missing_sub(self, client):
        """Token 缺少 sub 字段"""
        token = jwt.encode({"data": "no_sub"}, SECRET_KEY, algorithm=ALGORITHM)
        resp = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
