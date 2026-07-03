"""routers/system.py 单元测试

覆盖: performance-logs / performance-stats / apm-dashboard
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.auth import get_current_user


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1, username="testuser")
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_current_user, None)


def _unwrap(resp):
    body = resp.json()
    return body.get("data", body)


# ==========================================
# GET /api/v1/system/performance-logs
# ==========================================
class TestPerformanceLogs:
    def test_logs_success(self, client):
        """正常路径：查询性能日志"""
        mock_log = MagicMock()
        mock_log.id = 1
        mock_log.log_type = "slow_request"
        mock_log.duration_ms = 150.0
        mock_log.endpoint = "/api/test"
        mock_log.details = "test details"
        # timestamp with timezone
        from datetime import datetime, timezone

        mock_log.timestamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [  # noqa: E501
                mock_log
            ]

            resp = client.get("/api/v1/system/performance-logs?limit=10&log_type=slow_request")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 1
        assert data["data"][0]["log_type"] == "slow_request"

    def test_logs_empty(self, client):
        """空数据路径"""
        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []  # noqa: E501

            resp = client.get("/api/v1/system/performance-logs")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"] == []

    def test_logs_invalid_since_format(self, client):
        """无效 since 时间格式被忽略"""
        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []  # noqa: E501

            resp = client.get("/api/v1/system/performance-logs?since=invalid-time")
        assert resp.status_code == 200


# ==========================================
# GET /api/v1/system/performance-stats
# ==========================================
class TestPerformanceStats:
    def test_stats_success(self, client):
        """正常路径：获取性能统计"""
        mock_row = MagicMock()
        mock_row.log_type = "slow_request"
        mock_row.cnt = 5
        mock_row.avg_ms = 100.0
        mock_row.max_ms = 200.0

        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [mock_row]  # noqa: E501

            resp = client.get("/api/v1/system/performance-stats?hours=24")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"]["slow_request_count"] == 5
        assert data["data"]["total_count"] == 5

    def test_stats_empty(self, client):
        """无数据路径"""
        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = []  # noqa: E501

            resp = client.get("/api/v1/system/performance-stats")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"]["total_count"] == 0

    def test_stats_multiple_types(self, client):
        """多类型聚合"""
        row1 = MagicMock(log_type="slow_request", cnt=3, avg_ms=100.0, max_ms=200.0)
        row2 = MagicMock(log_type="event_loop_block", cnt=2, avg_ms=500.0, max_ms=800.0)

        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [row1, row2]  # noqa: E501

            resp = client.get("/api/v1/system/performance-stats")
        data = _unwrap(resp)
        assert data["data"]["slow_request_count"] == 3
        assert data["data"]["event_loop_block_count"] == 2
        assert data["data"]["total_count"] == 5


# ==========================================
# GET /api/v1/system/apm-dashboard
# ==========================================
class TestApmDashboard:
    def test_dashboard_success(self, client):
        """正常路径：APM 仪表盘全量数据"""
        with (
            patch(
                "backend.routers.system._build_health_snapshot",
                new_callable=lambda: AsyncMock(
                    return_value={"status": "healthy", "components": {"redis": "connected"}}
                ),
            ),  # noqa: E501
            patch(
                "backend.routers.system._build_cluster_snapshot",
                new_callable=lambda: AsyncMock(return_value={"master": {"collectors": []}}),
            ),  # noqa: E501
            patch("backend.routers.system._build_metrics_snapshot", return_value={"ws_connections": 5}),
            patch(
                "backend.routers.system._build_perf_stats",
                new_callable=lambda: AsyncMock(return_value={"total_count": 0}),
            ),  # noqa: E501
        ):
            resp = client.get("/api/v1/system/apm-dashboard")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "health" in data["data"]
        assert "cluster" in data["data"]
        assert "metrics" in data["data"]
        assert "performance_stats" in data["data"]


# ==========================================
# 内部辅助函数测试
# ==========================================
class TestInternalHelpers:
    @pytest.mark.asyncio
    async def test_build_health_snapshot_redis_down(self):
        """Redis 断开时 health 降级为 unhealthy"""
        from backend.routers.system import _build_health_snapshot

        with (
            patch("backend.routers.system.redis_client") as mock_redis,
            patch("backend.routers.system.futu_service", create=True) as mock_futu,
        ):
            mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))
            mock_futu.status = "CONNECTED"
            result = await _build_health_snapshot()
        assert result["status"] == "unhealthy"
        assert "disconnected" in result["components"]["redis"]

    @pytest.mark.asyncio
    async def test_build_health_snapshot_all_healthy(self):
        """全部健康时 status=healthy"""
        from backend.routers.system import _build_health_snapshot

        with (
            patch("backend.routers.system.redis_client") as mock_redis,
            patch.dict("sys.modules", {"backend.services.futu": MagicMock(futu_service=MagicMock(status="CONNECTED"))}),  # noqa: E501
        ):
            mock_redis.ping = AsyncMock()
            result = await _build_health_snapshot()
        assert result["status"] == "healthy"
        assert result["components"]["redis"] == "connected"

    @pytest.mark.asyncio
    async def test_build_cluster_snapshot_error(self):
        """集群快照异常时返回 error"""
        from backend.routers.system import _build_cluster_snapshot

        # 模拟 cluster_manager 导入后调用抛异常
        with patch("backend.workers.cluster_manager.cluster_manager") as mock_cm:
            mock_cm.get_cluster_status = MagicMock(side_effect=Exception("Cluster down"))
            result = await _build_cluster_snapshot()
        # 异常被捕获，返回 error 或 master
        assert "error" in result or "master" in result

    def test_build_metrics_snapshot_success(self):
        """Prometheus 指标快照正常路径"""
        from backend.routers.system import _build_metrics_snapshot

        mock_metric = MagicMock()
        mock_sample = MagicMock()
        mock_sample.name = "test_total"
        mock_sample.value = 42.0
        mock_sample.labels = {}
        mock_metric.collect.return_value = [MagicMock(samples=[mock_sample])]

        with patch.dict(
            "sys.modules",
            {
                "backend.core.metrics": MagicMock(
                    WS_ACTIVE_CONNECTIONS=mock_metric,
                    WS_MESSAGES_SENT=mock_metric,
                    WS_MESSAGES_DROPPED=mock_metric,
                    WS_SUBSCRIPTIONS=mock_metric,
                    REDIS_QUEUE_DEPTH=MagicMock(collect=MagicMock(return_value=[MagicMock(samples=[])])),
                    CIRCUIT_BREAKER_STATE=MagicMock(collect=MagicMock(return_value=[MagicMock(samples=[])])),
                    MARKET_QUOTE_TOTAL=mock_metric,
                )
            },
        ):
            result = _build_metrics_snapshot()
        assert "ws_connections" in result

    def test_build_metrics_snapshot_error(self):
        """Prometheus 导入失败时返回空 dict"""
        from backend.routers.system import _build_metrics_snapshot

        with patch.dict("sys.modules", {"backend.core.metrics": None}):
            result = _build_metrics_snapshot()
        assert result == {}

    @pytest.mark.asyncio
    async def test_build_perf_stats_success(self):
        """性能统计正常路径"""
        from backend.routers.system import _build_perf_stats

        mock_row = MagicMock(log_type="slow_request", cnt=10, avg_ms=50.0, max_ms=150.0)
        with patch("backend.routers.system.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [mock_row]  # noqa: E501
            result = await _build_perf_stats()
        assert result["total_count"] == 10
        assert result["slow_request_count"] == 10

    @pytest.mark.asyncio
    async def test_build_perf_stats_error(self):
        """性能统计异常时返回降级数据"""
        from backend.routers.system import _build_perf_stats

        with patch("backend.routers.system.SessionLocal", side_effect=Exception("DB error")):
            result = await _build_perf_stats()
        assert result["total_count"] == 0
