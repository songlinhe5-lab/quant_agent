import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 💡 关键：必须导入 models 以确保所有表（含 User）被注册到 Base.metadata
from backend.core import models  # noqa: F401
from backend.core.database import Base, get_db
from backend.main import app

# 1. 配置纯内存的 SQLite 数据库，使用 StaticPool 保证所有连接共享同一内存库
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)  # noqa: E501
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 2. 依赖覆盖 (Dependency Override)：让 FastAPI 接口使用测试数据库
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


# 💡 修复：mock Redis，本地测试无 Redis 环境
_fake_redis_store = {}


async def _fake_get(key):
    return _fake_redis_store.get(key)


async def _fake_set(key, value, ex=None):
    _fake_redis_store[key] = value
    return True


async def _fake_smembers(key):
    return _fake_redis_store.get(key, set())


async def _fake_sadd(key, *values):
    s = _fake_redis_store.setdefault(key, set())
    added = 0
    for v in values:
        if v not in s:
            s.add(v)
            added += 1
    return added


async def _fake_srem(key, *values):
    s = _fake_redis_store.get(key, set())
    removed = 0
    for v in values:
        if v in s:
            s.discard(v)
            removed += 1
    return removed


async def _fake_hincrby(key, field, amount):
    h = _fake_redis_store.setdefault(key, {})
    h[field] = h.get(field, 0) + amount
    return h[field]


async def _fake_hdel(key, *fields):
    h = _fake_redis_store.get(key, {})
    removed = 0
    for f in fields:
        if f in h:
            del h[f]
            removed += 1
    return removed


class TestPreferencesAPI(unittest.TestCase):
    def setUp(self):
        # 防止被其他测试文件覆盖,确保用本文件的 engine
        app.dependency_overrides[get_db] = override_get_db
        # 每次测试前，在内存中创建所有表
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)

        # 💡 修复：直接通过 ORM 创建用户（auth 模块无 /register 端点）
        from backend.routers.auth import get_password_hash

        db = TestingSessionLocal()
        user = models.User(
            username="testuser",
            email="test@example.com",
            hashed_password=get_password_hash("testpassword"),
        )
        db.add(user)
        db.commit()
        db.close()

        # 登录并获取 Token
        response = self.client.post("/api/v1/auth/login", data={"username": "testuser", "password": "testpassword"})
        self.assertEqual(response.status_code, 200, f"Login failed: {response.json()}")
        self.token = response.json()["data"]["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # 清空 fake redis
        _fake_redis_store.clear()

    def tearDown(self):
        # 测试结束后清理表结构
        Base.metadata.drop_all(bind=engine)

    @patch("backend.routers.preferences.l1_cached_redis")
    @patch("backend.routers.preferences.redis_client")
    def test_create_and_update_preferences(self, mock_redis, mock_l1):
        mock_redis.get = AsyncMock(side_effect=_fake_get)
        mock_redis.set = AsyncMock(side_effect=_fake_set)
        mock_l1.get = AsyncMock(side_effect=_fake_get)
        mock_l1.set = AsyncMock(side_effect=_fake_set)

        # 💡 修复：preferences router prefix="/settings" 挂载在 /api/v1 下，实际路径为 /api/v1/settings/preferences
        # 💡 响应被 response_envelope_middleware 二次包装: {code, msg, data: {原始响应}, ts}
        payload_1 = {"macro_symbols": ["AAPL", "MSFT", "GOOGL"]}
        res_post_1 = self.client.post("/api/v1/settings/preferences", json=payload_1, headers=self.headers)  # noqa: E501
        self.assertEqual(res_post_1.status_code, 200)

        payload_2 = {"macro_symbols": ["TSLA", "NVDA"]}
        res_post_2 = self.client.post("/api/v1/settings/preferences", json=payload_2, headers=self.headers)  # noqa: E501
        self.assertEqual(res_post_2.status_code, 200)

        res_get = self.client.get("/api/v1/settings/preferences", headers=self.headers)
        self.assertEqual(res_get.status_code, 200, f"GET preferences failed: {res_get.json()}")
        # 💡 响应结构: envelope.data.data.macro_symbols (middleware 包一层 + 路由自身 data 字段)
        self.assertEqual(res_get.json()["data"]["data"]["macro_symbols"], ["TSLA", "NVDA"])
