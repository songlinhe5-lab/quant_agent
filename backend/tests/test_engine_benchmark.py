import time

import numpy as np
import pandas as pd
import pytest

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
        sig = current_bar.get("signal", 0)

        if sig == 1:
            return {"action": "buy", "stop_loss": current_bar["Close"] * 0.95}
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

    df = pd.DataFrame(
        {
            "Open": closes * 0.999,
            "High": closes * 1.002,
            "Low": closes * 0.998,
            "Close": closes,
            "Volume": np.random.randint(100, 1000, size=n_bars),
            "signal": np.zeros(n_bars),
            "atr": np.ones(n_bars) * 1.5,
        },
        index=dates,
    )

    # Inject signals: Buy at 100, 300, 500... Sell at 200, 400, 600...
    df.loc[df.index[100::200], "signal"] = 1  # Buy
    df.loc[df.index[200::200], "signal"] = -1  # Sell

    return df


def test_engine_performance_benchmark(large_dataframe, capsys):
    """Benchmark test for EventDrivenBacktestEngine."""
    df = large_dataframe

    # --- Event-Driven Execution Benchmark ---
    ed_engine = EventDrivenBacktestEngine(BenchmarkStrategy(), df)
    start_ed = time.perf_counter()
    ed_engine.run()
    time_ed = time.perf_counter() - start_ed

    # Assert that the engine runs within a reasonable time (e.g., < 5 seconds)
    assert time_ed < 5.0, f"EventDrivenBacktestEngine took too long: {time_ed:.4f}s"

    # Use capsys to bypass PyTest's stdout capture and print the results immediately
    with capsys.disabled():
        print("\n🚀 === Backtest Engine Benchmark (10,000 bars) ===")
        print(f"🐢 Event-Driven Time : {time_ed:.4f} seconds")
        print("⚠️  Numba Engine: Not yet implemented (benchmark disabled)")

    # Basic assertion to ensure the test passes
    assert True
