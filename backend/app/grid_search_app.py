"""
参数网格搜索用例（BT-05）

加载行情 → GridSearchRunner（ProcessPool + Vector 快路径）→ 排序结果 + 夏普热力图。
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
from backend.engine.drivers.vector import VectorConfig
from backend.engine.grid_search import GridSearchConfig, GridSearchRunner


@dataclass
class GridSearchParams:
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
    target_metric: str = "sharpe"
    max_workers: int = 0
    heatmap_x: Optional[str] = None
    heatmap_y: Optional[str] = None


class GridSearchError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def run_grid_search(req: GridSearchParams) -> Dict[str, Any]:
    try:
        strategy_cls = resolve_strategy(req.strategy_key)
    except WalkForwardError as e:
        raise GridSearchError(e.message) from e

    if not req.param_grid:
        raise GridSearchError("param_grid 不能为空")

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
        raise GridSearchError(e.message) from e

    rename = {c: c.lower() for c in df.columns if c.lower() != c}
    if rename:
        df = df.rename(columns=rename)

    runner = GridSearchRunner(
        vector_config=VectorConfig(
            initial_capital=req.initial_capital,
            commission_pct=req.commission_pct,
            slippage_pct=req.slippage_pct,
        ),
        strategy_key=req.strategy_key,
    )
    try:
        report = runner.run(
            df,
            GridSearchConfig(
                param_grid=req.param_grid,
                base_params=req.base_params,
                target_metric=req.target_metric,
                max_workers=req.max_workers,
                heatmap_x=req.heatmap_x,
                heatmap_y=req.heatmap_y,
            ),
            strategy_cls=strategy_cls,
        )
    except ValueError as e:
        raise GridSearchError(str(e)) from e

    payload = report.to_dict()
    payload["data_source_msg"] = msg
    payload["strategy_key"] = req.strategy_key
    payload["ticker"] = req.ticker
    payload["strategies_available"] = sorted(STRATEGY_REGISTRY.keys())
    return {"status": "success", "data": payload}
