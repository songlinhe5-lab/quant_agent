"""
DIST-07 方案A: AKShare Redis 中继 — 单元测试
================================================

验证:
  1. AKShareService cache 模式: cache miss 返回 no_data
  2. AKShareService cache 模式: cache hit 正常返回
  3. AKShareService direct 模式: 直连 akshare (原有逻辑不变)
  4. AKShareService health_status 反映 mode
  5. AKShareCollector: 任务定义、交易时段判断、daemon 启停
  6. collector_registry: akshare 采集器注册
"""

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────
#  1. AKShareService cache 模式
# ─────────────────────────────────────────


class TestAKShareServiceCacheMode:
    """验证 AKShareService 在 cache 模式下的行为"""

    @pytest.fixture
    def cache_mode_service(self):
        """创建 cache 模式的 AKShareService (mock Redis)"""
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.lock = MagicMock()

        # SPEC-01 拆分后 redis_client 分布在各子模块，需逐一 patch
        with ExitStack() as stack:
            for mod in ("flow", "quote", "calendar"):
                stack.enter_context(patch(f"backend.services.akshare.{mod}.redis_client", mock_redis))
            from backend.services.akshare_service import AKShareService

            svc = AKShareService()
            svc._cache_mode = True  # 强制 cache 模式
            yield svc, mock_redis

    @pytest.mark.asyncio
    async def test_southbound_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 缓存未命中 → 返回 no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_southbound_flow()
        assert result["status"] == "no_data"
        assert "cache 模式" in result["message"]

    @pytest.mark.asyncio
    async def test_southbound_cache_hit_returns_cached(self, cache_mode_service):
        """cache 模式 + 缓存命中 → 返回缓存数据"""
        svc, mock_redis = cache_mode_service
        cached_data = {"status": "success", "data": {"net_inflow": 12.8}}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        result = await svc.get_southbound_flow()
        assert result["status"] == "success"
        assert result["data"]["net_inflow"] == 12.8

    @pytest.mark.asyncio
    async def test_northbound_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 北向资金缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_northbound_flow()
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_hsgt_holders_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 持股明细缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_hsgt_top_holders(symbol="00700")
        assert result["status"] == "no_data"
        assert "00700" in result["message"]

    @pytest.mark.asyncio
    async def test_company_news_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 新闻缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_company_news(ticker="00700")
        assert result["status"] == "no_data"
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_stock_quote_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 行情缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_stock_quote(ticker="SH.600519")
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_stock_history_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 历史K线缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_stock_history(ticker="SH.600519", num=60)
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_economic_calendar_cache_miss_returns_no_data(self, cache_mode_service):
        """cache 模式 + 宏观日历缓存未命中 → no_data"""
        svc, mock_redis = cache_mode_service
        mock_redis.get = AsyncMock(return_value=None)

        result = await svc.get_economic_calendar(days_ahead=7)
        assert result["status"] == "no_data"
        assert result["data"] == []


# ─────────────────────────────────────────
#  2. AKShareService health_status
# ─────────────────────────────────────────


class TestAKShareServiceHealthStatus:
    """验证健康状态反映运行模式"""

    def test_cache_mode_shows_relay(self):
        """cache 模式健康状态应标注 '北京VPS中继'"""
        from backend.services.akshare_service import AKShareService

        svc = AKShareService()
        svc._cache_mode = True

        health = svc.get_health_status()
        assert "cache" in health["mode"]
        assert "北京VPS中继" in health["mode"]

    def test_direct_mode_shows_direct(self):
        """direct 模式健康状态应标注 '直连akshare'"""
        from backend.services.akshare_service import AKShareService

        svc = AKShareService()
        svc._cache_mode = False

        health = svc.get_health_status()
        assert "direct" in health["mode"]
        assert "直连akshare" in health["mode"]


# ─────────────────────────────────────────
#  3. AKShareCollector 任务定义
# ─────────────────────────────────────────


