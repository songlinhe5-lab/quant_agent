"""
单元测试：采集器注册表 (workers/collector_registry.py)
测试采集器定义、启用逻辑和守护进程启动
"""

import os
from unittest import mock

import pytest

from backend.workers.collector_registry import COLLECTORS, CollectorDef, get_enabled_collectors, start_collector_daemons


class TestCollectorDef:
    """测试采集器定义数据类"""

    def test_collector_def_creation(self):
        """测试创建采集器定义"""
        cdef = CollectorDef(
            name="test",
            env_var="COLLECTOR_TEST",
            needs_postgres=True,
            description="Test collector",
        )
        assert cdef.name == "test"
        assert cdef.env_var == "COLLECTOR_TEST"
        assert cdef.needs_postgres is True
        assert cdef.description == "Test collector"

    def test_collector_def_defaults(self):
        """测试采集器定义默认值"""
        cdef = CollectorDef(name="test", env_var="COLLECTOR_TEST")
        assert cdef.needs_postgres is False
        assert cdef.description == ""


class TestCollectorsDict:
    """测试采集器字典定义"""

    def test_all_collectors_defined(self):
        """测试所有采集器都已定义"""
        expected_names = ["akshare", "futu", "finnhub", "yfinance"]
        assert set(COLLECTORS.keys()) == set(expected_names)

    def test_collector_metadata(self):
        """测试采集器元数据正确"""
        # AKShare
        akshare = COLLECTORS["akshare"]
        assert akshare.name == "akshare"
        assert akshare.env_var == "COLLECTOR_AKSHARE"
        assert "港股通" in akshare.description

        # Futu
        futu = COLLECTORS["futu"]
        assert futu.name == "futu"
        assert futu.env_var == "COLLECTOR_FUTU"
        assert "Level 2" in futu.description

        # Finnhub
        finnhub = COLLECTORS["finnhub"]
        assert finnhub.name == "finnhub"
        assert finnhub.env_var == "COLLECTOR_FINNHUB"
        assert "内幕交易" in finnhub.description

        # YFinance
        yfinance = COLLECTORS["yfinance"]
        assert yfinance.name == "yfinance"
        assert yfinance.env_var == "COLLECTOR_YFINANCE"
        assert "宏观指标" in yfinance.description

    def test_every_collector_has_factory(self):
        """BE-ARCH-03：插件表必须挂载 factory"""
        for name, cdef in COLLECTORS.items():
            assert callable(cdef.factory), f"{name} missing factory"


