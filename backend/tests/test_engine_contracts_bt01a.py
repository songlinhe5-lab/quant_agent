"""
BT-01a · 同构引擎契约层测试

覆盖：
- contracts.py: Bar / QuoteSnapshot / OrderIntent / OrderUpdate / Position / RunManifest
- clock.py: SimClock / WallClock / Clock Protocol
- strategy.py: Strategy ABC / signals / is_vectorizable
- context.py: BaseContext / StrategyContext Protocol

测试要求：≥90% 覆盖率
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import pytest

from backend.engine import (
    Bar,
    BaseContext,
    Clock,
    OrderIntent,
    OrderUpdate,
    Position,
    QuoteSnapshot,
    RunManifest,
    SimClock,
    Strategy,
    StrategyContext,
    WallClock,
)
from backend.schemas.domain import OrderStatus

# ─────────────────────────────────────────────
# contracts.py 测试
# ─────────────────────────────────────────────


class TestBar:
    """Bar 契约测试"""

    def test_bar_valid_creation(self):
        """正常创建 Bar"""
        bar = Bar(
            symbol="HK.00700",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            open=350.0,
            high=355.0,
            low=348.0,
            close=352.0,
            volume=1000000.0,
            ktype="K_DAY",
        )
        assert bar.symbol == "HK.00700"
        assert bar.close == 352.0
        assert bar.ktype == "K_DAY"

    def test_bar_default_ktype(self):
        """Bar 默认 ktype 为 K_DAY"""
        bar = Bar(
            symbol="US.AAPL",
            dt=datetime(2024, 1, 15, tzinfo=timezone.utc),
            open=180.0,
            high=182.0,
            low=179.0,
            close=181.0,
            volume=50000000.0,
        )
        assert bar.ktype == "K_DAY"

    def test_bar_rejects_naive_datetime(self):
        """Bar 拒绝无时区的 datetime"""
        with pytest.raises(ValueError, match="timezone-aware"):
            Bar(
                symbol="HK.00700",
                dt=datetime(2024, 1, 15, 16, 0),  # 无时区
                open=350.0,
                high=355.0,
                low=348.0,
                close=352.0,
                volume=1000000.0,
            )


class TestQuoteSnapshot:
    """QuoteSnapshot 契约测试"""

    def test_quote_snapshot_valid(self):
        """正常创建 QuoteSnapshot"""
        qs = QuoteSnapshot(
            symbol="HK.00700",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            price=352.0,
            bid=351.8,
            ask=352.2,
            stale=False,
        )
        assert qs.price == 352.0
        assert qs.bid == 351.8
        assert qs.stale is False

    def test_quote_snapshot_stale_flag(self):
        """QuoteSnapshot 降级标识"""
        qs = QuoteSnapshot(
            symbol="US.AAPL",
            dt=datetime(2024, 1, 15, tzinfo=timezone.utc),
            price=180.0,
            stale=True,
        )
        assert qs.stale is True
        assert qs.bid is None

    def test_quote_snapshot_rejects_naive_datetime(self):
        """QuoteSnapshot 拒绝无时区的 datetime"""
        with pytest.raises(ValueError, match="timezone-aware"):
            QuoteSnapshot(
                symbol="HK.00700",
                dt=datetime(2024, 1, 15),
                price=352.0,
            )


class TestOrderIntent:
    """OrderIntent 契约测试"""

    def test_market_order_valid(self):
        """市价单正常创建"""
        intent = OrderIntent(
            symbol="HK.00700",
            side="BUY",
            qty=100,
            order_type="MARKET",
        )
        assert intent.side == "BUY"
        assert intent.qty == 100
        assert intent.limit_price is None

    def test_limit_order_valid(self):
        """限价单正常创建"""
        intent = OrderIntent(
            symbol="HK.00700",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=350.0,
        )
        assert intent.limit_price == 350.0

    def test_limit_order_requires_price(self):
        """限价单必须指定价格"""
        with pytest.raises(ValueError, match="limit_price"):
            OrderIntent(
                symbol="HK.00700",
                side="BUY",
                qty=100,
                order_type="LIMIT",
                # 缺少 limit_price
            )

    def test_order_intent_rejects_zero_qty(self):
        """OrderIntent 拒绝零数量"""
        with pytest.raises(ValueError):
            OrderIntent(symbol="HK.00700", side="BUY", qty=0)

    def test_order_intent_rejects_negative_qty(self):
        """OrderIntent 拒绝负数量"""
        with pytest.raises(ValueError):
            OrderIntent(symbol="HK.00700", side="BUY", qty=-100)

    def test_order_intent_with_stop_loss(self):
        """OrderIntent 带止损"""
        intent = OrderIntent(
            symbol="US.AAPL",
            side="BUY",
            qty=50,
            stop_loss=175.0,
            tag="my_strategy_entry",
        )
        assert intent.stop_loss == 175.0
        assert intent.tag == "my_strategy_entry"


class TestOrderUpdate:
    """OrderUpdate 契约测试"""

    def test_order_update_filled(self):
        """成交回报"""
        update = OrderUpdate(
            order_id="order-123",
            intent_tag="entry_signal",
            status=OrderStatus.FILLED,
            filled_qty=100,
            avg_fill_price=352.5,
        )
        assert update.status == OrderStatus.FILLED
        assert update.filled_qty == 100

    def test_order_update_pending(self):
        """挂单状态"""
        update = OrderUpdate(
            order_id="order-456",
            status=OrderStatus.PENDING,
        )
        assert update.filled_qty == 0
        assert update.avg_fill_price is None


class TestPosition:
    """Position 契约测试"""

    def test_position_flat(self):
        """空仓"""
        pos = Position(symbol="HK.00700")
        assert pos.is_flat is True
        assert pos.qty == 0

    def test_position_with_holdings(self):
        """有持仓"""
        pos = Position(
            symbol="HK.00700",
            qty=100,
            avg_cost=350.0,
            market_value=35200.0,
            unrealized_pnl=200.0,
        )
        assert pos.is_flat is False
        assert pos.unrealized_pnl == 200.0


class TestRunManifest:
    """RunManifest 契约测试"""

    def test_manifest_creation(self):
        """正常创建 RunManifest"""
        manifest = RunManifest(
            run_id=str(uuid.uuid4()),
            mode="backtest",
            code_hash="abc123",
            params={"rsi_period": 14},
            random_seed=42,
        )
        assert manifest.mode == "backtest"
        assert manifest.random_seed == 42
        assert manifest.data_snapshot_id is None

    def test_compute_code_hash(self):
        """计算代码 hash"""
        source = "class MyStrategy(Strategy): ..."
        hash1 = RunManifest.compute_code_hash(source)
        hash2 = RunManifest.compute_code_hash(source)
        assert hash1 == hash2
        assert len(hash1) == 64  # sha256 hex length

    def test_compute_code_hash_different_source(self):
        """不同代码产生不同 hash"""
        hash1 = RunManifest.compute_code_hash("class A: ...")
        hash2 = RunManifest.compute_code_hash("class B: ...")
        assert hash1 != hash2

    def test_manifest_to_json(self):
        """序列化为确定性 JSON"""
        manifest = RunManifest(
            run_id="test-run-1",
            mode="backtest",
            code_hash="abc123",
            params={"b": 2, "a": 1},
        )
        json_str = manifest.to_json()
        parsed = json.loads(json_str)
        assert parsed["mode"] == "backtest"
        # 验证 sort_keys=True
        keys = list(parsed.keys())
        assert keys == sorted(keys)


# ─────────────────────────────────────────────
# clock.py 测试
# ─────────────────────────────────────────────


class TestSimClock:
    """SimClock 测试"""

    def test_sim_clock_initial_epoch(self):
        """SimClock 初始为 epoch"""
        clock = SimClock()
        assert clock.now() == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_sim_clock_set(self):
        """SimClock 可推进"""
        clock = SimClock()
        dt = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)
        clock.set(dt)
        assert clock.now() == dt

    def test_sim_clock_forward_only(self):
        """SimClock 不能回退"""
        clock = SimClock()
        dt1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        dt2 = datetime(2024, 1, 14, tzinfo=timezone.utc)
        clock.set(dt1)
        with pytest.raises(ValueError, match="cannot go backwards"):
            clock.set(dt2)

    def test_sim_clock_rejects_naive_datetime(self):
        """SimClock 拒绝无时区的 datetime"""
        clock = SimClock()
        with pytest.raises(ValueError, match="timezone-aware"):
            clock.set(datetime(2024, 1, 15))

    def test_sim_clock_reset(self):
        """SimClock 可重置"""
        clock = SimClock()
        clock.set(datetime(2024, 1, 15, tzinfo=timezone.utc))
        clock.reset()
        assert clock.now() == datetime(1970, 1, 1, tzinfo=timezone.utc)


class TestWallClock:
    """WallClock 测试"""

    def test_wall_clock_returns_current_time(self):
        """WallClock 返回当前时间"""
        clock = WallClock()
        before = datetime.now(timezone.utc)
        result = clock.now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_wall_clock_is_utc(self):
        """WallClock 返回 UTC 时间"""
        clock = WallClock()
        result = clock.now()
        assert result.tzinfo == timezone.utc


class TestClockProtocol:
    """Clock Protocol 测试"""

    def test_sim_clock_is_clock(self):
        """SimClock 实现 Clock Protocol"""
        clock = SimClock()
        assert isinstance(clock, Clock)

    def test_wall_clock_is_clock(self):
        """WallClock 实现 Clock Protocol"""
        clock = WallClock()
        assert isinstance(clock, Clock)


# ─────────────────────────────────────────────
# strategy.py 测试
# ─────────────────────────────────────────────


class ConcreteStrategy(Strategy):
    """具体策略实现（用于测试）"""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._on_bar_called = False
        self._on_init_called = False
        self._on_stop_called = False

    def on_init(self, ctx: "StrategyContext") -> None:
        self._on_init_called = True

    def on_bar(self, ctx: "StrategyContext", bar: "Bar") -> None:
        self._on_bar_called = True

    def on_stop(self, ctx: "StrategyContext") -> None:
        self._on_stop_called = True


class VectorizableStrategy(Strategy):
    """可矢量化策略（用于测试）"""

    def on_bar(self, ctx: "StrategyContext", bar: "Bar") -> None:
        pass

    @classmethod
    def signals(cls, df: pd.DataFrame, params: Dict[str, Any]) -> Optional[pd.Series]:
        # 简单均线策略
        sma = df["close"].rolling(20).mean()
        signal = (df["close"] > sma).astype(int)
        signal[df["close"] < sma] = -1
        return signal


class TestStrategyABC:
    """Strategy 抽象基类测试"""

    def test_cannot_instantiate_abstract(self):
        """不能直接实例化 Strategy"""
        with pytest.raises(TypeError):
            Strategy()

    def test_concrete_strategy_instantiable(self):
        """具体策略可实例化"""
        strategy = ConcreteStrategy(threshold=0.3)
        assert strategy.threshold == 0.3

    def test_on_bar_required(self):
        """on_bar 是必须实现的方法"""

        # 没有实现 on_bar 的类无法实例化
        class IncompleteStrategy(Strategy):
            pass

        with pytest.raises(TypeError):
            IncompleteStrategy()

    def test_on_init_optional(self):
        """on_init 是可选的"""

        class MinimalStrategy(Strategy):
            def on_bar(self, ctx, bar):
                pass

        strategy = MinimalStrategy()
        # 默认 on_init 不抛异常
        strategy.on_init(None)

    def test_on_stop_optional(self):
        """on_stop 是可选的"""

        class MinimalStrategy(Strategy):
            def on_bar(self, ctx, bar):
                pass

        strategy = MinimalStrategy()
        # 默认 on_stop 不抛异常
        strategy.on_stop(None)

    def test_on_order_update_optional(self):
        """on_order_update 是可选的"""

        class MinimalStrategy(Strategy):
            def on_bar(self, ctx, bar):
                pass

        strategy = MinimalStrategy()
        # 默认 on_order_update 不抛异常
        strategy.on_order_update(None, None)


class TestStrategySignals:
    """Strategy 矢量化快路径测试"""

    def test_default_signals_returns_none(self):
        """默认 signals 返回 None"""
        assert ConcreteStrategy.signals(pd.DataFrame(), {}) is None

    def test_is_vectorizable_false_for_base(self):
        """基础策略不可矢量化"""
        assert ConcreteStrategy.is_vectorizable() is False

    def test_is_vectorizable_true_for_override(self):
        """覆盖 signals 的策略可矢量化"""
        assert VectorizableStrategy.is_vectorizable() is True

    def test_vectorizable_strategy_signals(self):
        """可矢量化策略的 signals 方法"""
        df = pd.DataFrame(
            {
                "close": [1.0] * 30,
            },
            index=pd.date_range("2024-01-01", periods=30),
        )
        result = VectorizableStrategy.signals(df, {})
        assert result is not None
        assert len(result) == 30


# ─────────────────────────────────────────────
# context.py 测试
# ─────────────────────────────────────────────


class TestBaseContext:
    """BaseContext 测试"""

    @pytest.fixture
    def clock(self):
        return SimClock()

    @pytest.fixture
    def ctx(self, clock):
        return BaseContext(mode="backtest", run_id="test-run-1", clock=clock)

    def test_now_delegates_to_clock(self, ctx, clock):
        """ctx.now 委托给 clock"""
        dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        clock.set(dt)
        assert ctx.now == dt

    def test_mode_property(self, ctx):
        """ctx.mode 返回运行模式"""
        assert ctx.mode == "backtest"

    def test_run_id_property(self, ctx):
        """ctx.run_id 返回运行 ID"""
        assert ctx.run_id == "test-run-1"

    def test_subscribe(self, ctx):
        """subscribe 记录订阅标的"""
        ctx.subscribe(["HK.00700", "US.AAPL"], warmup=60)
        assert ctx._subscribed_symbols == ["HK.00700", "US.AAPL"]
        assert ctx._warmup == 60

    def test_log(self, ctx, clock):
        """log 记录日志"""
        clock.set(datetime(2024, 1, 15, tzinfo=timezone.utc))
        ctx.log("test_event", key1="value1", key2=42)
        assert len(ctx.logs) == 1
        assert ctx.logs[0]["event"] == "test_event"
        assert ctx.logs[0]["key1"] == "value1"
        assert ctx.logs[0]["key2"] == 42

    def test_logs_returns_copy(self, ctx):
        """logs 返回副本"""
        ctx.log("event1")
        logs1 = ctx.logs
        logs2 = ctx.logs
        assert logs1 is not logs2


class TestStrategyContextProtocol:
    """StrategyContext Protocol 测试"""

    def test_base_context_has_core_properties(self):
        """BaseContext 提供核心属性（now/mode/run_id/subscribe/log）"""
        clock = SimClock()
        ctx = BaseContext(mode="backtest", run_id="test", clock=clock)
        # 核心属性存在
        assert hasattr(ctx, "now")
        assert hasattr(ctx, "mode")
        assert hasattr(ctx, "run_id")
        assert hasattr(ctx, "subscribe")
        assert hasattr(ctx, "log")

    def test_full_context_satisfies_protocol(self):
        """完整 Context 实现满足 StrategyContext Protocol"""

        class FullContext(BaseContext):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._cash = 100000.0
                self._positions: Dict[str, Any] = {}

            def history(self, symbol, n, ktype="K_DAY"):
                return pd.DataFrame()

            def quote(self, symbol):
                from backend.engine.contracts import QuoteSnapshot

                return QuoteSnapshot(symbol=symbol, dt=self.now, price=0.0)

            def financial(self, symbol, field):
                return None

            def universe(self):
                return []

            def position(self, symbol):
                return self._positions.get(symbol, Position(symbol=symbol))

            @property
            def cash(self):
                return self._cash

            @property
            def equity(self):
                return self._cash

            def order(self, intent):
                return "order-1"

            def cancel(self, order_id):
                return True

            def open_orders(self):
                return []

        clock = SimClock()
        ctx = FullContext(mode="backtest", run_id="test", clock=clock)
        assert isinstance(ctx, StrategyContext)


# ─────────────────────────────────────────────
# 集成测试：示例策略可实例化并运行
# ─────────────────────────────────────────────


class TestExampleStrategyIntegration:
    """示例策略集成测试"""

    def test_strategy_lifecycle(self):
        """策略生命周期：on_init → on_bar → on_stop"""
        strategy = ConcreteStrategy()
        clock = SimClock()
        ctx = BaseContext(mode="backtest", run_id="test", clock=clock)

        # on_init
        strategy.on_init(ctx)
        assert strategy._on_init_called

        # on_bar
        bar = Bar(
            symbol="HK.00700",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            open=350.0,
            high=355.0,
            low=348.0,
            close=352.0,
            volume=1000000.0,
        )
        clock.set(bar.dt)
        strategy.on_bar(ctx, bar)
        assert strategy._on_bar_called

        # on_stop
        strategy.on_stop(ctx)
        assert strategy._on_stop_called

    def test_strategy_can_access_ctx(self):
        """策略可以通过 ctx 访问元信息"""

        class InspectingStrategy(Strategy):
            def __init__(self):
                self.observed_mode = None
                self.observed_run_id = None

            def on_bar(self, ctx, bar):
                self.observed_mode = ctx.mode
                self.observed_run_id = ctx.run_id

        strategy = InspectingStrategy()
        clock = SimClock()
        ctx = BaseContext(mode="backtest", run_id="my-run-42", clock=clock)

        bar = Bar(
            symbol="US.AAPL",
            dt=datetime(2024, 1, 15, tzinfo=timezone.utc),
            open=180.0,
            high=182.0,
            low=179.0,
            close=181.0,
            volume=50000000.0,
        )
        clock.set(bar.dt)
        strategy.on_bar(ctx, bar)

        assert strategy.observed_mode == "backtest"
        assert strategy.observed_run_id == "my-run-42"
