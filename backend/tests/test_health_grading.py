"""
ARCH-05: 健康检查分级 (liveness / readiness / deep) 测试

- /api/v1/health         → 纯 liveness，始终 200（不依赖任何外部依赖，AGENTS §10.4）
- /api/v1/health/live    → 存活探针，200
- /api/v1/health/ready   → 就绪探针，Redis + PG + 至少一数据源连通才 200，否则 503
- /api/v1/health/deep    → 全链路诊断，含 WS 连接数 / 线程池 / 事件循环 lag 等

注：应用层统一响应包装为 {"code","msg","data","ts"}，各端点真实载荷在 data 字段内。
"""

from fastapi.testclient import TestClient


def _pg_ok(*_args, **_kwargs):
    async def _impl():
        return (True, "connected")

    return _impl()


def _pg_down(*_args, **_kwargs):
    async def _impl():
        return (False, "disconnected (OperationalError)")

    return _impl()


def _ds_ok(*_args, **_kwargs):
    async def _impl():
        return (True, {"market_gateway": "CONNECTED"})

    return _impl()


async def _health_snapshot_ok(*_args, **_kwargs):
    return {
        "status": "healthy",
        "components": {
            "redis": "connected",
            "futu": "CONNECTED",
            "asyncio_thread_pool": {},
            "fastapi_thread_pool": {},
        },
    }


def test_health_liveness_always_200(test_client: TestClient, monkeypatch):
    """/api/v1/health 为纯 liveness：即使 Redis 断开也应 200 (AGENTS §10.4)"""
    import backend.routers.system_health as sh

    async def _boom(*_a, **_k):
        raise RuntimeError("redis is dead")

    # 即使 Redis ping 抛错，liveness 端点也不得依赖它
    monkeypatch.setattr(sh.redis_client, "ping", _boom)
    resp = test_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "healthy"


def test_health_live_endpoint(test_client: TestClient):
    resp = test_client.get("/api/v1/health/live")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "alive"
    assert "uptime_seconds" in body
    assert "timestamp" in body


def test_health_ready_ok(test_client: TestClient, monkeypatch):
    import backend.routers.system_health as sh

    monkeypatch.setattr(sh, "_check_postgres", _pg_ok)
    monkeypatch.setattr(sh, "_check_data_sources", _ds_ok)
    resp = test_client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "ready"
    assert body["checks"]["redis"] == "connected"
    assert body["checks"]["postgres"] == "connected"


def test_health_ready_503_when_pg_down(test_client: TestClient, monkeypatch):
    import backend.routers.system_health as sh

    monkeypatch.setattr(sh, "_check_postgres", _pg_down)
    monkeypatch.setattr(sh, "_check_data_sources", _ds_ok)
    resp = test_client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()["data"]
    assert body["status"] == "not_ready"
    assert "disconnected" in body["checks"]["postgres"]


def test_health_deep_diagnostics(test_client: TestClient, monkeypatch):
    import backend.app.system_app as system_app
    import backend.routers.system_health as sh

    monkeypatch.setattr(sh, "_check_postgres", _pg_ok)
    monkeypatch.setattr(sh, "_check_data_sources", _ds_ok)
    monkeypatch.setattr(system_app, "build_health_snapshot", _health_snapshot_ok)
    resp = test_client.get("/api/v1/health/deep")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "healthy"
    # 全链路诊断必含字段
    assert "websocket" in body and "active_connections" in body["websocket"]
    assert "thread_pools" in body
    assert "event_loop_lag_seconds" in body
    assert "collectors" in body
    assert "enabled_collectors" in body["collectors"]
    assert "circuit_breaker_states" in body
    # 事件循环 lag 应为非负浮点
    assert isinstance(body["event_loop_lag_seconds"], (int, float))
    assert body["event_loop_lag_seconds"] >= 0
