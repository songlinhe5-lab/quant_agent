"""
Futu 数据源抽象层单元测试

覆盖：
- LocalDataSource 基本行为
- FutuSourceRouter 本地路由
- ConnectionManager.switch_host 运行时切换
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.futu.data_source import LocalDataSource
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
# FutuSourceRouter
# ---------------------------------------------------------------------------
class TestFutuSourceRouter:
    """FutuSourceRouter 路由器测试"""

    def _make_router(self):
        """创建测试用路由器"""
        svc = MagicMock()
        svc.status = "DISCONNECTED"
        svc.conn_mgr._host = "127.0.0.1"
        svc.conn_mgr._port = 11111
        svc.conn_mgr.status = "DISCONNECTED"
        svc.conn_mgr.error_msg = ""
        return FutuSourceRouter(svc)

    def test_mode_is_local(self):
        """模式始终为 local"""
        router = self._make_router()
        assert router.current_mode == "local"

    def test_switch_mode_returns_local(self):
        """switch_mode 始终返回 local"""
        router = self._make_router()
        assert router.switch_mode("remote") == "local"
        assert router.switch_mode("auto") == "local"

    @pytest.mark.asyncio
    async def test_local_handler_called(self):
        """本地可用时调用 handler"""
        router = self._make_router()
        router._local._svc.status = "CONNECTED"

        handler = AsyncMock(return_value={"status": "success", "data": "test"})
        result = await router.route("fetch_quote", {"ticker": "HK.00700"}, local_handler=handler, ticker="HK.00700")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_local_unavailable(self):
        """本地不可用时返回错误"""
        router = self._make_router()
        router._local._svc.status = "DISCONNECTED"

        handler = AsyncMock()
        result = await router.route("fetch_quote", {}, local_handler=handler)
        assert result["status"] == "error"

    def test_status(self):
        """status 返回完整状态"""
        router = self._make_router()
        s = router.status()
        assert s["mode"] == "local"
        assert "local" in s


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
