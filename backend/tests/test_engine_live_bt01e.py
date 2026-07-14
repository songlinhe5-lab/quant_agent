"""
BT-01e · LiveDriver 测试

覆盖：
- TickAccumulator: tick 聚合 / bar 闭合 / 重置
- LiveContext: 属性/方法
- LiveDriverConfig: 配置
- LiveDriver: 启动/停止/行情降级

测试要求：≥60% 覆盖率（集成层）
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine import Bar, OrderIntent, Strategy
from backend.engine.clock import WallClock
from backend.engine.contracts import Position, QuoteSnapshot
from backend.engine.drivers.live import (
    LiveContext,
    LiveDriver,
    LiveDriverConfig,
    TickAccumulator,
)
from backend.engine.gateway import ExecutionGateway, GatewayMode


# ─────────────────────────────────────────────
# TickAccumulator 测试
# ─────────────────────────────────────────────


class TestTickAccumulator:
    """tick→bar 聚合器测试"""

    def test_single_tick(self):
        """单个 tick"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_1M")
        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        acc.add_tick(price=100.0, volume=1000.0, dt=dt)

        assert acc.open == 100.0
        assert acc.close == 100.0
        assert acc.high == 100.0
        assert acc.low == 100.0
        assert acc.volume == 1000.0
        assert acc.tick_count == 1

    def test_multiple_ticks(self):
        """多个 tick 聚合"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_1M")
        base_dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        acc.add_tick(100.0, 1000.0, base_dt)
        acc.add_tick(102.0, 500.0, base_dt + timedelta(seconds=10))
        acc.add_tick(99.0, 800.0, base_dt + timedelta(seconds=20))
        acc.add_tick(101.0, 600.0, base_dt + timedelta(seconds=30))

        assert acc.open == 100.0
        assert acc.high == 102.0
        assert acc.low == 99.0
        assert acc.close == 101.0
        assert acc.volume == 2900.0
        assert acc.tick_count == 4

    def test_bar_completion(self):
        """bar 闭合检测"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_1M")
        start = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        acc.add_tick(100.0, 1000.0, start)

        # 未闭合（不到 60s）
        assert acc.is_complete(start + timedelta(seconds=30)) is False

        # 已闭合（超过 60s）
        assert acc.is_complete(start + timedelta(seconds=61)) is True

    def test_to_bar(self):
        """转换为 Bar"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_DAY")
        dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        acc.add_tick(100.0, 1000.0, dt)
        acc.add_tick(105.0, 2000.0, dt + timedelta(hours=1))

        bar = acc.to_bar()
        assert bar.symbol == "TEST.001"
        assert bar.open == 100.0
        assert bar.high == 105.0
        assert bar.low == 100.0
        assert bar.close == 105.0
        assert bar.volume == 3000.0
        assert bar.ktype == "K_DAY"

    def test_reset(self):
        """重置聚合器"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_1M")
        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        acc.add_tick(100.0, 1000.0, dt)
        acc.reset()

        assert acc.tick_count == 0
        assert acc.volume == 0.0
        assert acc.started_at is None

    def test_empty_accumulator_not_complete(self):
        """空聚合器不闭合"""
        acc = TickAccumulator(symbol="TEST.001", ktype="K_1M")
        assert acc.is_complete(datetime.now(timezone.utc)) is False


# ─────────────────────────────────────────────
# LiveContext 测试
# ─────────────────────────────────────────────


class TestLiveContext:
    """LiveContext 测试"""

    @pytest.fixture
    def ctx(self):
        clock = WallClock()
        gateway = ExecutionGateway(mode=GatewayMode.PAPER)
        return LiveContext(
            mode="paper",
            run_id="test-run",
            clock=clock,
            gateway=gateway,
            symbol="TEST.001",
        )

    def test_mode_property(self, ctx):
        """mode 属性"""
        assert ctx.mode == "paper"

    def test_run_id_property(self, ctx):
        """run_id 属性"""
        assert ctx.run_id == "test-run"

    def test_quote_returns_latest(self, ctx):
        """quote 返回最新行情"""
        quote = QuoteSnapshot(
            symbol="TEST.001",
            dt=datetime.now(timezone.utc),
            price=100.0,
        )
        ctx.set_latest_quote(quote)
        result = ctx.quote("TEST.001")
        assert result.price == 100.0

    def test_quote_stale_for_unknown(self, ctx):
        """quote 对未知标的返回 stale"""
        result = ctx.quote("UNKNOWN.001")
        assert result.stale is True

    def test_cash_property(self, ctx):
        """cash 属性"""
        assert ctx.cash == 100000.0
        ctx.set_cash(50000.0)
        assert ctx.cash == 50000.0

    def test_position_property(self, ctx):
        """position 属性"""
        pos = ctx.position("TEST.001")
        assert pos.is_flat is True

        ctx.set_position("TEST.001", Position(symbol="TEST.001", qty=100, avg_cost=100.0))
        pos = ctx.position("TEST.001")
        assert pos.qty == 100

    def test_equity_property(self, ctx):
        """equity 属性"""
        quote = QuoteSnapshot(
            symbol="TEST.001",
            dt=datetime.now(timezone.utc),
            price=105.0,
        )
        ctx.set_latest_quote(quote)
        ctx.set_position("TEST.001", Position(symbol="TEST.001", qty=100, avg_cost=100.0))

        equity = ctx.equity
        assert equity == 100000.0 + 100 * 105.0

    def test_universe(self, ctx):
        """universe 返回订阅标的"""
        assert ctx.universe() == ["TEST.001"]


# ─────────────────────────────────────────────
# LiveDriverConfig 测试
# ─────────────────────────────────────────────


class TestLiveDriverConfig:
    """LiveDriverConfig 测试"""

    def test_default_config(self):
        """默认配置"""
        config = LiveDriverConfig()
        assert config.mode == "paper"
        assert config.ktype == "K_DAY"
        assert config.stale_timeout_seconds == 30.0
        assert config.poll_interval_seconds == 60.0

    def test_custom_config(self):
        """自定义配置"""
        config = LiveDriverConfig(
            mode="live",
            ktype="K_1H",
            stale_timeout_seconds=60.0,
        )
        assert config.mode == "live"
        assert config.ktype == "K_1H"


# ─────────────────────────────────────────────
# LiveDriver 测试
# ─────────────────────────────────────────────


class TestLiveDriver:
    """LiveDriver 测试"""

    def test_driver_creation(self):
        """创建 LiveDriver"""
        driver = LiveDriver(LiveDriverConfig(mode="paper"))
        assert driver.is_running is False

    @pytest.mark.asyncio
    async def test_driver_start_stop(self):
        """启动/停止 LiveDriver"""

        class TestStrategy(Strategy):
            def on_bar(self, ctx, bar):
                pass

        driver = LiveDriver(LiveDriverConfig(
            mode="paper",
            poll_interval_seconds=0.1,  # 快速轮询用于测试
        ))

        strategy = TestStrategy()
        run_id = await driver.start(strategy, "TEST.001", {})

        assert driver.is_running is True
        assert run_id is not None

        # 等待一小段时间
        await asyncio.sleep(0.2)

        # 停止
        await driver.stop()
        assert driver.is_running is False
