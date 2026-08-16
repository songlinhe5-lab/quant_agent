"""source_router 单元测试 — 验证本地直连 OpenD 路由/降级逻辑。"""

import pytest

from data_subservice.futu_src.data_source import LocalDataSource
from data_subservice.futu_src.source_router import FutuSourceRouter


class _FakeConnMgr:
    def __init__(self, status):
        self.status = status
        self._host = "127.0.0.1"
        self._port = 11111
        self.error_msg = ""


class _FakeService:
    def __init__(self, status):
        self.status = status
        self.conn_mgr = _FakeConnMgr(status)


class TestFutuSourceRouter:
    def test_init_wraps_local_source(self):
        svc = _FakeService("CONNECTED")
        router = FutuSourceRouter(svc)
        assert isinstance(router._local, LocalDataSource)
        assert router.current_mode == "local"

    def test_switch_mode_always_local(self):
        router = FutuSourceRouter(_FakeService("CONNECTED"))
        assert router.switch_mode("remote") == "local"

    def test_status_dict(self):
        router = FutuSourceRouter(_FakeService("CONNECTED"))
        st = router.status()
        assert st["mode"] == "local"
        assert st["local"]["type"] == "local"
        assert st["local"]["connected"] is True

    @pytest.mark.asyncio
    async def test_route_delegates_to_local_handler(self):
        router = FutuSourceRouter(_FakeService("CONNECTED"))
        captured = {}

        async def handler(**kwargs):
            captured.update(kwargs)
            return {"ok": True, "ticker": kwargs.get("ticker")}

        result = await router.route("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler, ticker="HK.00700")
        assert result == {"ok": True, "ticker": "HK.00700"}
        assert captured == {"ticker": "HK.00700"}

    @pytest.mark.asyncio
    async def test_route_returns_unavailable_when_local_returns_none(self):
        # 断开时 LocalDataSource.is_available 为 False，fetch 直接返回 None
        router = FutuSourceRouter(_FakeService("DISCONNECTED"))

        async def handler(**kwargs):
            return {"should": "not be called"}

        result = await router.route("fetch_quote", {}, local_handler=handler)
        assert result["status"] == "error"
        assert "数据源不可用" in result["message"]

    @pytest.mark.asyncio
    async def test_route_returns_unavailable_when_handler_none(self):
        router = FutuSourceRouter(_FakeService("CONNECTED"))
        result = await router.route("fetch_quote", {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_route_handles_handler_exception(self):
        router = FutuSourceRouter(_FakeService("CONNECTED"))

        async def boom(**kwargs):
            raise RuntimeError("boom")

        result = await router.route("fetch_quote", {}, local_handler=boom)
        assert result["status"] == "error"


class TestLocalDataSourceDirect:
    def test_is_available_connected(self):
        ds = LocalDataSource(_FakeService("CONNECTED"))
        assert ds.is_available is True
        assert ds.source_type == "local"

    def test_is_available_disconnected(self):
        ds = LocalDataSource(_FakeService("DISCONNECTED"))
        assert ds.is_available is False

    @pytest.mark.asyncio
    async def test_fetch_none_when_unavailable(self):
        ds = LocalDataSource(_FakeService("DISCONNECTED"))

        async def handler(**kwargs):
            return {"x": 1}

        assert await ds.fetch("a", {}, local_handler=handler) is None

    @pytest.mark.asyncio
    async def test_fetch_none_when_no_handler(self):
        ds = LocalDataSource(_FakeService("CONNECTED"))
        assert await ds.fetch("a", {}) is None

    @pytest.mark.asyncio
    async def test_fetch_returns_handler_result(self):
        ds = LocalDataSource(_FakeService("CONNECTED"))

        async def handler(**kwargs):
            return {"y": 2}

        assert await ds.fetch("a", {}, local_handler=handler) == {"y": 2}

    @pytest.mark.asyncio
    async def test_fetch_catches_handler_error(self):
        ds = LocalDataSource(_FakeService("CONNECTED"))

        async def boom(**kwargs):
            raise ValueError("kaboom")

        assert await ds.fetch("a", {}, local_handler=boom) is None

    def test_status_dict(self):
        ds = LocalDataSource(_FakeService("CONNECTED"))
        st = ds.status()
        assert st["type"] == "local"
        assert st["connected"] is True
        assert st["host"] == "127.0.0.1"
        assert st["port"] == 11111
