"""
BT-05 · 参数网格搜索单测

覆盖：网格展开、热力图矩阵、串行 Runner、进程池路径（workers>1 mock）、API 错误映射。
禁止真实网络；默认 max_workers=1。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app.grid_search_app import GridSearchError, GridSearchParams, run_grid_search
from backend.engine.grid_search import (
    GridSearchConfig,
    GridSearchRunner,
    build_heatmap,
    expand_param_grid,
)
from backend.engine.walk_forward import SmaCrossStrategy


def make_df(n: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    prices = 100 + np.linspace(0, 10, n) + np.sin(np.linspace(0, 6, n))
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "close": prices,
            "volume": np.full(n, 1e6),
        },
        index=dates,
    )


class TestExpandParamGrid:
    def test_cartesian(self):
        combos = expand_param_grid({}, {"a": [1, 2], "b": [10, 20]})
        assert len(combos) == 4
        assert {"a": 1, "b": 10} in combos

    def test_truncates(self):
        combos = expand_param_grid({}, {"a": list(range(20)), "b": list(range(20))}, max_combos=10)
        assert len(combos) == 10

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            expand_param_grid({}, {})


class TestBuildHeatmap:
    def test_2d_matrix_and_echarts(self):
        results = [
            {"params": {"period": 10, "slow": 40}, "sharpe": 1.0, "ok": True},
            {"params": {"period": 20, "slow": 40}, "sharpe": 2.0, "ok": True},
            {"params": {"period": 10, "slow": 60}, "sharpe": 0.5, "ok": True},
            {"params": {"period": 20, "slow": 60}, "sharpe": 1.5, "ok": True},
        ]
        grid = {"period": [10, 20], "slow": [40, 60]}
        hm = build_heatmap(results, grid, metric="sharpe")
        assert hm["x_param"] == "period"
        assert hm["y_param"] == "slow"
        assert hm["matrix"][0][0] == 1.0
        assert hm["matrix"][0][1] == 2.0
        assert hm["matrix"][1][0] == 0.5
        assert len(hm["echarts_data"]) == 4
        assert hm["echarts_data"][0][:2] == [0, 0]

    def test_1d_heatmap(self):
        results = [
            {"params": {"period": 5}, "sharpe": 0.1, "ok": True},
            {"params": {"period": 10}, "sharpe": 0.3, "ok": True},
        ]
        hm = build_heatmap(results, {"period": [5, 10]}, metric="sharpe")
        assert hm["y_param"] is None
        assert hm["matrix"] == [[0.1, 0.3]]

    def test_3d_slice_uses_fixed(self):
        results = [
            {"params": {"a": 1, "b": 10, "c": 100}, "sharpe": 1.0, "ok": True},
            {"params": {"a": 2, "b": 10, "c": 100}, "sharpe": 2.0, "ok": True},
            {"params": {"a": 1, "b": 10, "c": 200}, "sharpe": 9.0, "ok": True},
        ]
        grid = {"a": [1, 2], "b": [10], "c": [100, 200]}
        # best first → fixed c=100 when sorting by sharpe elsewhere; pass fixed explicitly
        hm = build_heatmap(
            results,
            grid,
            metric="sharpe",
            fixed_params={"c": 100, "b": 10},
        )
        assert hm["fixed_params"]["c"] == 100
        assert hm["matrix"][0][0] == 1.0
        assert hm["matrix"][0][1] == 2.0


class TestGridSearchRunner:
    def test_serial_run_sorted_by_sharpe(self):
        def fake_eval(strategy_key, params, df, vcfg):
            period = int(params["period"])
            return {
                "params": dict(params),
                "sharpe": float(period),  # larger period → higher sharpe
                "total_return": 0.01 * period,
                "max_drawdown": 0.1,
                "ok": True,
                "error": None,
            }

        with patch("backend.engine.grid_search._eval_one", side_effect=fake_eval):
            runner = GridSearchRunner(strategy_key="sma_cross")
            report = runner.run(
                make_df(),
                GridSearchConfig(
                    param_grid={"period": [5, 15, 10]},
                    target_metric="sharpe",
                    max_workers=1,
                ),
                strategy_cls=SmaCrossStrategy,
            )
        assert report.n_combos == 3
        assert report.best["params"]["period"] == 15
        assert report.results[0]["sharpe"] >= report.results[-1]["sharpe"]
        assert report.heatmap["metric"] == "sharpe"
        assert report.workers == 1

    def test_process_pool_path_invoked(self):
        calls = {"n": 0}

        def fake_eval(params):
            calls["n"] += 1
            return {
                "params": dict(params),
                "sharpe": 1.0,
                "total_return": 0.1,
                "max_drawdown": 0.05,
                "ok": True,
                "error": None,
            }

        class FakePool:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def map(self, fn, combos):
                return [fake_eval(c) for c in combos]

        with patch("backend.engine.grid_search.ProcessPoolExecutor", FakePool):
            runner = GridSearchRunner(strategy_key="sma_cross")
            report = runner.run(
                make_df(40),
                GridSearchConfig(
                    param_grid={"period": [5, 10]},
                    max_workers=2,
                ),
                strategy_cls=SmaCrossStrategy,
            )
        assert report.n_ok == 2
        assert calls["n"] == 2
        assert report.workers == 2

    def test_rejects_non_vectorizable(self):
        from backend.engine.strategy import Strategy

        class Bad(Strategy):
            def on_bar(self, ctx, bar):
                pass

        runner = GridSearchRunner()
        with pytest.raises(ValueError, match="矢量化"):
            runner.run(
                make_df(30),
                GridSearchConfig(param_grid={"period": [5]}, max_workers=1),
                strategy_cls=Bad,
            )


@pytest.mark.asyncio
class TestGridSearchEndpoint:
    async def test_endpoint_maps_error(self):
        from backend.routers.backtest import GridSearchRequest, grid_search_endpoint

        with patch(
            "backend.routers.backtest.run_grid_search",
            new=AsyncMock(side_effect=GridSearchError("empty grid")),
        ):
            with pytest.raises(HTTPException) as ei:
                await grid_search_endpoint(GridSearchRequest(ticker="US.AAPL", param_grid={"period": [10]}))
            assert ei.value.status_code == 400
            assert "empty grid" in ei.value.detail


@pytest.mark.asyncio
async def test_app_rejects_empty_grid():
    with pytest.raises(GridSearchError):
        await run_grid_search(GridSearchParams(ticker="US.AAPL", param_grid={}))
