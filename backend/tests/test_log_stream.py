"""FE-DEBUG-01 日志流路由测试（进程内环形缓冲 + 增量聚合接口）。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core import log_buffer
from backend.main import app


@pytest.fixture(autouse=True)
def _fresh_buffer(monkeypatch):
    """每个用例使用独立 ring buffer，避免用例间游标/条目污染。"""
    buf = log_buffer.RingBuffer(capacity=50)
    monkeypatch.setattr(log_buffer, "ring_buffer", buf)
    from backend.routers import log_stream

    monkeypatch.setattr(log_stream, "ring_buffer", buf)
    return buf


class TestRingBuffer:
    def test_append_recent_and_last_id(self, _fresh_buffer):
        buf = _fresh_buffer
        buf.append("INFO", "app", "hello")
        buf.append("ERROR", "app", "boom")
        assert buf.last_id == 2
        entries = buf.recent(after_id=0)
        assert [e["message"] for e in entries] == ["hello", "boom"]
        # 增量游标
        delta = buf.recent(after_id=1)
        assert len(delta) == 1 and delta[0]["message"] == "boom"
        # 条目字段完整
        assert set(delta[0].keys()) == {"id", "ts", "level", "name", "message"}

    def test_capacity_eviction(self):
        buf = log_buffer.RingBuffer(capacity=5)
        for i in range(10):
            buf.append("INFO", "app", f"msg-{i}")
        assert buf.last_id == 10
        entries = buf.recent(after_id=0)
        assert len(entries) == 5
        assert entries[0]["message"] == "msg-5"  # 最旧 5 条被淘汰

    def test_handler_strips_rich_markup(self, _fresh_buffer):
        buf = _fresh_buffer
        handler = log_buffer.RingBufferHandler(buf)
        record = MagicMock()
        record.getMessage.return_value = "[cyan]colored[/cyan] plain"
        handler.emit(record)
        assert buf.recent()[0]["message"] == "colored plain"


class TestLogStreamRouter:
    def _client(self):
        return TestClient(app)

    def test_recent_no_auth_ok(self):
        # 测试环境已旁路鉴权（conftest），直接调用应 200
        _fresh = None
        with patch.object(log_buffer, "ring_buffer") as _:
            pass  # fixture 已替换
        res = self._client().get("/api/v1/logs/stream/recent")
        assert res.status_code == 200
        data = res.json()["data"]
        assert "last_id" in data and isinstance(data["entries"], list)

    def test_recent_incremental(self, _fresh_buffer):
        _fresh_buffer.append("INFO", "app", "one")
        client = self._client()
        first = client.get("/api/v1/logs/stream/recent").json()["data"]
        assert len(first["entries"]) == 1
        _fresh_buffer.append("WARN", "app", "two")
        second = client.get("/api/v1/logs/stream/recent", params={"after": first["last_id"]}).json()["data"]
        assert [e["message"] for e in second["entries"]] == ["two"]

    def test_nodes_empty_when_router_unconfigured(self, _fresh_buffer):
        with patch(
            "backend.services.datasource.router.data_source_router.get_health_status",
            new=AsyncMock(return_value={"router_enabled": False, "nodes": {}}),
        ):
            res = self._client().get("/api/v1/logs/stream/nodes")
        assert res.status_code == 200
        body = res.json()["data"]
        assert body["total"] == 0 and body["nodes"] == []

    def test_nodes_dedup_by_url(self, _fresh_buffer):
        fake_status = {
            "router_enabled": True,
            "nodes": {
                "yf_primary": {"name": "yf_primary", "url": "http://localhost:8001", "status": "healthy"},
                "futu_master": {"name": "futu_master", "url": "http://localhost:8001", "status": "healthy"},
                "yf_backup_1": {"name": "yf_backup_1", "url": "http://yf-b:8001", "status": "unknown"},
            },
        }
        with patch(
            "backend.services.datasource.router.data_source_router.get_health_status",
            new=AsyncMock(return_value=fake_status),
        ):
            res = self._client().get("/api/v1/logs/stream/nodes")
        nodes = res.json()["data"]["nodes"]
        assert len(nodes) == 2
        local = [n for n in nodes if "localhost" in n["url"]][0]
        assert sorted(local["aliases"]) == ["futu_master", "yf_primary"]
        assert local["online"] is True

    @pytest.mark.asyncio
    async def test_summary_aggregates_nodes(self, _fresh_buffer):
        from backend.routers import log_stream

        _fresh_buffer.append("INFO", "app", "main-log")
        fake_node_body = {
            "code": 0,
            "data": {
                "last_id": 7,
                "entries": [{"id": 7, "ts": "t", "level": "WARN", "name": "yf", "message": "node-log"}],
            },
        }
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json = MagicMock(return_value=fake_node_body)

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.get = AsyncMock(return_value=fake_resp)

        node_list = [{"url": "http://localhost:8001", "name": "s1", "aliases": ["yf_primary"], "online": True}]

        with (
            patch.object(log_stream, "_collect_nodes", new=AsyncMock(return_value=node_list)),
            patch.object(log_stream.httpx, "AsyncClient", return_value=fake_client),
        ):
            res = self._client().get("/api/v1/logs/stream/summary", params={"after": 0})

        assert res.status_code == 200
        data = res.json()["data"]
        # 主服务日志
        assert [e["message"] for e in data["main"]["entries"]] == ["main-log"]
        # 节点日志聚合
        assert data["nodes"][0]["status"] == "ok"
        assert data["nodes"][0]["entries"][0]["message"] == "node-log"
        assert data["nodes"][0]["name"] == "s1"

    @pytest.mark.asyncio
    async def test_summary_node_unreachable_degraded(self, _fresh_buffer):
        from backend.routers import log_stream

        async def _boom(url: str, after: int):
            raise RuntimeError("connection refused")

        node_list = [{"url": "http://127.0.0.1:9", "name": "dead", "aliases": [], "online": False}]
        with (
            patch.object(log_stream, "_collect_nodes", new=AsyncMock(return_value=node_list)),
            patch.object(log_stream, "_fetch_node_recent", new=_boom),
        ):
            res = self._client().get("/api/v1/logs/stream/summary")

        node = res.json()["data"]["nodes"][0]
        assert node["status"] == "error"
        assert "connection refused" in node["error"]
        assert node["entries"] == []

    def test_recent_requires_auth_in_prod(self, _fresh_buffer):
        """生产环境（无 bypass）未带 token 应 401 —— 验证路由确实声明了 get_current_user 依赖。"""
        import inspect

        from backend.routers import log_stream

        route = [r for r in log_stream.router.routes if getattr(r, "path", "").endswith("/recent")][0]
        sig = inspect.signature(route.endpoint)
        defaults = {name: p.default for name, p in sig.parameters.items()}
        # endpoint 参数默认值是 Depends(get_current_user)
        assert any(
            type(d).__name__ == "Depends"
            and getattr(getattr(d, "dependency", None), "__name__", "") == "get_current_user"
            for d in defaults.values()
        )
