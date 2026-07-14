"""
BT-04 · 蒙特卡洛压测单测

覆盖：PnL 提取、路径模拟、分位曲线、最坏回撤、Runner（注入基线）、API 错误映射。
禁止真实网络请求。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app.monte_carlo_app import MonteCarloError, MonteCarloParams, run_monte_carlo
from backend.engine.drivers.vector import VectorConfig, VectorResult
from backend.engine.monte_carlo import (
    MonteCarloConfig,
    MonteCarloRunner,
    extract_daily_returns,
    extract_trade_pnls,
    max_drawdown_from_equity,
    percentile_curves_from_paths,
    simulate_paths,
)
from backend.engine.strategy import Strategy
from backend.engine.walk_forward import SmaCrossStrategy


class TestExtractors:
    def test_extract_trade_pnls(self):
        trades = [
            {"action": "BUY", "price": 10},
            {"action": "SELL", "profit": 12.5},
            {"action": "SELL", "profit": -3.0},
        ]
        pnls = extract_trade_pnls(trades)
        assert list(pnls) == [12.5, -3.0]

    def test_extract_daily_returns(self):
        curve = [{"equity": 100.0}, {"equity": 110.0}, {"equity": 99.0}]
        rets = extract_daily_returns(curve)
        assert rets[0] == pytest.approx(0.1)
        assert rets[1] == pytest.approx(-0.1)

    def test_max_drawdown(self):
        eq = np.array([100.0, 120.0, 90.0, 95.0])
        assert max_drawdown_from_equity(eq) == pytest.approx(0.25)


class TestSimulatePaths:
    def test_reshuffle_preserves_sum(self):
        pnls = np.array([10.0, -5.0, 7.0, -2.0])
        paths = simulate_paths(
            pnls,
            method="trade_reshuffle",
            iterations=20,
            initial_capital=1000.0,
            seed=1,
            series_kind="pnl",
        )
        assert paths.shape == (20, 5)
        expected_final = 1000.0 + pnls.sum()
        assert np.allclose(paths[:, -1], expected_final)

    def test_bootstrap_shape_and_seed_repro(self):
        pnls = np.array([1.0, -1.0, 2.0, -0.5, 0.5])
        a = simulate_paths(
            pnls,
            method="trade_bootstrap",
            iterations=50,
            initial_capital=100.0,
            seed=42,
            series_kind="pnl",
        )
        b = simulate_paths(
            pnls,
            method="trade_bootstrap",
            iterations=50,
            initial_capital=100.0,
            seed=42,
            series_kind="pnl",
        )
        assert np.allclose(a, b)

    def test_return_bootstrap_compound(self):
        rets = np.array([0.01, -0.01, 0.02])
        paths = simulate_paths(
            rets,
            method="return_bootstrap",
            iterations=10,
            initial_capital=100.0,
            seed=0,
            series_kind="return",
        )
        assert paths.shape == (10, 4)
        assert np.allclose(paths[:, 0], 100.0)

    def test_invalid_iterations(self):
        with pytest.raises(ValueError):
            simulate_paths(
                np.array([1.0, 2.0]),
                method="trade_bootstrap",
                iterations=0,
                initial_capital=1.0,
                seed=None,
                series_kind="pnl",
            )


class TestPercentileCurves:
    def test_p50_between_p5_p95(self):
        rng = np.random.default_rng(0)
        paths = 100 + np.cumsum(rng.normal(0, 1, size=(200, 30)), axis=1)
        paths = np.concatenate([np.full((200, 1), 100.0), paths], axis=1)
        curves = percentile_curves_from_paths(paths, (5, 50, 95))
        for i in range(len(curves["p50"])):
            assert curves["p5"][i]["equity"] <= curves["p50"][i]["equity"]
            assert curves["p50"][i]["equity"] <= curves["p95"][i]["equity"]


class TestMonteCarloRunner:
    def _baseline_with_trades(self, n_trades: int = 12) -> VectorResult:
        pnls = [10.0, -4.0, 6.0, -2.0, 8.0, -5.0, 3.0, -1.0, 7.0, -3.0, 2.0, -6.0][
            :n_trades
        ]
        equity = 100000.0
        curve = [{"date": "2020-01-01", "equity": equity}]
        trades = []
        for i, p in enumerate(pnls):
            equity += p
            trades.append({"action": "SELL", "profit": p})
            curve.append({"date": f"2020-01-{i + 2:02d}", "equity": equity})
        return VectorResult(
            metrics={}, equity_curve=curve, trades=trades, signals=pd.Series()
        )

    def test_trade_bootstrap_report(self):
        from unittest.mock import MagicMock

        mock_ex = MagicMock()
        mock_ex.config = VectorConfig(initial_capital=100000.0)
        runner = MonteCarloRunner(executor=mock_ex)
        report = runner.run(
            SmaCrossStrategy,
            pd.DataFrame({"close": [1, 2, 3]}),
            params={},
            config=MonteCarloConfig(iterations=100, method="trade_bootstrap", seed=7),
            baseline=self._baseline_with_trades(12),
        )
        assert report.n_paths == 100
        assert "p5" in report.percentile_curves
        assert "p50" in report.percentile_curves
        assert "p95" in report.percentile_curves
        assert report.worst_drawdown >= 0
        assert report.method_used == "trade_bootstrap"

    def test_reshuffle_final_return_constant(self):
        from unittest.mock import MagicMock

        mock_ex = MagicMock()
        mock_ex.config = VectorConfig(initial_capital=100000.0)
        runner = MonteCarloRunner(executor=mock_ex)
        report = runner.run(
            SmaCrossStrategy,
            pd.DataFrame({"close": [1]}),
            config=MonteCarloConfig(iterations=30, method="trade_reshuffle", seed=1),
            baseline=self._baseline_with_trades(10),
        )
        p5 = report.percentile_curves["p5"][-1]["equity"]
        p95 = report.percentile_curves["p95"][-1]["equity"]
        assert p5 == pytest.approx(p95, rel=0, abs=0.01)

    def test_fallback_to_return_bootstrap_when_few_trades(self):
        from unittest.mock import MagicMock

        mock_ex = MagicMock()
        mock_ex.config = VectorConfig(initial_capital=100000.0)
        runner = MonteCarloRunner(executor=mock_ex)
        report = runner.run(
            SmaCrossStrategy,
            pd.DataFrame({"close": [1]}),
            config=MonteCarloConfig(
                iterations=40, method="trade_bootstrap", seed=2, min_trades=20
            ),
            baseline=self._baseline_with_trades(3),
        )
        assert report.method_used == "return_bootstrap"

    def test_rejects_non_vectorizable(self):
        class Bad(Strategy):
            def on_bar(self, ctx, bar):
                pass

        runner = MonteCarloRunner(vector_config=VectorConfig())
        with pytest.raises(ValueError, match="矢量化"):
            runner.run(Bad, pd.DataFrame({"close": range(50)}))


@pytest.mark.asyncio
class TestMonteCarloEndpoint:
    async def test_endpoint_maps_error(self):
        from backend.routers.backtest import MonteCarloRequest, monte_carlo_endpoint

        with patch(
            "backend.routers.backtest.run_monte_carlo",
            new=AsyncMock(side_effect=MonteCarloError("too short")),
        ):
            with pytest.raises(HTTPException) as ei:
                await monte_carlo_endpoint(MonteCarloRequest(ticker="US.AAPL"))
            assert ei.value.status_code == 400
            assert "too short" in ei.value.detail


@pytest.mark.asyncio
async def test_unknown_strategy_normalized():
    with pytest.raises(MonteCarloError):
        await run_monte_carlo(MonteCarloParams(ticker="US.AAPL", strategy_key="nope"))
