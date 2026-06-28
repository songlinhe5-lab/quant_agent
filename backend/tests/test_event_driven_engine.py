import pandas as pd
import pytest

from backend.core.backtest_engine import EventDrivenBacktestEngine


class MockSimpleStrategy:
    """
    A predictable mock strategy to test the EventDrivenBacktestEngine.
    It triggers a BUY, a SELL, and a STOP-LOSS scenario deterministically.
    """

    def __init__(self):
        self._position_size = 0
        self._position_data = {}

    def on_bar(self, window_df: pd.DataFrame) -> dict:
        window_df.iloc[-1]["close"]
        bar_index = len(window_df) - 1  # The engine passes window_df up to the current bar  # noqa: E501

        # Bar 11: Buy at 110. Stop loss at 105.
        if bar_index == 11:
            return {"action": "buy", "stop_loss": 105.0}

        # Bar 15: Sell to close the position
        elif bar_index == 15:
            return {"action": "sell"}

        # Bar 17: Buy again at 117. Stop loss at 112.
        elif bar_index == 17:
            return {"action": "buy", "stop_loss": 112.0}

        # Bar 19: Price will dip to 100 in the mock data, hitting the stop loss implicitly.  # noqa: E501

        return {}


@pytest.fixture
def mock_dataframe():
    """
    Generates 20 days of deterministic OHLCV data.
    Prices steadily increase from 100 to 118, but drops suddenly on day 19 to trigger a stop loss.
    """  # noqa: E501
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    prices = [100.0 + i for i in range(19)] + [100.0]  # Sudden drop at the end

    df = pd.DataFrame(
        {
            "Open": prices,
            "High": [p + 2.0 for p in prices],
            "Low": [p - 2.0 for p in prices],
            "Close": prices,
            "Volume": [1000] * 20,
        },
        index=dates,
    )

    return df


def test_event_driven_engine_execution(mock_dataframe):
    """
    Tests if the EventDrivenBacktestEngine executes trades, applies slippage/commissions,
    and enforces stop-loss logic appropriately.
    """  # noqa: E501
    strategy = MockSimpleStrategy()
    initial_capital = 100000.0
    commission_pct = 0.001  # 0.1%
    slippage_pct = 0.001  # 0.1%

    engine = EventDrivenBacktestEngine(
        strategy_instance=strategy,
        df=mock_dataframe,
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
    )

    report = engine.run()

    # 1. Verify general report structure
    assert "metrics" in report
    assert "equity_curve" in report
    assert "trades" in report

    metrics = report["metrics"]
    trades = report["trades"]

    # 2. Verify Trades execution
    # Expected Trades:
    # 1. Buy @ Bar 11
    # 2. Sell @ Bar 15
    # 3. Buy @ Bar 17
    # 4. Sell (Stop Loss) @ Bar 19
    assert len(trades) == 4, "Should have exactly 4 trades (2 complete round trips)"

    assert trades[0]["action"] == "BUY"
    assert trades[1]["action"] == "SELL"
    assert trades[2]["action"] == "BUY"
    assert trades[3]["action"] == "SELL"  # Stop loss

    # 3. Verify Friction Costs (Slippage + Commission)
    total_friction_str = metrics["total_friction_cost"].replace("$", "").replace(",", "")  # noqa: E501
    total_friction = float(total_friction_str)
    assert total_friction > 0.0, "Friction costs (commission & slippage) should be > 0"

    # 4. Verify Equity Curve dimensions
    # Engine loops from index 10 to len(df)-1. Total 20 bars -> 10 iterations.
    assert len(report["equity_curve"]) == 10

    # 5. Verify the Stop Loss triggered correctly on the last trade
    # On Bar 19, the price dips to 100.0. Stop loss was set at 112.0.
    # The engine should execute the exit at the current price (100.0) with slippage.
    stop_loss_trade = trades[3]
    assert stop_loss_trade["price"] == 100.0 * (1 - slippage_pct), (
        "Stop loss should execute at current price adjusted for slippage"
    )  # noqa: E501


class MockLimitStrategy:
    """
    A predictable strategy to test pending Limit Orders.
    Engine starts processing at bar 10 (index 10), so signals before that are ignored.
    """

    def __init__(self):
        self._position_size = 0
        self._position_data = {}

    def on_bar(self, window_df: pd.DataFrame) -> dict:
        bar_index = len(window_df) - 1

        # Bar 10 (first engine bar): Issue a Limit Buy order at 89.0.
        if bar_index == 10 and self._position_size == 0:
            return {"action": "buy", "limit_price": 89.0, "stop_loss": 80.0}

        # Bar 12 (after buy fills at bar 11): Issue a Limit Sell order at 121.0
        elif bar_index == 12 and self._position_size > 0:
            return {"action": "sell", "limit_price": 121.0}

        return {}


def test_limit_order_execution():
    # 15 bars, engine processes bars 10-14
    dates = pd.date_range("2024-01-01", periods=15, freq="D")
    prices = [100.0] * 15
    prices[11] = 90.0  # Bar 11 Close=90, Low=85 → triggers Buy limit (89.0)
    prices[10] = 100.0  # Bar 10 Low=95, NOT <= 89.0 → no trigger
    prices[13] = 122.0  # Bar 13 Close=122, High=127 → triggers Sell limit (121.0)

    df = pd.DataFrame(
        {
            "Open": prices,
            "High": [p + 5.0 for p in prices],
            "Low": [p - 5.0 for p in prices],
            "Close": prices,
            "Volume": [1000] * 15,
        },
        index=dates,
    )

    engine = EventDrivenBacktestEngine(
        strategy_instance=MockLimitStrategy(),
        df=df,
        commission_pct=0.0,
        slippage_pct=0.0,
    )
    report = engine.run()
    trades = report["trades"]

    assert len(trades) == 2, f"Should execute exactly 1 buy limit and 1 sell limit, got {len(trades)}: {trades}"

    # Buy fills at bar 11: Low=85 <= 89.0, base_price = min(89.0, 90.0) = 89.0
    assert trades[0]["action"] == "BUY"
    assert trades[0]["price"] == 89.0
    # Sell fills at bar 13: High=127 >= 121.0, base_price = max(121.0, 122.0) = 122.0
    assert trades[1]["action"] == "SELL"
    assert trades[1]["price"] == 122.0
