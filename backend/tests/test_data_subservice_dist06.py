"""
DIST-06: data_subservice yfinance 核心逻辑迁移 — 单元测试
==========================================================

验证:
  1. YFinanceWorker 初始化 (YF_ROUTER_ENABLED 强制 false)
  2. start/stop 生命周期 (daemon 任务启动/取消)
  3. get_health 健康检查
  4. 数据接口代理 (fetch/batched_quote/tech_indicators/search)
  5. main.py 集成 (lifespan 中 worker 启动/停止, 端点反映 worker 状态)
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────
#  1. YFinanceWorker 初始化
# ─────────────────────────────────────────


class TestYFinanceWorkerInit:
    """验证 YFinanceWorker 初始化"""

    def test_forces_router_disabled(self):
        """初始化时应强制 YF_ROUTER_ENABLED=false"""
        with (
            patch.dict(os.environ, {"YF_ROUTER_ENABLED": "true"}),
            patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls,
        ):
            mock_cls.return_value = MagicMock()

            from data_subservice.yfinance_worker import YFinanceWorker

            YFinanceWorker()

            assert os.environ["YF_ROUTER_ENABLED"] == "false"
            mock_cls.assert_called_once()

    def test_creates_yfinance_service(self):
        """应创建 YFinanceService 实例"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            assert worker.service is mock_svc
            assert worker._started is False
            assert worker._daemon_task is None


# ─────────────────────────────────────────
#  2. start/stop 生命周期
# ─────────────────────────────────────────


class TestYFinanceWorkerLifecycle:
    """验证 worker 启动/停止流程"""

    @pytest.mark.asyncio
    async def test_start_creates_daemon_task(self):
        """start() 应创建 macro_data_daemon 后台任务"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.macro_data_daemon = AsyncMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()
            await worker.start()

            assert worker._started is True
            assert worker._daemon_task is not None
            assert not worker._daemon_task.done()

            # 清理
            worker._daemon_task.cancel()
            try:
                await worker._daemon_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """重复 start() 应跳过"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.macro_data_daemon = AsyncMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            await worker.start()
            first_task = worker._daemon_task

            await worker.start()  # 第二次应跳过
            assert worker._daemon_task is first_task

            # 清理
            worker._daemon_task.cancel()
            try:
                await worker._daemon_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_cancels_daemon_and_closes_service(self):
        """stop() 应取消 daemon 任务并关闭 service"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.macro_data_daemon = AsyncMock()
            mock_svc.close = MagicMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()
            await worker.start()

            task = worker._daemon_task
            assert not task.done()

            await worker.stop()

            # daemon 应被取消
            assert task.done()
            assert task.cancelled()
            # service.close() 应被调用
            mock_svc.close.assert_called_once()
            assert worker._started is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """未启动时 stop() 应安全执行"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.close = MagicMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            await worker.stop()  # 不应抛异常
            mock_svc.close.assert_called_once()


# ─────────────────────────────────────────
#  3. 健康检查
# ─────────────────────────────────────────


