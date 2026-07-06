"""
Futu 数据源抽象层单元测试

覆盖：
- LocalDataSource / RemoteDataSource 基本行为
- FutuSourceRouter 三种模式路由
- ConnectionManager.switch_host 运行时切换
- FutuAdmin API 端点
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.futu.data_source import LocalDataSource, RemoteDataSource
from backend.services.futu.source_router import FutuSourceRouter


# ---------------------------------------------------------------------------
# LocalDataSource
# ---------------------------------------------------------------------------
class TestLocalDataSource:
    """LocalDataSource 测试"""

    def test_source_type(self):
        """类型标识为 local"""
        svc = MagicMock()
        ds = LocalDataSource(svc)
        assert ds.source_type == "local"

    def test_is_available_connected(self):
        """连接可用时返回 True"""
        svc = MagicMock()
        svc.status = "CONNECTED"
        ds = LocalDataSource(svc)
        assert ds.is_available is True

    def test_is_available_disconnected(self):
        """未连接时返回 False"""
        svc = MagicMock()
        svc.status = "DISCONNECTED"
        ds = LocalDataSource(svc)
        assert ds.is_available is False

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """fetch 成功时调用 handler"""
        svc = MagicMock()
        svc.status = "CONNECTED"
        ds = LocalDataSource(svc)

        handler = AsyncMock(return_value={"status": "success", "price": 100.0})
        result = await ds.fetch("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler, ticker="HK.00700")
        assert result == {"status": "success", "price": 100.0}
        handler.assert_called_once_with(ticker="HK.00700")

    @pytest.mark.asyncio
    async def test_fetch_not_connected(self):
        """未连接时 fetch 返回 None"""
        svc = MagicMock()
        svc.status = "DISCONNECTED"
        ds = LocalDataSource(svc)

        handler = AsyncMock()
        result = await ds.fetch("fetch_quote", {}, local_handler=handler)
        assert result is None
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_handler_exception(self):
        """handler 异常时返回 None"""
        svc = MagicMock()
        svc.status = "CONNECTED"
        ds = LocalDataSource(svc)

        handler = AsyncMock(side_effect=Exception("connection lost"))
        result = await ds.fetch("fetch_quote", {}, local_handler=handler)
        assert result is None

    def test_status(self):
        """status 返回连接信息"""
        svc = MagicMock()
        svc.status = "CONNECTED"
        svc.conn_mgr._host = "127.0.0.1"
        svc.conn_mgr._port = 11111
        svc.conn_mgr.status = "CONNECTED"
        svc.conn_mgr.error_msg = ""
        ds = LocalDataSource(svc)
        s = ds.status()
        assert s["type"] == "local"
        assert s["connected"] is True
        assert s["host"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# RemoteDataSource
# ---------------------------------------------------------------------------
class TestRemoteDataSource:
    """RemoteDataSource 测试"""

    def test_source_type(self):
        """类型标识为 remote"""
        ds = RemoteDataSource()
        assert ds.source_type == "remote"

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """fetch 通过 ClusterManager 获取数据"""
        ds = RemoteDataSource()
        mock_result = {
            "data": {"status": "success", "price": 100.0},
            "source_node": "slave-1",
        }

        with patch(
            "backend.services.futu.data_source.RemoteDataSource._RemoteDataSource__class__",
            create=True,
        ):
            mock_cm = MagicMock()
            mock_cm.call_collector = AsyncMock(return_value=mock_result)
            mock_cm.get_available_nodes = MagicMock(return_value=[MagicMock()])

            with patch("backend.workers.cluster_manager.cluster_manager", mock_cm):
                result = await ds.fetch("fetch_quote", {"ticker": "HK.00700"})
                assert result is not None
                assert result["price"] == 100.0

    @pytest.mark.asyncio
    async def test_fetch_connection_error_returns_none(self):
        """连接失败类错误返回 None (触发降级)"""
        ds = RemoteDataSource()
        mock_result = {
            "data": {"status": "error", "message": "Futu OpenD 未连接"},
        }

        mock_cm = MagicMock()
        mock_cm.call_collector = AsyncMock(return_value=mock_result)

        with patch("backend.workers.cluster_manager.cluster_manager", mock_cm):
            result = await ds.fetch("fetch_quote", {"ticker": "HK.00700"})
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_prevents_recursion(self):
        """防递归重入: _in_dispatch 时直接返回 None"""
        ds = RemoteDataSource()
        ds._in_dispatch = True
        result = await ds.fetch("fetch_quote", {"ticker": "HK.00700"})
        assert result is None


# ---------------------------------------------------------------------------
# FutuSourceRouter
# ---------------------------------------------------------------------------
class TestFutuSourceRouter:
    """FutuSourceRouter 路由器测试"""

    def _make_router(self, mode="auto"):
        """创建测试用路由器"""
        svc = MagicMock()
        svc.status = "DISCONNECTED"
        svc.conn_mgr._host = "127.0.0.1"
        svc.conn_mgr._port = 11111
        svc.conn_mgr.status = "DISCONNECTED"
        svc.conn_mgr.error_msg = ""

        with patch.dict("os.environ", {"FUTU_SOURCE_MODE": mode}):
            router = FutuSourceRouter(svc)
        return router

    def test_default_mode(self):
        """默认模式为 auto"""
        router = self._make_router()
        assert router.current_mode == "auto"

    def test_invalid_mode_fallback(self):
        """无效模式回退到 auto"""
        svc = MagicMock()
        svc.status = "DISCONNECTED"
        svc.conn_mgr._host = "127.0.0.1"
        svc.conn_mgr._port = 11111
        svc.conn_mgr.status = "DISCONNECTED"
        svc.conn_mgr.error_msg = ""
        with patch.dict("os.environ", {"FUTU_SOURCE_MODE": "invalid"}):
            router = FutuSourceRouter(svc)
        assert router.current_mode == "auto"

    def test_switch_mode(self):
        """运行时切换模式"""
        router = self._make_router()
        assert router.current_mode == "auto"

        router.switch_mode("local")
        assert router.current_mode == "local"

        router.switch_mode("remote")
        assert router.current_mode == "remote"

    def test_switch_mode_invalid(self):
        """切换到无效模式抛异常"""
        router = self._make_router()
        with pytest.raises(ValueError, match="无效模式"):
            router.switch_mode("bogus")

    @pytest.mark.asyncio
    async def test_local_mode_uses_local_handler(self):
        """local 模式下调用本地 handler"""
        router = self._make_router("local")
        router._local._svc.status = "CONNECTED"

        handler = AsyncMock(return_value={"status": "success", "data": "test"})
        result = await router.route("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler, ticker="HK.00700")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_local_mode_unavailable(self):
        """local 模式下本地不可用返回错误"""
        router = self._make_router("local")
        router._local._svc.status = "DISCONNECTED"

        handler = AsyncMock()
        result = await router.route("fetch_quote", {}, local_handler=handler)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_remote_mode_uses_remote(self):
        """remote 模式下调用远程数据源"""
        router = self._make_router("remote")

        router._remote.fetch = AsyncMock(return_value={"status": "success", "data": "remote"})
        result = await router.route("fetch_quote", {"ticker": "HK.00700"})
        assert result["status"] == "success"
        assert result["data"] == "remote"

    @pytest.mark.asyncio
    async def test_auto_mode_local_first(self):
        """auto 模式下本地优先"""
        router = self._make_router("auto")
        router._local._svc.status = "CONNECTED"

        handler = AsyncMock(return_value={"status": "success", "source": "local"})
        result = await router.route("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler, ticker="HK.00700")
        assert result["source"] == "local"

    @pytest.mark.asyncio
    async def test_auto_mode_fallback_to_remote(self):
        """auto 模式下本地失败降级到远程"""
        router = self._make_router("auto")
        router._local._svc.status = "DISCONNECTED"

        router._remote.fetch = AsyncMock(return_value={"status": "success", "source": "remote"})
        handler = AsyncMock()
        result = await router.route("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler)
        assert result["source"] == "remote"

    def test_status(self):
        """status 返回完整状态"""
        router = self._make_router("auto")
        s = router.status()
        assert "mode" in s
        assert "local" in s
        assert "remote" in s
        assert s["mode"] == "auto"


# ---------------------------------------------------------------------------
# ConnectionManager.switch_host
# ---------------------------------------------------------------------------
class TestConnectionManagerSwitchHost:
    """ConnectionManager.switch_host 测试"""

    def test_switch_host_same_address(self):
        """切换到相同地址返回 unchanged"""
        from backend.services.futu.connection_manager import ConnectionManager

        with patch.dict("os.environ", {"FUTU_HOST": "127.0.0.1", "FUTU_PORT": "11111"}):
            cm = ConnectionManager()

        result = cm.switch_host("127.0.0.1", 11111)
        assert result["status"] == "unchanged"

    def test_switch_host_new_address(self):
        """切换到新地址触发重连"""
        from backend.services.futu.connection_manager import ConnectionManager

        with patch.dict("os.environ", {"FUTU_HOST": "127.0.0.1", "FUTU_PORT": "11111"}):
            cm = ConnectionManager()

        # 模拟已连接状态，这样 switch_host 会先 close
        cm.status = "CONNECTED"
        cm.close = MagicMock()
        cm.connect = MagicMock()

        result = cm.switch_host("1.2.3.4", 11111)
        assert result["old_host"] == "127.0.0.1"
        assert result["new_host"] == "1.2.3.4"
        assert cm._host == "1.2.3.4"
        cm.close.assert_called_once()
        cm.connect.assert_called_once()

    def test_target_property(self):
        """target 属性返回当前地址"""
        from backend.services.futu.connection_manager import ConnectionManager

        with patch.dict("os.environ", {"FUTU_HOST": "10.0.0.1", "FUTU_PORT": "11112"}):
            cm = ConnectionManager()
        assert cm.target == "10.0.0.1:11112"
