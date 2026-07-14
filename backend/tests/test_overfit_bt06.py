"""
BT-06 · 过拟合检测单测

覆盖：正态近似、DSR 单调性、参数悬崖、Analyzer 告警、API 错误映射。
禁止真实网络。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.app.overfit_app import OverfitError, OverfitParams, run_overfit_check
from backend.engine.overfit import (
    OverfitAnalyzer,
    OverfitConfig,
    deflated_sharpe_ratio,
    detect_param_cliffs,
    expected_max_sharpe,
    norm_cdf,
    norm_ppf,
    sharpe_variance,
)


class TestNormApprox:
    def test_cdf_symmetry(self):
        assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-6)
        assert norm_cdf(1.0) + norm_cdf(-1.0) == pytest.approx(1.0, abs=1e-5)

    def test_ppf_roundtrip(self):
        for p in (0.05, 0.5, 0.95):
            assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-4)


class TestDeflatedSharpe:
    def test_more_trials_raises_sr_star(self):
        v = sharpe_variance(1.0, 252)
        s1 = expected_max_sharpe(5, v)
        s2 = expected_max_sharpe(100, v)
        assert s2 > s1

    def test_high_sr_few_trials_high_dsr(self):
        # 高夏普 + 少试验 → DSR 应偏高
        dsr = deflated_sharpe_ratio(2.0, n_trials=3, n_obs=500)
        assert dsr["dsr"] > 0.9

    def test_low_sr_many_trials_low_dsr(self):
        # 弱夏普 + 海量试验 + 短样本 → DSR 应显著下降
        dsr = deflated_sharpe_ratio(0.2, n_trials=500, n_obs=60)
        assert dsr["dsr"] < 0.95
        assert dsr["sr_star"] > dsr["observed_sr"] or dsr["dsr"] < 0.5


class TestParamCliffs:
    def test_detects_cliff_around_best(self):
        grid = {"period": [10, 20, 30]}
        results = [
            {"params": {"period": 10}, "sharpe": 0.2, "ok": True},
            {"params": {"period": 20}, "sharpe": 2.0, "ok": True},  # best spike
            {"params": {"period": 30}, "sharpe": 0.3, "ok": True},
        ]
        sens = detect_param_cliffs(
            results, grid, cliff_abs=0.5, cliff_rel=0.3, around_best_only=True
        )
        assert sens.cliff_detected is True
        assert sens.best_params == {"period": 20}
        assert sens.max_cliff_drop >= 1.5
        assert any(c.axis == "period" for c in sens.cliffs)

    def test_smooth_grid_no_cliff(self):
        grid = {"period": [10, 20, 30]}
        results = [
            {"params": {"period": 10}, "sharpe": 1.0, "ok": True},
            {"params": {"period": 20}, "sharpe": 1.1, "ok": True},
            {"params": {"period": 30}, "sharpe": 1.05, "ok": True},
        ]
        sens = detect_param_cliffs(
            results, grid, cliff_abs=0.5, cliff_rel=0.35, around_best_only=True
        )
        assert sens.cliff_detected is False


class TestOverfitAnalyzer:
    def test_warning_when_dsr_low_or_cliff(self):
        # 制造大量虚假高夏普试验：多格低夏普 + 一格尖峰
        results = [{"params": {"a": i}, "sharpe": 0.1, "ok": True} for i in (1, 3)]
        results.append({"params": {"a": 2}, "sharpe": 1.2, "ok": True})
        # 再灌水 n_trials：Analyzer 用 ok 数量
        for i in range(50):
            results.append({"params": {"a": 1, "noise": i}, "sharpe": 0.05, "ok": True})

        # param_grid only has a — noise keys won't neighbor; still DSR should warn
        report = OverfitAnalyzer().analyze(
            results,
            {"a": [1, 2, 3]},
            n_obs=100,
            config=OverfitConfig(dsr_warn_below=0.95, cliff_abs=0.5),
        )
        assert report.overfit_warning is True
        assert any("Deflated Sharpe" in w or "悬崖" in w for w in report.warnings)

    def test_clean_case_no_warning(self):
        grid = {"period": [10, 20]}
        results = [
            {"params": {"period": 10}, "sharpe": 1.8, "ok": True},
            {"params": {"period": 20}, "sharpe": 1.7, "ok": True},
        ]
        report = OverfitAnalyzer().analyze(
            results,
            grid,
            n_obs=500,
            config=OverfitConfig(dsr_warn_below=0.5, cliff_abs=1.0, cliff_rel=0.9),
        )
        assert report.overfit_warning is False
        assert report.dsr["dsr"] >= 0.5


@pytest.mark.asyncio
class TestOverfitEndpoint:
    async def test_endpoint_maps_error(self):
        from backend.routers.backtest import OverfitRequest, overfit_endpoint

        with patch(
            "backend.routers.backtest.run_overfit_check",
            new=AsyncMock(side_effect=OverfitError("need grid")),
        ):
            with pytest.raises(HTTPException) as ei:
                await overfit_endpoint(
                    OverfitRequest(ticker="US.AAPL", param_grid={"period": [10]})
                )
            assert ei.value.status_code == 400
            assert "need grid" in ei.value.detail


@pytest.mark.asyncio
async def test_app_rejects_empty_grid():
    with pytest.raises(OverfitError):
        await run_overfit_check(OverfitParams(ticker="US.AAPL", param_grid={}))
