"""routers/preferences.py 补充测试

覆盖缺口: POST /settings/preferences 路由级、GET/POST /settings/watchlist、
watchlist batch add/remove 引用计数联动、异常路径。
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app
from backend.core import models
from backend.routers.auth import get_current_user

# 创建模拟用户
def _mock_user(username="testuser"):
    return models.User(id=1, username=username, email=f"{username}@test.com",
                       hashed_password="x")


@pytest.fixture
def client():
    """创建测试客户端，并覆盖认证依赖"""
    # 使用 dependency_overrides 正确覆盖 FastAPI 的依赖注入
    app.dependency_overrides[get_current_user] = lambda: _mock_user()
    client = TestClient(app)
    yield client
    # 测试后清理
    app.dependency_overrides.clear()


class TestUpdatePreferencesRoute:
    """POST /api/v1/settings/preferences 路由级测试"""

    def test_update_preferences_merges_and_syncs_yfinance_flag(self, client):
        """更新偏好时,若含 yfinanceFallbackEnabled,同步写入全局 L1 缓存"""
        existing = {"theme": "dark", "defaultLeverage": 1.0}
        with patch("backend.routers.preferences.redis_client") as m_redis, \
             patch("backend.routers.preferences.l1_cached_redis") as m_l1:
            m_redis.get = AsyncMock(return_value=json.dumps(existing))
            m_redis.set = AsyncMock(return_value=True)
            m_l1.set = AsyncMock(return_value=True)
            resp = client.post(
                "/api/v1/settings/preferences",
                json={"theme": "light", "yfinanceFallbackEnabled": False},
            )
        assert resp.status_code == 200
        body = resp.json()
        # 响应被包装成统一格式 {"code": 0, "data": {...}, "msg": "...", "ts": ...}
        # 注意：端点返回 {"status": "...", "message": "...", "data": current_prefs}
        # 所以 body["data"] 包含端点的原始响应
        assert body["code"] == 0
        assert body["data"]["data"]["theme"] == "light"
        assert body["data"]["data"]["defaultLeverage"] == 1.0  # 保留旧字段
        # 验证 yfinance 全局开关同步
        m_l1.set.assert_any_call("quant:settings:yfinance_enabled", "0")

    def test_update_preferences_without_yfinance_flag_skips_sync(self, client):
        """更新偏好不含 yfinanceFallbackEnabled 时,不触发全局同步"""
        with patch("backend.routers.preferences.redis_client") as m_redis, \
             patch("backend.routers.preferences.l1_cached_redis") as m_l1:
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            m_l1.set = AsyncMock(return_value=True)
            resp = client.post(
                "/api/v1/settings/preferences",
                json={"theme": "dark"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        m_l1.set.assert_not_awaited()

    def test_update_preferences_redis_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis, \
             patch("backend.routers.preferences.l1_cached_redis"):
            m_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.post(
                "/api/v1/settings/preferences",
                json={"theme": "dark"},
            )
        assert resp.status_code == 500


class TestWatchlistRoutes:
    """GET /api/v1/settings/watchlist + POST /api/v1/settings/watchlist/batch"""

    def test_get_watchlist_empty(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.smembers = AsyncMock(return_value=[])
            resp = client.get("/api/v1/settings/watchlist")
        assert resp.status_code == 200
        # 响应被包装成统一格式，端点返回 {"status": "...", "data": [...]}
        # 所以 resp.json()["data"] 是端点的原始响应
        assert resp.json()["data"]["data"] == []

    def test_get_watchlist_decodes_bytes_members(self, client):
        """Redis 返回 bytes 列表时正确解码为 str"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.smembers = AsyncMock(
                return_value=[b"US.AAPL", b"HK.00700"]
            )
            resp = client.get("/api/v1/settings/watchlist")
        assert resp.status_code == 200
        # 响应被包装成统一格式，端点返回 {"status": "...", "data": [...]}
        data = resp.json()["data"]["data"]
        assert "US.AAPL" in data and "HK.00700" in data

    def test_get_watchlist_handles_str_members(self, client):
        """Redis 返回 str 列表时直接使用"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.smembers = AsyncMock(return_value=["US.TSLA"])
            resp = client.get("/api/v1/settings/watchlist")
        assert resp.status_code == 200
        # 响应被包装成统一格式，端点返回 {"status": "...", "data": [...]}
        assert resp.json()["data"]["data"] == ["US.TSLA"]

    def test_get_watchlist_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.smembers = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.get("/api/v1/settings/watchlist")
        assert resp.status_code == 500

    def test_batch_add_increments_refcount(self, client):
        """批量添加:新标的加入用户集 + 全局引用计数+1"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.sadd = AsyncMock(return_value=1)  # 1=新增
            m_redis.hincrby = AsyncMock(return_value=1)
            resp = client.post(
                "/api/v1/settings/watchlist/batch",
                json={"tickers": ["AAPL", "TSLA"], "action": "add"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        # 引用计数+1 调用 2 次
        assert m_redis.hincrby.await_count == 2

    def test_batch_add_existing_ticker_skips_refcount(self, client):
        """批量添加:已存在的标的不再增加引用计数"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.sadd = AsyncMock(return_value=0)  # 0=已存在
            m_redis.hincrby = AsyncMock(return_value=1)
            resp = client.post(
                "/api/v1/settings/watchlist/batch",
                json={"tickers": ["AAPL"], "action": "add"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        m_redis.hincrby.assert_not_awaited()

    def test_batch_remove_decrements_refcount_and_cleans_zero(self, client):
        """批量移除:引用计数-1,归零时 hdel 清理"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.srem = AsyncMock(return_value=1)  # 1=移除成功
            m_redis.hincrby = AsyncMock(return_value=0)  # 归零
            m_redis.hdel = AsyncMock(return_value=1)
            resp = client.post(
                "/api/v1/settings/watchlist/batch",
                json={"tickers": ["AAPL"], "action": "remove"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        m_redis.hdel.assert_awaited_once()

    def test_batch_remove_nonexistent_ticker_skips(self, client):
        """批量移除:不在监控池的标的跳过"""
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.srem = AsyncMock(return_value=0)  # 0=不存在
            m_redis.hincrby = AsyncMock(return_value=0)
            resp = client.post(
                "/api/v1/settings/watchlist/batch",
                json={"tickers": ["NOPE"], "action": "remove"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        m_redis.hincrby.assert_not_awaited()

    def test_batch_update_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.sadd = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.post(
                "/api/v1/settings/watchlist/batch",
                json={"tickers": ["AAPL"], "action": "add"},
            )
        assert resp.status_code == 500


class TestGetPreferencesEdgeCases:
    """GET /api/v1/settings/preferences 边界条件"""

    def test_get_preferences_redis_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.get("/api/v1/settings/preferences")
        assert resp.status_code == 500

    def test_get_preferences_with_saved_data_merges_defaults(self, client):
        """有保存数据时,与默认值合并(保存值覆盖默认值)"""
        saved = {"theme": "light", "defaultLeverage": 3.0}
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(saved))
            resp = client.get("/api/v1/settings/preferences")
        assert resp.status_code == 200
        # 响应被包装成统一格式，端点返回 {"status": "...", "data": {...}}
        # 所以 resp.json()["data"]["data"] 是实际的偏好数据
        data = resp.json()["data"]["data"]
        assert data["theme"] == "light"
        assert data["defaultLeverage"] == 3.0
        assert data["language"] == "zh-CN"  # 默认值保留（修正原测试中的拼写错误）


class TestNewsTagsEdgeCases:
    """GET /api/v1/settings/news-tags 边界条件"""

    def test_get_news_tags_returns_cached_rules(self, client):
        """有缓存时返回缓存规则"""
        cached = {"CUSTOM": r"\b(custom)\b"}
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/settings/news-tags")
        assert resp.status_code == 200
        # 响应被包装成统一格式，端点返回 {"status": "...", "data": {...}}
        # 所以 resp.json()["data"]["data"] 是实际的规则数据
        assert resp.json()["data"]["data"] == cached

    def test_get_news_tags_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis:
            m_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.get("/api/v1/settings/news-tags")
        assert resp.status_code == 500

    def test_post_news_tags_success_persists_to_redis(self, client):
        with patch("backend.routers.preferences.redis_client") as m_redis, \
             patch("backend.routers.preferences.l1_cached_redis") as m_l1:
            m_l1.set = AsyncMock(return_value=True)
            resp = client.post(
                "/api/v1/settings/news-tags",
                json={"FED": r"\b(fed|fomc)\b"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        m_l1.set.assert_awaited_once()

    def test_post_news_tags_server_error_returns_500(self, client):
        with patch("backend.routers.preferences.redis_client"), \
             patch("backend.routers.preferences.l1_cached_redis") as m_l1:
            m_l1.set = AsyncMock(side_effect=RuntimeError("redis down"))
            resp = client.post(
                "/api/v1/settings/news-tags",
                json={"FED": r"\b(fed)\b"},
            )
        assert resp.status_code == 500
