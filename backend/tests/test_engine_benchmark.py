import pytest
import time
import pandas as pd
import numpy as np

from backend.core.backtest_engine import EventDrivenBacktestEngine

class BenchmarkStrategy:
    """
    A simple strategy designed purely to trigger buying and selling 
    in the Event-Driven engine for benchmarking purposes.
    """
    def __init__(self):
        self._position_size = 0
        self._position_data = {}

    def on_bar(self, window_df: pd.DataFrame) -> dict:
        current_bar = window_df.iloc[-1]
        sig = current_bar.get('signal', 0)
        
        if sig == 1:
            return {"action": "buy", "stop_loss": current_bar['Close'] * 0.95}
        elif sig == -1:
            return {"action": "sell"}
        return {}


@pytest.fixture
def large_dataframe():
    """
    Generates 10,000 bars of OHLCV data for benchmarking.
    We inject buy/sell signals every 200 bars.
    """
    np.random.seed(42)
    n_bars = 10000
    dates = pd.date_range("2010-01-01", periods=n_bars, freq="min")
    closes = np.cumprod(1 + np.random.randn(n_bars) * 0.001) * 100
    
    df = pd.DataFrame({
        "Open": closes * 0.999,
        "High": closes * 1.002,
        "Low": closes * 0.998,
        "Close": closes,
        "Volume": np.random.randint(100, 1000, size=n_bars),
        "signal": np.zeros(n_bars),
        "atr": np.ones(n_bars) * 1.5
    }, index=dates)
    
    # Inject signals: Buy at 100, 300, 500... Sell at 200, 400, 600...
    df.loc[df.index[100::200], 'signal'] = 1   # Buy
    df.loc[df.index[200::200], 'signal'] = -1  # Sell
    
    return df


def test_engine_performance_benchmark(large_dataframe, capsys):
    df = large_dataframe
    
    # --- 1. Event-Driven Execution ---
    ed_engine = EventDrivenBacktestEngine(BenchmarkStrategy(), df)
    start_ed = time.perf_counter()
    ed_engine.run()
    time_ed = time.perf_counter() - start_ed
    
    # --- 2. Numba Vectorized Execution ---
    close_arr = df['Close'].values.astype(np.float64)
    signal_arr = df['signal'].values.astype(np.float64)
    atr_arr = df['atr'].values.astype(np.float64)
    
    # WARM-UP: Pre-compile Numba function to ensure a fair benchmark
    _fast_backtest_engine(close_arr[:10], signal_arr[:10], atr_arr[:10], 2.0, 100000.0, 0.0005, 0.001)
    
    start_nb = time.perf_counter()
    _fast_backtest_engine(close_arr, signal_arr, atr_arr, 2.0, 100000.0, 0.0005, 0.001)
    time_nb = time.perf_counter() - start_nb
    
    speedup = time_ed / time_nb if time_nb > 0 else 0
    
    # Ensure Numba is significantly faster (usually > 50x depending on CPU)
    assert time_nb < time_ed, f"Numba Engine ({time_nb:.4f}s) should be faster than Event-Driven ({time_ed:.4f}s)"
    
    # Use capsys to bypass PyTest's stdout capture and print the results immediately
    with capsys.disabled():
        print(f"\n🚀 === Backtest Engine Benchmark (10,000 bars) ===")
        print(f"🐢 Event-Driven Time : {time_ed:.4f} seconds")
        print(f"⚡ Numba Engine Time  : {time_nb:.4f} seconds")
        print(f"🔥 Speedup Factor    : {speedup:.2f}x faster")