import unittest

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


class TestPreferencesAPI(unittest.TestCase):
    def setUp(self):
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

    def tearDown(self):
        # 测试结束后清理表结构
        Base.metadata.drop_all(bind=engine)

    def test_create_and_update_preferences(self):
        # 💡 修复：preferences router prefix="/settings" 挂载在 /api/v1 下，实际路径为 /api/v1/settings/preferences
        payload_1 = {"macro_symbols": ["AAPL", "MSFT", "GOOGL"]}
        res_post_1 = self.client.post("/api/v1/settings/preferences", json=payload_1, headers=self.headers)  # noqa: E501
        self.assertEqual(res_post_1.status_code, 200)

        payload_2 = {"macro_symbols": ["TSLA", "NVDA"]}
        res_post_2 = self.client.post("/api/v1/settings/preferences", json=payload_2, headers=self.headers)  # noqa: E501
        self.assertEqual(res_post_2.status_code, 200)

        res_get = self.client.get("/api/v1/settings/preferences", headers=self.headers)
        self.assertEqual(res_get.status_code, 200, f"GET preferences failed: {res_get.json()}")
        self.assertEqual(res_get.json()["data"]["macro_symbols"], ["TSLA", "NVDA"])
