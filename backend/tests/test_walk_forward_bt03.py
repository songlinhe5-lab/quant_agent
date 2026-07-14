"""
BT-03 · Walk-Forward 滚动验证单测

覆盖：窗口生成、指标计算、漂移检测、Runner（Mock VectorExecutor）、API 用例解析。
禁止真实网络 / 真实 vectorbt 依赖（executor 可注入）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from backend.engine.drivers.vector import VectorConfig, VectorResult
from backend.engine.strategy import Strategy
from backend.engine.walk_forward import (
    SmaCrossStrategy,
    WalkForwardConfig,
    WalkForwardFold,
    WalkForwardRunner,
    detect_performance_drift,
    generate_windows,
    metrics_from_equity,
)
from backend.app.walk_forward_app import (
    STRATEGY_REGISTRY,
    WalkForwardError,
    resolve_strategy,
)


def make_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    return pd.DataFrame(
        {
            "open": prices * 0.999,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "close": prices,
            "volume": rng.integers(1e5, 1e6, n).astype(float),
        },
        index=dates,
    )


def _fake_result(initial: float, end_mult: float, n: int = 20) -> VectorResult:
    eqs = [initial * (1 + (end_mult - 1) * i / max(n - 1, 1)) for i in range(n)]
    curve = [{"date": f"2020-01-{i+1:02d}", "equity": e} for i, e in enumerate(eqs)]
    return VectorResult(
        metrics={},
        equity_curve=curve,
        trades=[],
        signals=pd.Series(dtype=int),
    )


class TestGenerateWindows:
    def test_rolling_windows(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, step_bars=20)
        wins = generate_windows(200, cfg)
        assert len(wins) == 5
        assert wins[0] == (0, 100, 100, 120)
        assert wins[1] == (20, 120, 120, 140)

    def test_anchored_windows(self):
        cfg = WalkForwardConfig(train_bars=50, test_bars=25, step_bars=25, anchored=True)
        wins = generate_windows(150, cfg)
        assert wins[0][0] == 0
        assert wins[1][0] == 0  # anchored expands from 0
        assert wins[1][1] == 75

    def test_insufficient_data_empty(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=50)
        assert generate_windows(120, cfg) == []


class TestMetricsFromEquity:
    def test_flat_equity_zero_sharpe(self):
        curve = [{"equity": 100000.0} for _ in range(10)]
        m = metrics_from_equity(curve, 100000.0)
        assert m.total_return == 0.0
        assert m.sharpe == 0.0

    def test_monotonic_up(self):
        curve = [{"equity": 100000 + i * 100} for i in range(50)]
        m = metrics_from_equity(curve, 100000.0)
        assert m.total_return > 0
        assert m.sharpe > 0
        assert m.max_drawdown == 0.0


class TestDriftDetection:
    def _fold(self, i, is_s, oos_s, is_r=0.1, oos_r=0.05):
        from backend.engine.walk_forward import FoldMetrics

        return WalkForwardFold(
            fold_index=i,
            train_start=0,
            train_end=10,
            test_start=10,
            test_end=20,
            params={},
            is_metrics=FoldMetrics(is_r, is_s, 0.1, 10),
            oos_metrics=FoldMetrics(oos_r, oos_s, 0.1, 10),
        )

    def test_no_drift_stable(self):
        folds = [self._fold(i, 1.0, 0.9, 0.05, 0.04) for i in range(4)]
        drift, reasons = detect_performance_drift(folds, WalkForwardConfig())
        assert drift is False
        assert reasons == []

    def test_is_oos_gap_flags_drift(self):
        folds = [self._fold(i, 2.0, 0.2) for i in range(3)]
        drift, reasons = detect_performance_drift(
            folds, WalkForwardConfig(is_oos_sharpe_gap=0.5)
        )
        assert drift is True
        assert any("缺口" in r for r in reasons)

    def test_declining_oos_sharpe_flags_drift(self):
        folds = [
            self._fold(0, 1.0, 1.5),
            self._fold(1, 1.0, 0.5),
            self._fold(2, 1.0, -0.5),
            self._fold(3, 1.0, -1.0),
        ]
        drift, reasons = detect_performance_drift(
            folds, WalkForwardConfig(oos_sharpe_slope_warn=-0.1)
        )
        assert drift is True
        assert any("恶化" in r for r in reasons)


class TestWalkForwardRunner:
    def test_rejects_non_vectorizable(self):
        class Bad(Strategy):
            def on_bar(self, ctx, bar):
                pass

        runner = WalkForwardRunner(vector_config=VectorConfig())
        with pytest.raises(ValueError, match="矢量化"):
            runner.run(Bad, make_df(200), config=WalkForwardConfig(train_bars=80, test_bars=20))

    def test_run_with_mock_executor(self):
        mock_ex = MagicMock()
        mock_ex.config = VectorConfig(initial_capital=100000.0)
        # IS slightly better than OOS but stable
        mock_ex.run.side_effect = lambda cls, params, df: _fake_result(
            100000.0, 1.05 if len(df) > 50 else 1.02, n=max(len(df), 5)
        )
        runner = WalkForwardRunner(executor=mock_ex)
        report = runner.run(
            SmaCrossStrategy,
            make_df(220),
            params={"period": 10},
            config=WalkForwardConfig(train_bars=80, test_bars=20, step_bars=20, min_folds=2),
        )
        assert len(report.folds) >= 2
        assert "oos_sharpe_mean" in report.summary
        assert isinstance(report.drift_detected, bool)
        d = report.to_dict()
        assert d["config"]["n_folds"] == len(report.folds)

    def test_param_grid_picks_best_on_train(self):
        mock_ex = MagicMock()
        mock_ex.config = VectorConfig(initial_capital=100000.0)

        def _run(cls, params, df):
            # period=15 在训练集上更优
            mult = 1.2 if params.get("period") == 15 else 1.01
            return _fake_result(100000.0, mult, n=max(len(df), 5))

        mock_ex.run.side_effect = _run
        runner = WalkForwardRunner(executor=mock_ex)
        report = runner.run(
            SmaCrossStrategy,
            make_df(200),
            params={},
            config=WalkForwardConfig(
                train_bars=80,
                test_bars=20,
                step_bars=40,
                param_grid={"period": [5, 15]},
                target_metric="total_return",
                min_folds=2,
            ),
        )
        assert all(f.params.get("period") == 15 for f in report.folds)

    def test_insufficient_folds_raises(self):
        runner = WalkForwardRunner(
            executor=MagicMock(config=VectorConfig(), run=MagicMock())
        )
        with pytest.raises(ValueError, match="不足以"):
            runner.run(
                SmaCrossStrategy,
                make_df(100),
                config=WalkForwardConfig(train_bars=80, test_bars=40, min_folds=3),
            )


class TestWalkForwardAppResolve:
    def test_registry_has_sma(self):
        assert "sma_cross" in STRATEGY_REGISTRY
        assert resolve_strategy("sma_cross") is SmaCrossStrategy

    def test_unknown_strategy(self):
        with pytest.raises(WalkForwardError):
            resolve_strategy("nope")


@pytest.mark.asyncio
class TestWalkForwardEndpoint:
    async def test_endpoint_maps_error(self):
        from unittest.mock import AsyncMock, patch

        from fastapi import HTTPException

        from backend.routers.backtest import WalkForwardRequest, walk_forward_endpoint

        with patch(
            "backend.routers.backtest.run_walk_forward",
            new=AsyncMock(side_effect=WalkForwardError("bad window")),
        ):
            with pytest.raises(HTTPException) as ei:
                await walk_forward_endpoint(
                    WalkForwardRequest(ticker="US.AAPL", train_bars=50, test_bars=20)
                )
            assert ei.value.status_code == 400
            assert "bad window" in ei.value.detail
