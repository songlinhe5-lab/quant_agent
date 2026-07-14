"""
过拟合检测用例（BT-06）

拉数 → 网格搜索（BT-05）→ Deflated Sharpe + 参数悬崖报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.backtest_app import BacktestDataError, BacktestParams, load_backtest_frame
from backend.app.walk_forward_app import (
    STRATEGY_REGISTRY,
    WalkForwardError,
    resolve_strategy,
)
from backend.engine.drivers.vector import VectorConfig, VectorExecutor
from backend.engine.grid_search import GridSearchConfig, GridSearchRunner
from backend.engine.overfit import (
    OverfitAnalyzer,
    OverfitConfig,
    returns_moments_from_equity,
)


@dataclass
class OverfitParams:
    ticker: str
    param_grid: Dict[str, List[Any]]
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = "sma_cross"
    base_params: Dict[str, Any] = field(default_factory=dict)
    max_workers: int = 1
    dsr_warn_below: float = 0.95
    cliff_abs: float = 0.5
    cliff_rel: float = 0.35


class OverfitError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def run_overfit_check(req: OverfitParams) -> Dict[str, Any]:
    try:
        strategy_cls = resolve_strategy(req.strategy_key)
    except WalkForwardError as e:
        raise OverfitError(e.message) from e

    if not req.param_grid:
        raise OverfitError("param_grid 不能为空（过拟合检测依赖多重试炼网格）")

    frame_req = BacktestParams(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        data_snapshot_id=req.data_snapshot_id,
    )
    try:
        df, msg = await load_backtest_frame(frame_req)
    except BacktestDataError as e:
        raise OverfitError(e.message) from e

    rename = {c: c.lower() for c in df.columns if c.lower() != c}
    if rename:
        df = df.rename(columns=rename)

    vcfg = VectorConfig(
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )
    grid_runner = GridSearchRunner(vector_config=vcfg, strategy_key=req.strategy_key)
    try:
        grid_report = grid_runner.run(
            df,
            GridSearchConfig(
                param_grid=req.param_grid,
                base_params=req.base_params,
                target_metric="sharpe",
                max_workers=req.max_workers,
            ),
            strategy_cls=strategy_cls,
        )
    except ValueError as e:
        raise OverfitError(str(e)) from e

    # 用最优参数再跑一次基线以取收益矩（n_obs / skew / kurt）
    best_params = (grid_report.best or {}).get("params") or dict(req.base_params)
    baseline = VectorExecutor(vcfg).run(strategy_cls, best_params, df)
    skew, kurt, n_obs = returns_moments_from_equity(baseline.equity_curve)

    analyzer = OverfitAnalyzer()
    report = analyzer.analyze(
        grid_report.results,
        req.param_grid,
        n_obs=n_obs or len(df),
        skew=skew,
        kurtosis=kurt,
        config=OverfitConfig(
            dsr_warn_below=req.dsr_warn_below,
            cliff_abs=req.cliff_abs,
            cliff_rel=req.cliff_rel,
        ),
    )

    payload = report.to_dict()
    payload["grid"] = {
        "best": grid_report.best,
        "n_combos": grid_report.n_combos,
        "n_ok": grid_report.n_ok,
        "heatmap": grid_report.heatmap,
        "top_results": grid_report.results[:10],
    }
    payload["data_source_msg"] = msg
    payload["strategy_key"] = req.strategy_key
    payload["ticker"] = req.ticker
    payload["strategies_available"] = sorted(STRATEGY_REGISTRY.keys())
    return {"status": "success", "data": payload}
