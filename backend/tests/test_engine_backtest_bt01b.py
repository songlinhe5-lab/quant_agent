"""
BT-01b · BacktestDriver + SimBroker 测试

覆盖：
- SimBroker: 市价单/限价单/止损/滑点/手续费/持仓管理
- BacktestDriver: 主循环/权益曲线/指标计算
- BacktestContext: history()/quote()/financial()/universe()

测试要求：≥80% 覆盖率
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backend.engine import Bar, OrderIntent, Strategy
from backend.engine.clock import SimClock
from backend.engine.drivers.backtest import BacktestConfig, BacktestContext, BacktestDriver
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig

# ─────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────


def make_sample_df(n: int = 50) -> pd.DataFrame:
    """生成测试用 K 线数据"""
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    np.random.seed(42)
    base_price = 100.0
    prices = [base_price]
    for _ in range(n - 1):
        change = np.random.uniform(-0.02, 0.02)
        prices.append(prices[-1] * (1 + change))

    data = {
        "open": [p * 0.998 for p in prices],
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
    }
    return pd.DataFrame(data, index=dates)


class SimpleTestStrategy(Strategy):
    """简单测试策略：价格低于 95 买入，高于 105 卖出"""

    def on_bar(self, ctx, bar: Bar) -> None:
        pos = ctx.position(bar.symbol)
        if bar.close < 95 and pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="BUY", qty=100))
        elif bar.close > 105 and not pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="SELL", qty=pos.qty))


# ─────────────────────────────────────────────
# SimBroker 测试
# ─────────────────────────────────────────────


class TestSimBroker:
    """SimBroker 模拟撮合测试"""

    @pytest.fixture
    def broker(self):
        return SimBroker(SimBrokerConfig(commission_pct=0.001, slippage_pct=0.001), initial_cash=100000.0)

    @pytest.fixture
    def sample_bar(self):
        return Bar(
            symbol="TEST.001",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            volume=1000000.0,
        )

    def test_market_buy(self, broker, sample_bar):
        """市价买入"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        order_id = broker.submit(intent, sample_bar)

        assert order_id.startswith("sim-")
        pos = broker.get_position("TEST.001")
        assert pos.qty == 100
        assert broker.cash < 100000.0  # 扣除了资金

    def test_market_sell(self, broker, sample_bar):
        """市价卖出（先买后卖）"""
        # 先买入
        buy_intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        broker.submit(buy_intent, sample_bar)

        # 再卖出
        sell_intent = OrderIntent(symbol="TEST.001", side="SELL", qty=100)
        broker.submit(sell_intent, sample_bar)

        pos = broker.get_position("TEST.001")
        assert pos.qty == 0

    def test_limit_buy_pending(self, broker, sample_bar):
        """限价买入挂单"""
        intent = OrderIntent(
            symbol="TEST.001",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=95.0,  # 低于当前价
        )
        broker.submit(intent, sample_bar)

        # 挂单应在订单簿中
        pending = broker.get_open_orders("TEST.001")
        assert len(pending) == 1
        assert broker.get_position("TEST.001").qty == 0  # 未成交

    def test_limit_buy_filled_on_low(self, broker, sample_bar):
        """限价买入在 bar.low 触及时成交"""
        # 挂一个 99 的限价买单（bar.low=98 会触及）
        intent = OrderIntent(
            symbol="TEST.001",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=99.0,
        )
        broker.submit(intent, sample_bar)

        # 用新 bar 撮合
        new_bar = Bar(
            symbol="TEST.001",
            dt=datetime(2024, 1, 16, tzinfo=timezone.utc),
            open=100.0,
            high=101.0,
            low=97.0,  # 低于 99，触发成交
            close=100.0,
            volume=1000000.0,
        )
        broker.match_open_orders(new_bar)

        pos = broker.get_position("TEST.001")
        assert pos.qty == 100

    def test_commission_deducted(self, broker, sample_bar):
        """手续费扣除"""
        initial_cash = broker.cash
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        broker.submit(intent, sample_bar)

        # 现金应该减少（成交价 + 手续费）
        assert broker.cash < initial_cash
        # 摩擦成本应该 > 0
        assert broker.state.total_friction > 0

    def test_slippage_applied(self, broker, sample_bar):
        """滑点应用"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        broker.submit(intent, sample_bar)

        # 成交价应该高于收盘价（买入滑点向上）
        trade = broker.state.trades[-1]
        assert trade["price"] > sample_bar.close

    def test_cancel_order(self, broker, sample_bar):
        """取消挂单"""
        intent = OrderIntent(
            symbol="TEST.001",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=95.0,
        )
        order_id = broker.submit(intent, sample_bar)
        assert len(broker.get_open_orders()) == 1

        result = broker.cancel(order_id)
        assert result is True
        assert len(broker.get_open_orders()) == 0

    def test_insufficient_cash(self, broker, sample_bar):
        """资金不足时按可用资金成交"""
        # 尝试买入远超现金的数量
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100000)
        broker.submit(intent, sample_bar)

        # 应该按可用资金买入部分
        pos = broker.get_position("TEST.001")
        assert pos.qty > 0
        assert pos.qty < 100000


# ─────────────────────────────────────────────
# BacktestContext 测试
# ─────────────────────────────────────────────


class TestBacktestContext:
    """BacktestContext 测试"""

    @pytest.fixture
    def ctx(self):
        df = make_sample_df(50)
        clock = SimClock()
        broker = SimBroker(SimBrokerConfig(), initial_cash=100000.0)
        return BacktestContext(
            run_id="test-run",
            clock=clock,
            df=df,
            symbol="TEST.001",
            broker=broker,
        )

    def test_history_returns_window(self, ctx):
        """history 返回截至当前 bar 的窗口"""
        ctx.set_cursor(20)
        df = ctx.history("TEST.001", n=10)
        assert len(df) == 10

    def test_history_at_beginning(self, ctx):
        """history 在起始位置返回较少数据"""
        ctx.set_cursor(5)
        df = ctx.history("TEST.001", n=10)
        assert len(df) == 6  # 0~5 共 6 根

    def test_quote_returns_current(self, ctx):
        """quote 返回当前 bar 快照"""
        ctx.set_cursor(10)
        clock = ctx._clock
        clock.set(ctx._df.index[10])
        quote = ctx.quote("TEST.001")
        assert quote.price > 0
        assert quote.stale is False

    def test_quote_stale_for_unknown_symbol(self, ctx):
        """quote 对未知标的返回 stale"""
        quote = ctx.quote("UNKNOWN.001")
        assert quote.stale is True

    def test_cash_property(self, ctx):
        """cash 属性"""
        assert ctx.cash == 100000.0

    def test_equity_property(self, ctx):
        """equity 属性"""
        ctx.set_cursor(0)
        ctx._clock.set(ctx._df.index[0])
        equity = ctx.equity
        assert equity > 0


# ─────────────────────────────────────────────
# BacktestDriver 测试
# ─────────────────────────────────────────────


class TestBacktestDriver:
    """BacktestDriver 测试"""

    @pytest.fixture
    def driver(self):
        config = BacktestConfig(
            initial_capital=100000.0,
            commission_pct=0.001,
            slippage_pct=0.001,
            random_seed=42,
        )
        return BacktestDriver(config)

    def test_run_basic(self, driver):
        """基本回测运行"""
        df = make_sample_df(50)
        result = driver.run(
            strategy_cls=SimpleTestStrategy,
            params={},
            df=df,
            symbol="TEST.001",
            source_code="class SimpleTestStrategy: ...",
        )

        assert result.manifest.mode == "backtest"
        assert result.manifest.random_seed == 42
        assert len(result.equity_curve) == 50
        assert "total_return" in result.metrics

    def test_run_with_trades(self, driver):
        """回测产生交易"""
        # 构造一个会触发买卖的数据
        df = make_sample_df(100)
        # 让价格有足够波动
        df.loc[df.index[30:40], "close"] = 90.0  # 触发买入
        df.loc[df.index[60:70], "close"] = 110.0  # 触发卖出

        result = driver.run(
            strategy_cls=SimpleTestStrategy,
            params={},
            df=df,
            symbol="TEST.001",
        )

        assert result.manifest.run_id is not None
        assert len(result.manifest.code_hash) == 64

    def test_run_rejects_short_data(self, driver):
        """拒绝过短数据"""
        df = make_sample_df(5)
        with pytest.raises(ValueError, match="至少需要 10 根"):
            driver.run(
                strategy_cls=SimpleTestStrategy,
                params={},
                df=df,
                symbol="TEST.001",
            )

    def test_manifest_populated(self, driver):
        """RunManifest 正确填充"""
        df = make_sample_df(50)
        result = driver.run(
            strategy_cls=SimpleTestStrategy,
            params={},
            df=df,
            symbol="TEST.001",
            source_code="test source code",
        )

        assert result.manifest.params == {}
        assert result.manifest.data_snapshot_id is None
        assert result.manifest.engine_version == "1.0.0"

    def test_equity_curve_structure(self, driver):
        """权益曲线结构正确"""
        df = make_sample_df(30)
        result = driver.run(
            strategy_cls=SimpleTestStrategy,
            params={},
            df=df,
            symbol="TEST.001",
        )

        for entry in result.equity_curve:
            assert "date" in entry
            assert "equity" in entry
            assert "benchmark" in entry
            assert "price" in entry


class TestBacktestDriverMetrics:
    """BacktestDriver 指标计算测试"""

    def test_metrics_format(self):
        """指标格式正确"""
        driver = BacktestDriver(BacktestConfig())
        df = make_sample_df(50)
        result = driver.run(
            strategy_cls=SimpleTestStrategy,
            params={},
            df=df,
            symbol="TEST.001",
        )

        assert "%" in result.metrics["total_return"]
        assert "%" in result.metrics["max_drawdown"]
        assert "%" in result.metrics["win_rate"]
        assert "$" in result.metrics["total_friction_cost"]

    def test_empty_equity_curve_metrics(self):
        """空权益曲线的指标"""
        driver = BacktestDriver(BacktestConfig())
        metrics = driver._compute_metrics([], [])

        assert metrics["total_return"] == "0.00%"
        assert metrics["sharpe_ratio"] == "0.00"
