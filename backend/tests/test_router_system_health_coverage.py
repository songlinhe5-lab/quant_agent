"""补充 routers/system_health.py 遗漏分支的覆盖率测试。

响应被自定义处理器统一包裹为 {"code","msg","data":{...}}, 故断言取 resp.json()["data"]。

分支控制沿用 test_health_grading.py 的 monkeypatch 模式 (setattr sh._check_*),
避免直接 patch 只读的 AsyncEngine.connect。conftest 已 autouse mock
backend.routers.system_health.redis_client。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.routers import system_health as sh


@pytest.fixture
def client(test_client):
    return test_client


# ── /metrics 鉴权 (35-48, 53) ──────────────────────────────────────────────
def test_metrics_auth_ok(client):
    resp = client.get("/metrics", auth=("admin", "admin"))
    assert resp.status_code == 200


def test_metrics_auth_fail(client):
    resp = client.get("/metrics", auth=("bad", "bad"))
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json()["msg"]


def test_health_and_live(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/live").status_code == 200


def test_root_and_mcp(client):
    assert client.get("/").status_code == 200
    assert client.get("/mcp").status_code == 200


def test_monitor_page_404_without_dist(client, monkeypatch):
    monkeypatch.setattr(sh.os.path, "exists", lambda p: False)
    resp = client.get("/monitor")
    assert resp.status_code == 404


def test_cluster_status(client):
    resp = client.get("/api/v1/cluster")
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "standalone"


def test_uptime_kuma_webhook(client):
    with patch(
        "backend.services.notification_service.notification_service.send_alert",
        new=AsyncMock(),
    ):
        down = client.post(
            "/api/v1/webhook/uptime-kuma",
            json={"monitor": {"name": "API"}, "heartbeat": {"status": 0}, "msg": "x"},
        )
        up = client.post(
            "/api/v1/webhook/uptime-kuma",
            json={"monitor": {"name": "API"}, "heartbeat": {"status": 1}},
        )
    assert down.status_code == 200
    assert up.status_code == 200


# ── /health/ready redis 断线 (201-202) ─────────────────────────────────────
def test_health_ready_redis_down(client, monkeypatch):
    monkeypatch.setattr(sh.redis_client, "ping", AsyncMock(side_effect=RuntimeError("down")))
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert "disconnected" in resp.json()["data"]["checks"]["redis"]


# ── /health/ready postgres 断线 (74-79) ────────────────────────────────────
def test_health_ready_postgres_down(client, monkeypatch):
    monkeypatch.setattr(sh, "_check_postgres", AsyncMock(return_value=(False, "disconnected (boom)")))
    monkeypatch.setattr(sh, "_check_data_sources", AsyncMock(return_value=(True, {})))
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert "disconnected" in resp.json()["data"]["checks"]["postgres"]


# ── _check_data_sources: market_gateway CONNECTED (95-98) ──────────────────
def test_data_sources_market_gateway_connected(client, monkeypatch):
    from backend.app import market_data as md_mod

    # 仅验证数据源分支逻辑，真实 PG 由 _check_postgres 隔离（避免测试沙箱无 PG 连通性）
    monkeypatch.setattr(sh, "_check_postgres", AsyncMock(return_value=(True, "connected")))
    monkeypatch.setattr(md_mod.market_data, "status", "CONNECTED")
    resp = client.get("/api/v1/health/deep")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "healthy"
    assert resp.json()["data"]["data_source_detail"]["market_gateway"] == "CONNECTED"


# ── _check_data_sources: 注册表存在 healthy 源 (89-123, 116-117) ───────────
def test_data_sources_via_registry_healthy(client, monkeypatch):
    fake_source = MagicMock()
    fake_source.health = AsyncMock(return_value=MagicMock(healthy=True))
    reg = MagicMock()
    reg.list_names = MagicMock(return_value=["fake"])
    reg.get = MagicMock(return_value=fake_source)

    from backend.app import market_data as md_mod

    # 仅验证注册表 + 数据源分支，真实 PG 由 _check_postgres 隔离（避免测试沙箱无 PG 连通性）
    monkeypatch.setattr(sh, "_check_postgres", AsyncMock(return_value=(True, "connected")))
    monkeypatch.setattr(md_mod.market_data, "status", "UNKNOWN")
    monkeypatch.setattr("backend.services.datasource.datasource_registry", reg)
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"


# ── _check_data_sources: 注册表整体异常 (120-121) ──────────────────────────
def test_data_sources_registry_error(client, monkeypatch):
    from backend.app import market_data as md_mod

    monkeypatch.setattr(md_mod.market_data, "status", "UNKNOWN")
    monkeypatch.setattr(
        "backend.services.datasource.datasource_registry",
        MagicMock(list_names=MagicMock(side_effect=RuntimeError("no registry"))),
    )
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["data"]["status"] == "not_ready"


# ── /health/deep 降级分支 (241, 243) ───────────────────────────────────────
def test_health_deep_degraded_when_postgres_down(client, monkeypatch):
    monkeypatch.setattr(sh, "_check_postgres", AsyncMock(return_value=(False, "disconnected")))
    monkeypatch.setattr(sh, "_check_data_sources", AsyncMock(return_value=(True, {})))
    resp = client.get("/api/v1/health/deep")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "degraded"