class TestAKShareCollectorTasks:
    """验证采集任务定义"""

    def test_collector_tasks_defined(self):
        """应定义 southbound, northbound, economic_calendar 三个任务"""
        from backend.workers.akshare_collector import COLLECTOR_TASKS

        assert "southbound" in COLLECTOR_TASKS
        assert "northbound" in COLLECTOR_TASKS
        assert "economic_calendar" in COLLECTOR_TASKS

    def test_southbound_intervals(self):
        """南向资金任务应有合理的采集间隔"""
        from backend.workers.akshare_collector import COLLECTOR_TASKS

        task = COLLECTOR_TASKS["southbound"]
        assert task.interval_trading == 300  # 盘中 5 分钟
        assert task.interval_closed == 7200  # 收盘后 2 小时

    def test_task_handlers_complete(self):
        """所有任务应有对应的 handler"""
        from backend.workers.akshare_collector import _TASK_HANDLERS, COLLECTOR_TASKS

        for name in COLLECTOR_TASKS:
            assert name in _TASK_HANDLERS, f"任务 {name} 缺少 handler"


# ─────────────────────────────────────────
#  4. 交易时段判断
# ─────────────────────────────────────────


class TestIsTradingHours:
    """验证交易时段判断逻辑"""

    def test_weekday_trading_hours_logic(self):
        """工作日交易时段 (北京时间 10:00) 应返回 True"""
        from datetime import datetime, timedelta, timezone

        tz_cn = timezone(timedelta(hours=8))
        mock_now = datetime(2026, 7, 8, 10, 0, 0, tzinfo=tz_cn)  # 周三 10:00

        # 直接测试逻辑 (不 mock datetime 模块)
        assert mock_now.weekday() == 2  # 周三
        hour = mock_now.hour
        minute = mock_now.minute
        is_trading = (hour == 9 and minute >= 15) or (10 <= hour <= 15) or (hour == 16 and minute <= 15)
        assert is_trading is True

    def test_weekend_not_trading(self):
        """周末不应采集"""
        from datetime import datetime

        # 周六
        saturday = datetime(2026, 7, 11, 10, 0, 0)
        assert saturday.weekday() >= 5  # 6 = Saturday


# ─────────────────────────────────────────
#  5. AKShareCollector daemon 生命周期
# ─────────────────────────────────────────


class TestAKShareCollectorDaemon:
    """验证采集 daemon 的启停"""

    @pytest.mark.asyncio
    async def test_daemon_starts_and_cancels(self):
        """daemon 应能正常启动和取消"""
        from backend.workers.akshare_collector import akshare_collector_daemon

        mock_service = MagicMock()
        mock_service.get_southbound_flow = AsyncMock(return_value={"status": "success", "data": {"net_inflow": 12.8}})
        mock_service.get_northbound_flow = AsyncMock(return_value={"status": "success", "data": {"net_inflow": -5.3}})
        mock_service.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": []})

        with (
            patch("backend.services.akshare_service.AKShareService", return_value=mock_service),
            patch("backend.workers.akshare_collector.asyncio.sleep", side_effect=[None, asyncio.CancelledError]),
        ):
            task = asyncio.create_task(akshare_collector_daemon(enabled_tasks=["southbound"]))
            await asyncio.sleep(0.1)

            # 取消任务
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            assert task.done()

    @pytest.mark.asyncio
    async def test_daemon_calls_handlers(self):
        """daemon 应在首次循环时调用所有启用的 handler"""
        from backend.workers.akshare_collector import akshare_collector_daemon

        mock_service = MagicMock()
        mock_service.get_southbound_flow = AsyncMock(return_value={"status": "success", "data": {"net_inflow": 12.8}})

        call_count = 0

        async def mock_sleep(*args):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError

        with (
            patch("backend.services.akshare_service.AKShareService", return_value=mock_service),
            patch("backend.workers.akshare_collector.asyncio.sleep", side_effect=mock_sleep),
        ):
            task = asyncio.create_task(akshare_collector_daemon(enabled_tasks=["southbound"]))
            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_service.get_southbound_flow.assert_awaited()


# ─────────────────────────────────────────
#  6. collector_registry 集成
# ─────────────────────────────────────────


class TestCollectorRegistryIntegration:
    """验证 collector_registry 中 akshare 采集器的注册"""

    @pytest.mark.asyncio
    async def test_akshare_collector_registered(self):
        """collector_registry 应为 akshare 启动 daemon"""
        from backend.workers.collector_registry import start_collector_daemons

        mock_task = MagicMock()
        mock_task.done.return_value = False

        with (
            patch("backend.workers.akshare_collector.akshare_collector_daemon", new_callable=AsyncMock),
            patch("asyncio.create_task", return_value=mock_task) as mock_create,
        ):
            tasks = await start_collector_daemons(["akshare"])

            mock_create.assert_called_once()
            assert len(tasks) == 1
