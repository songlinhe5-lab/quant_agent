"""strategies/live 实盘策略单元测试"""
import numpy as np
import pandas as pd


def _make_kline_df(n=50, base_price=100.0, seed=42):
    """生成测试用 K 线 DataFrame"""
    np.random.seed(seed)
    close = base_price + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(1000, 10000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


class TestDualMaAtrStopStrategy:
    """双均线 ATR 止损策略测试"""

    def test_init_defaults_set_correctly(self):
        """测试默认参数初始化"""
        from backend.strategies.live.dualmaatrstopstrategy import DualMaAtrStopStrategy
        s = DualMaAtrStopStrategy()
        assert s.short_window == 10
        assert s.long_window == 30
        assert s.atr_window == 21
        assert s.atr_mult == 1.6
        assert s.ma_type == "SMA"

    def test_init_custom_params_overridden(self):
        """测试自定义参数覆盖"""
        from backend.strategies.live.dualmaatrstopstrategy import DualMaAtrStopStrategy
        s = DualMaAtrStopStrategy(short_window=5, long_window=15, atr_window=10, atr_mult=2.5, ma_type="EMA")
        assert s.short_window == 5
        assert s.ma_type == "EMA"

    def test_calculate_indicators_sma_adds_columns(self):
        """测试 SMA 模式下指标计算生成正确列"""
        from backend.strategies.live.dualmaatrstopstrategy import DualMaAtrStopStrategy
        s = DualMaAtrStopStrategy(short_window=5, long_window=10, atr_window=7)
        s.df = _make_kline_df(30)
        s._calculate_indicators()
        assert "short_ma" in s.df.columns
        assert "long_ma" in s.df.columns
        assert "atr" in s.df.columns

    def test_generate_signals_produces_valid_values(self):
        """测试信号生成产生合法值 (1, -1, 0)"""
        from backend.strategies.live.dualmaatrstopstrategy import DualMaAtrStopStrategy
        s = DualMaAtrStopStrategy(short_window=5, long_window=10, atr_window=7)
        s.df = _make_kline_df(50)
        s._calculate_indicators()
        s._generate_signals()
        assert "signal" in s.df.columns
        valid_signals = set(s.df["signal"].unique())
        assert valid_signals.issubset({1, -1, 0})

    def test_ema_mode_calculates_indicators_without_nan(self):
        """测试 EMA 模式正常计算且不产生 NaN"""
        from backend.strategies.live.dualmaatrstopstrategy import DualMaAtrStopStrategy
        s = DualMaAtrStopStrategy(short_window=5, long_window=10, ma_type="EMA")
        s.df = _make_kline_df(30)
        s._calculate_indicators()
        assert s.df["short_ma"].isna().sum() == 0


class TestMaCrossAtrStrategy:
    """双均线交叉 ATR 策略测试"""

    def test_init_defaults_set_correctly(self):
        """测试默认参数"""
        from backend.strategies.live.macrossatrstrategy import MaCrossAtrStrategy
        s = MaCrossAtrStrategy()
        assert s.fast_ma == 10
        assert s.slow_ma == 20
        assert s.atr_period == 14
        assert s.atr_mult == 2.0

    def test_calculate_indicators_adds_ma_and_atr(self):
        """测试指标计算生成均线和 ATR 列"""
        from backend.strategies.live.macrossatrstrategy import MaCrossAtrStrategy
        s = MaCrossAtrStrategy(fast_ma=5, slow_ma=10, atr_period=7)
        s.df = _make_kline_df(30)
        s._calculate_indicators()
        assert "ma_fast" in s.df.columns
        assert "ma_slow" in s.df.columns
        assert "atr" in s.df.columns

    def test_generate_signals_valid_range(self):
        """测试信号值在合法范围内"""
        from backend.strategies.live.macrossatrstrategy import MaCrossAtrStrategy
        s = MaCrossAtrStrategy(fast_ma=5, slow_ma=10, atr_period=7)
        s.df = _make_kline_df(50)
        s._calculate_indicators()
        s._generate_signals()
        valid_signals = set(s.df["signal"].unique())
        assert valid_signals.issubset({1, -1, 0})

    def test_ema_mode_indicators_no_nan(self):
        """测试 EMA 模式不产生 NaN"""
        from backend.strategies.live.macrossatrstrategy import MaCrossAtrStrategy
        s = MaCrossAtrStrategy(fast_ma=5, slow_ma=10, ma_type="EMA")
        s.df = _make_kline_df(20)
        s._calculate_indicators()
        assert s.df["ma_fast"].isna().sum() == 0


class TestPairsTradingBot:
    """配对交易策略测试"""

    def test_init_defaults_set_correctly(self):
        """测试默认参数"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot()
        assert bot.stock1 == "00700.HK"
        assert bot.stock2 == "09988.HK"
        assert bot.entry_z == 2.5
        assert bot.exit_z == 0.5
        assert bot.position is None

    def test_calc_zscore_returns_float(self):
        """测试 Z-Score 计算返回浮点数"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot()
        p1 = np.array([100, 102, 101, 103, 100, 104, 102, 105, 101, 106], dtype=float)
        p2 = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        z = bot.calc_zscore(p1, p2)
        assert isinstance(z, float)

    def test_on_tick_high_z_triggers_short_spread(self):
        """测试高 Z-Score 触发做空价差"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot(entry_z=1.0)
        p1 = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 120], dtype=float)
        p2 = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        data = {"00700.HK": {"price": p1}, "09988.HK": {"price": p2}}
        signal = bot.on_tick(data)
        assert signal is not None
        assert "SHORT" in signal
        assert bot.position == "short_spread"

    def test_on_tick_low_z_triggers_long_spread(self):
        """测试低 Z-Score 触发做多价差"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot(entry_z=1.0)
        p1 = np.array([100, 99, 98, 97, 96, 95, 94, 93, 92, 80], dtype=float)
        p2 = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        data = {"00700.HK": {"price": p1}, "09988.HK": {"price": p2}}
        signal = bot.on_tick(data)
        assert signal is not None
        assert "LONG" in signal
        assert bot.position == "long_spread"

    def test_on_tick_neutral_z_returns_none(self):
        """测试 Z-Score 在中性区间无信号"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot(entry_z=2.5, exit_z=0.5)
        p1 = np.array([100, 101, 100, 101, 100, 101, 100, 101, 100, 101], dtype=float)
        p2 = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        data = {"00700.HK": {"price": p1}, "09988.HK": {"price": p2}}
        signal = bot.on_tick(data)
        assert signal is None
        assert bot.position is None

    def test_on_tick_exit_z_closes_existing_position(self):
        """测试 Z-Score 回归中性时平仓"""
        from backend.strategies.live.pairstradingbot import PairsTradingBot
        bot = PairsTradingBot(entry_z=2.5, exit_z=0.5)
        bot.position = "long_spread"
        # 构造有方差但末尾 z 接近 0 的价差序列
        p1 = np.array([100, 102, 98, 101, 99, 100, 102, 98, 101, 100], dtype=float)
        p2 = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
        data = {"00700.HK": {"price": p1}, "09988.HK": {"price": p2}}
        signal = bot.on_tick(data)
        assert signal == "CLOSE ALL"
        assert bot.position is None
