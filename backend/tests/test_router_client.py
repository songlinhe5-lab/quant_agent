"""
客户端 APM 心跳路由单元测试
覆盖: backend/routers/client.py
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core import models
from backend.core.database import Base, get_db
from backend.main import app


def _unwrap(resp):
    """剥离统一响应封装，返回路由原始 dict"""
    body = resp.json()
    return body.get("data", body)


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


class TestClientHeartbeatRoutes:
    """客户端 APM 心跳路由测试"""

    def setup_method(self):
        app.dependency_overrides[get_db] = override_get_db  # 防止被其他测试文件覆盖
        import backend.routers.client as client_mod

        client_mod._VITALS_COLUMNS_ENSURED = False
        Base.metadata.create_all(bind=engine)

    def teardown_method(self):
        Base.metadata.drop_all(bind=engine)

    def test_receive_heartbeat_success(self):
        """正常路径：心跳上报成功"""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/client/heartbeat",
            json={
                "platform": "flutter",
                "appVersion": "1.0.0",
                "deviceId": "dev-001",
                "fps": 60.0,
                "memoryMb": 128.5,
                "wsLatencyMs": 30,
                "timestamp": 1719500000000,
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "received_at" in data

    def test_receive_heartbeat_with_web_vitals(self):
        """OBS-03: Web 端心跳携带 LCP/CLS/INP/TTFB"""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/client/heartbeat",
            json={
                "platform": "web",
                "appVersion": "0.1.0",
                "deviceId": "web-dev-001",
                "lcpMs": 1320.5,
                "cls": 0.03,
                "inpMs": 88.0,
                "ttfbMs": 110.0,
                "timestamp": 1719500000000,
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "received_at" in data

        db = TestingSessionLocal()
        row = db.query(models.ClientHeartbeat).filter_by(device_id="web-dev-001").one()
        assert row.lcp_ms == 1320.5
        assert row.cls == 0.03
        assert row.inp_ms == 88.0
        assert row.ttfb_ms == 110.0
        db.close()

    def test_heartbeat_stats_success(self):
        """正常路径：获取心跳统计摘要"""
        # 先写入一条心跳
        db = TestingSessionLocal()
        db.add(
            models.ClientHeartbeat(
                platform="flutter",
                app_version="1.0.0",
                device_id="dev-001",
                fps=60.0,
                memory_mb=128.5,
                ws_latency_ms=30,
            )
        )
        db.commit()
        db.close()

        client = TestClient(app)
        resp = client.get("/api/v1/client/heartbeat/stats?minutes=60")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["window_minutes"] == 60
        assert isinstance(data["platforms"], list)

    def test_heartbeat_stats_empty(self):
        """空数据路径：无心跳数据时返回空 platforms"""
        client = TestClient(app)
        resp = client.get("/api/v1/client/heartbeat/stats?minutes=60")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["platforms"] == []
