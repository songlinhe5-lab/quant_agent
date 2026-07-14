"""
蒙特卡洛压测用例（BT-04）

加载行情 → 基线 Vector 回测 → 交易重排/自助抽样 → 分位曲线报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from backend.app.backtest_app import BacktestDataError, BacktestParams, load_backtest_frame
from backend.app.walk_forward_app import (
    STRATEGY_REGISTRY,
    WalkForwardError,
    resolve_strategy,
)
from backend.engine.drivers.vector import VectorConfig
from backend.engine.monte_carlo import MonteCarloConfig, MonteCarloRunner

MethodName = Literal["trade_reshuffle", "trade_bootstrap", "return_bootstrap"]


@dataclass
class MonteCarloParams:
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
    iterations: int = 1000
    method: MethodName = "trade_bootstrap"
    seed: Optional[int] = 42


class MonteCarloError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def run_monte_carlo(req: MonteCarloParams) -> Dict[str, Any]:
    try:
        strategy_cls = resolve_strategy(req.strategy_key)
    except WalkForwardError as e:
        raise MonteCarloError(e.message) from e

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
        raise MonteCarloError(e.message) from e

    rename = {c: c.lower() for c in df.columns if c.lower() != c}
    if rename:
        df = df.rename(columns=rename)

    runner = MonteCarloRunner(
        vector_config=VectorConfig(
            initial_capital=req.initial_capital,
            commission_pct=req.commission_pct,
            slippage_pct=req.slippage_pct,
        )
    )
    try:
        report = runner.run(
            strategy_cls,
            df,
            params=req.params,
            config=MonteCarloConfig(
                iterations=req.iterations,
                method=req.method,
                seed=req.seed,
            ),
        )
    except ValueError as e:
        raise MonteCarloError(str(e)) from e

    payload = report.to_dict()
    payload["data_source_msg"] = msg
    payload["strategy_key"] = req.strategy_key
    payload["ticker"] = req.ticker
    payload["strategies_available"] = sorted(STRATEGY_REGISTRY.keys())
    return {"status": "success", "data": payload}