class TestGetEnabledCollectors:
    """测试获取启用的采集器列表"""

    def test_no_collectors_enabled(self):
        """测试所有采集器都未启用时返回空列表"""
        with mock.patch.dict(os.environ, {}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == []

    def test_single_collector_enabled(self):
        """测试单个采集器启用"""
        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": "true"}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == ["akshare"]

    def test_multiple_collectors_enabled(self):
        """测试多个采集器启用"""
        with mock.patch.dict(
            os.environ,
            {
                "COLLECTOR_AKSHARE": "true",
                "COLLECTOR_FUTU": "true",
                "COLLECTOR_YFINANCE": "true",
            },
            clear=True,
        ):
            enabled = get_enabled_collectors()
            assert set(enabled) == {"akshare", "futu", "yfinance"}

    def test_case_insensitive_env_var(self):
        """测试环境变量值大小写不敏感"""
        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": "True"}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == ["akshare"]

        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": "TRUE"}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == ["akshare"]

    def test_false_env_var(self):
        """测试 false 值不启用采集器"""
        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": "false"}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == []

        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": "False"}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == []

    def test_empty_env_var(self):
        """测试空环境变量不启用采集器"""
        with mock.patch.dict(os.environ, {"COLLECTOR_AKSHARE": ""}, clear=True):
            enabled = get_enabled_collectors()
            assert enabled == []


@pytest.mark.asyncio
class TestStartCollectorDaemons:
    """测试启动采集器守护进程"""

    async def test_akshare_starts_collector_daemon(self):
        """测试 AKShare 启动采集守护进程 (DIST-07 方案A: Redis 中继)"""
        with (
            mock.patch("asyncio.create_task") as mock_create_task,
            mock.patch("backend.workers.akshare_collector.akshare_collector_daemon"),
        ):
            mock_create_task.return_value = mock.MagicMock()
            tasks = await start_collector_daemons(["akshare"])
            assert len(tasks) == 1
            mock_create_task.assert_called_once()

    async def test_futu_starts_watchdog(self):
        """测试 Futu 启动 watchdog 守护进程"""
        with (
            mock.patch("asyncio.create_task") as mock_create_task,
            mock.patch("backend.services.futu.watchdog.get_watchdog"),
            mock.patch("backend.services.futu_service.futu_service"),
        ):
            mock_create_task.return_value = mock.MagicMock()
            tasks = await start_collector_daemons(["futu"])

            mock_create_task.assert_called_once()
            assert len(tasks) == 1

    async def test_finnhub_master_starts_daemon(self):
        """测试 Finnhub 在 Master 节点启动守护进程"""
        with (
            mock.patch("os.getenv", return_value="master"),
            mock.patch("asyncio.create_task") as mock_create_task,
            mock.patch("backend.services.market_daemon.run_global_daemon"),
        ):
            mock_create_task.return_value = mock.MagicMock()
            tasks = await start_collector_daemons(["finnhub"])

            mock_create_task.assert_called_once()
            assert len(tasks) == 1

    async def test_finnhub_slave_no_daemon(self):
        """测试 Finnhub 在 Slave 节点不启动守护进程"""
        with (
            mock.patch("os.getenv", return_value="slave"),
            mock.patch("backend.workers.collectors.finnhub.print") as mock_print,
        ):
            tasks = await start_collector_daemons(["finnhub"])

            assert tasks == []
            mock_print.assert_called_with("  [finnhub] slave mode: data fetching only, no daemon")

    async def test_yfinance_starts_daemon(self):
        """测试 YFinance 启动宏数据守护进程"""
        with (
            mock.patch("asyncio.create_task") as mock_create_task,
            mock.patch("backend.services.yfinance_service.yf_service") as mock_service,
        ):
            mock_create_task.return_value = mock.MagicMock()
            mock_service.macro_data_daemon = mock.AsyncMock()
            tasks = await start_collector_daemons(["yfinance"])

            mock_create_task.assert_called_once()
            assert len(tasks) == 1

    async def test_unknown_collector_skipped(self):
        """未知采集器名静默跳过"""
        tasks = await start_collector_daemons(["not_a_real_collector"])
        assert tasks == []

    async def test_start_stop_matrix_all_enabled(self):
        """启停矩阵：四个采集器同时启 → stop 全部 cancel"""
        from backend.workers.collector_registry import stop_collector_daemons

        mock_task = mock.MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = mock.MagicMock()

        with (
            mock.patch("asyncio.create_task", return_value=mock_task) as mock_create,
            mock.patch("asyncio.gather", new=mock.AsyncMock(return_value=[])),
            mock.patch("backend.workers.akshare_collector.akshare_collector_daemon"),
            mock.patch("backend.services.futu.watchdog.get_watchdog") as mock_wd,
            mock.patch("backend.services.futu_service.futu_service"),
            mock.patch("backend.services.market_daemon.run_global_daemon"),
            mock.patch("backend.services.yfinance_service.yf_service") as mock_yf,
            mock.patch.dict(os.environ, {"NODE_TYPE": "master"}, clear=False),
        ):
            mock_wd.return_value.start = mock.AsyncMock()
            mock_yf.macro_data_daemon = mock.AsyncMock()

            tasks = await start_collector_daemons(["akshare", "futu", "finnhub", "yfinance"])
            assert len(tasks) == 4
            assert mock_create.call_count == 4

            await stop_collector_daemons(tasks)
            assert mock_task.cancel.call_count == 4
