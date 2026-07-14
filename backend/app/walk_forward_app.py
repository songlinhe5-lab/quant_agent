"""
Walk-Forward 用例（BT-03）

加载行情 → WalkForwardRunner（VectorBT 快路径）→ 漂移报告。
Router 只做校验与 HTTP 映射。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from backend.app.backtest_app import BacktestDataError, BacktestParams, load_backtest_frame
from backend.engine.drivers.vector import VectorConfig
from backend.engine.strategy import Strategy
from backend.engine.walk_forward import (
    SmaCrossStrategy,
    WalkForwardConfig,
    WalkForwardRunner,
)

STRATEGY_REGISTRY: Dict[str, Type[Strategy]] = {
    "sma_cross": SmaCrossStrategy,
}


@dataclass
class WalkForwardParams:
    ticker: str
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = "sma_cross"
    params: Dict[str, Any] = field(default_factory=dict)
    param_grid: Optional[Dict[str, List[Any]]] = None
    train_bars: int = 120
    test_bars: int = 40
    step_bars: Optional[int] = None
    anchored: bool = False
    target_metric: str = "sharpe"


class WalkForwardError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def resolve_strategy(strategy_key: str) -> Type[Strategy]:
    key = (strategy_key or "sma_cross").lower()
    if key not in STRATEGY_REGISTRY:
        raise WalkForwardError(
            f"未知 strategy_key={strategy_key!r}，可选: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[key]


async def run_walk_forward(req: WalkForwardParams) -> Dict[str, Any]:
    """完整用例：拉数 → 滚动验证 → 报告 dict。"""
    strategy_cls = resolve_strategy(req.strategy_key)
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
        raise WalkForwardError(e.message) from e

    # 统一小写列名供 signals 使用
    rename = {c: c.lower() for c in df.columns if c.lower() != c}
    if rename:
        df = df.rename(columns=rename)

    cfg = WalkForwardConfig(
        train_bars=req.train_bars,
        test_bars=req.test_bars,
        step_bars=req.step_bars,
        anchored=req.anchored,
        param_grid=req.param_grid,
        target_metric=req.target_metric,
    )
    runner = WalkForwardRunner(
        vector_config=VectorConfig(
            initial_capital=req.initial_capital,
            commission_pct=req.commission_pct,
            slippage_pct=req.slippage_pct,
        )
    )
    try:
        report = runner.run(strategy_cls, df, params=req.params, config=cfg)
    except ValueError as e:
        raise WalkForwardError(str(e)) from e

    payload = report.to_dict()
    payload["data_source_msg"] = msg
    payload["strategy_key"] = req.strategy_key
    payload["ticker"] = req.ticker
    return {"status": "success", "data": payload}
