import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base, get_db
from backend.main import app

# 1. 配置纯内存的 SQLite 数据库，测试结束后数据自动销毁
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
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

        # 模拟前置流程：注册一个测试用户
        self.client.post(
            "i/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "testpassword",
            },
        )

        # 模拟前置流程：登录并获取 Token
        response = self.client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpassword"}
        )
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        # 测试结束后清理表结构
        Base.metadata.drop_all(bind=engine)

    def test_create_and_update_preferences(self):
        payload_1 = {"macro_symbols": ["AAPL", "MSFT", "GOOGL"]}
        res_post_1 = self.client.post(
            "/api/preferences/me", json=payload_1, headers=self.headers
        )  # noqa: E501
        self.assertEqual(res_post_1.status_code, 200)

        payload_2 = {"macro_symbols": ["TSLA", "NVDA"]}
        res_post_2 = self.client.post(
            "/api/preferences/me", json=payload_2, headers=self.headers
        )  # noqa: E501
        self.assertEqual(res_post_2.status_code, 200)

        res_get = self.client.get("/api/preferences/me", headers=self.headers)
        self.assertEqual(res_get.json()["macro_symbols"], ["TSLA", "NVDA"])