class TestYFinanceWorkerHealth:
    """验证 worker 健康检查"""

    def test_get_health_returns_status(self):
        """get_health() 应返回 service 状态 + daemon_running"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.get_health_status.return_value = {
                "name": "Yahoo Finance",
                "status": "healthy",
                "cooldown_remaining": 0,
                "message": "正常",
            }
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            health = worker.get_health()
            assert health["name"] == "Yahoo Finance"
            assert health["status"] == "healthy"
            assert health["daemon_running"] is False

    @pytest.mark.asyncio
    async def test_get_health_daemon_running(self):
        """daemon 运行时 daemon_running 应为 True"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.macro_data_daemon = AsyncMock()
            mock_svc.get_health_status.return_value = {"status": "healthy"}
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()
            await worker.start()

            health = worker.get_health()
            assert health["daemon_running"] is True

            # 清理
            worker._daemon_task.cancel()
            try:
                await worker._daemon_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_is_daemon_running_property(self):
        """is_daemon_running 属性应反映 daemon 状态"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.macro_data_daemon = AsyncMock()
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            assert worker.is_daemon_running is False

            await worker.start()
            assert worker.is_daemon_running is True

            worker._daemon_task.cancel()
            try:
                await worker._daemon_task
            except asyncio.CancelledError:
                pass


# ─────────────────────────────────────────
#  4. 数据接口代理
# ─────────────────────────────────────────


class TestYFinanceWorkerDataAPI:
    """验证 worker 数据接口正确代理到 YFinanceService"""

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_service(self):
        """fetch() 应代理到 service.fetch_yf_data()"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.fetch_yf_data = AsyncMock(return_value=(True, {"Close": [100]}, ""))
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            result = await worker.fetch("AAPL", "history", ttl=600, period="5d")
            assert result["success"] is True
            assert result["data"] == {"Close": [100]}
            mock_svc.fetch_yf_data.assert_awaited_once_with("AAPL", "history", ttl=600, period="5d")

    @pytest.mark.asyncio
    async def test_batched_quote_delegates(self):
        """batched_quote() 应代理到 service.get_batched_quote()"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.get_batched_quote = AsyncMock(return_value={"status": "success", "ticker": "AAPL"})
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            result = await worker.batched_quote("AAPL", req_type="quote")
            assert result["status"] == "success"
            mock_svc.get_batched_quote.assert_awaited_once_with("AAPL", req_type="quote")

    @pytest.mark.asyncio
    async def test_tech_indicators_delegates(self):
        """tech_indicators() 应代理到 service.get_tech_indicators()"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.get_tech_indicators = AsyncMock(return_value={"status": "success", "data": {}})
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            result = await worker.tech_indicators("AAPL", rsi_period=14)
            assert result["status"] == "success"
            mock_svc.get_tech_indicators.assert_awaited_once_with("AAPL", rsi_period=14)

    @pytest.mark.asyncio
    async def test_search_delegates(self):
        """search() 应代理到 service.search_tickers()"""
        with patch("data_subservice.yfinance_worker.YFinanceService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.search_tickers = AsyncMock(return_value={"status": "success", "data": [{"symbol": "AAPL"}]})
            mock_cls.return_value = mock_svc

            from data_subservice.yfinance_worker import YFinanceWorker

            worker = YFinanceWorker()

            result = await worker.search("Apple")
            assert result["status"] == "success"
            assert len(result["data"]) == 1
            mock_svc.search_tickers.assert_awaited_once_with("Apple")


# ─────────────────────────────────────────
#  5. main.py 集成测试
# ─────────────────────────────────────────


class TestMainIntegration:
    """验证 main.py 中 worker 集成"""

    @pytest.mark.asyncio
    async def test_lifespan_starts_worker_when_yfinance_in_capabilities(self):
        """当 DS_CAPABILITIES 包含 yfinance 时，lifespan 应启动 worker"""
        import data_subservice.main as mod

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)
        mock_registry.deregister = AsyncMock(return_value=True)

        fake_redis = MagicMock()
        fake_redis.ping = AsyncMock(return_value=True)
        fake_redis.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        mock_worker = MagicMock()
        mock_worker.start = AsyncMock()
        mock_worker.stop = AsyncMock()
        mock_worker.is_daemon_running = True
        mock_worker.get_health.return_value = {"status": "healthy", "daemon_running": True}

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_CAPABILITIES", ["yfinance"]),
            patch.object(mod, "YFinanceWorker", return_value=mock_worker),
        ):
            async with mod.lifespan(mod.app):
                # worker 应已启动
                mock_worker.start.assert_awaited_once()

            # worker 应已停止
            mock_worker.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_skips_worker_when_no_yfinance(self):
        """当 DS_CAPABILITIES 不包含 yfinance 时，不应启动 worker"""
        import data_subservice.main as mod

        # 重置前一个测试可能残留的状态
        mod._yf_worker = None

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)
        mock_registry.deregister = AsyncMock(return_value=True)

        fake_redis = MagicMock()
        fake_redis.ping = AsyncMock(return_value=True)
        fake_redis.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_CAPABILITIES", ["akshare"]),
        ):
            async with mod.lifespan(mod.app):
                assert mod._yf_worker is None

    def test_health_endpoint_includes_daemon_status(self):
        """/health 端点应包含 yfinance_daemon_running"""
        import data_subservice.main as mod

        mock_worker = MagicMock()
        mock_worker.is_daemon_running = True

        with (
            patch.object(mod, "_yf_worker", mock_worker),
            patch.object(mod, "_start_time", 1000.0),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_REGION", "us-west"),
            patch.object(mod, "DS_CAPABILITIES", ["yfinance"]),
        ):
            from fastapi.testclient import TestClient

            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")

            assert resp.status_code == 200
            data = resp.json()
            assert data["yfinance_daemon_running"] is True

    def test_ds_health_endpoint_shows_yfinance_detail(self):
        """/ds/health 端点应显示 yfinance 真实健康信息"""
        import data_subservice.main as mod

        mock_worker = MagicMock()
        mock_worker.get_health.return_value = {
            "name": "Yahoo Finance",
            "status": "healthy",
            "cooldown_remaining": 0,
            "message": "正常",
            "daemon_running": True,
        }

        with (
            patch.object(mod, "_yf_worker", mock_worker),
            patch.object(mod, "_start_time", 1000.0),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_REGION", "us-west"),
            patch.object(mod, "DS_CAPABILITIES", ["yfinance"]),
        ):
            from fastapi.testclient import TestClient

            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/ds/health")

            assert resp.status_code == 200
            data = resp.json()
            assert "yfinance" in data["sources"]
            yf_src = data["sources"]["yfinance"]
            assert yf_src["mode"] == "local_daemon"
            assert yf_src["status"] == "available"
            assert "detail" in yf_src
            assert yf_src["detail"]["daemon_running"] is True

    def test_ds_health_endpoint_degraded_when_unhealthy(self):
        """/ds/health 在 yfinance 不健康时应显示 degraded"""
        import data_subservice.main as mod

        mock_worker = MagicMock()
        mock_worker.get_health.return_value = {
            "name": "Yahoo Finance",
            "status": "circuit_open",
            "cooldown_remaining": 30,
            "message": "限流熔断中",
            "daemon_running": True,
        }

        with (
            patch.object(mod, "_yf_worker", mock_worker),
            patch.object(mod, "_start_time", 1000.0),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_REGION", "us-west"),
            patch.object(mod, "DS_CAPABILITIES", ["yfinance"]),
        ):
            from fastapi.testclient import TestClient

            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/ds/health")

            data = resp.json()
            yf_src = data["sources"]["yfinance"]
            assert yf_src["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_lifespan_handles_worker_init_failure(self):
        """worker 初始化失败时 lifespan 不应崩溃"""
        import data_subservice.main as mod

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)
        mock_registry.deregister = AsyncMock(return_value=True)

        fake_redis = MagicMock()
        fake_redis.ping = AsyncMock(return_value=True)
        fake_redis.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
            patch.object(mod, "DS_CAPABILITIES", ["yfinance"]),
            patch.object(mod, "YFinanceWorker", side_effect=RuntimeError("yfinance 依赖缺失")),
        ):
            # 不应抛异常
            async with mod.lifespan(mod.app):
                pass
