"""
BT-04 · 蒙特卡洛压测

对基线回测的交易 PnL（或日收益）做重排 / 自助抽样，生成 N 条权益路径，
输出 5%/50%/95% 分位曲线与最坏回撤。

消费 VectorBT 快路径（VectorExecutor）仅跑一次基线；路径生成纯 NumPy。

设计文档：docs/15 §4.2 · docs/TODO BT-04 · docs/01 §5.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence, Type

import numpy as np
import pandas as pd

from backend.engine.drivers.vector import VectorConfig, VectorExecutor, VectorResult
from backend.engine.strategy import Strategy
from backend.engine.walk_forward import metrics_from_equity

logger = logging.getLogger(__name__)

Method = Literal["trade_reshuffle", "trade_bootstrap", "return_bootstrap"]
_MIN_TRADES_FOR_TRADE_METHOD = 5
_MAX_ITERATIONS = 5000


@dataclass
class MonteCarloConfig:
    iterations: int = 1000
    method: Method = "trade_bootstrap"
    seed: Optional[int] = 42
    percentiles: Sequence[float] = (5.0, 50.0, 95.0)
    min_trades: int = _MIN_TRADES_FOR_TRADE_METHOD


@dataclass
class MonteCarloReport:
    method_used: str
    n_paths: int
    n_steps: int
    percentile_curves: Dict[str, List[Dict[str, float]]]
    worst_drawdown: float
    drawdown_percentiles: Dict[str, float]
    final_return_percentiles: Dict[str, float]
    baseline: Dict[str, Any]
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_used": self.method_used,
            "n_paths": self.n_paths,
            "n_steps": self.n_steps,
            "percentile_curves": self.percentile_curves,
            "worst_drawdown": round(self.worst_drawdown, 6),
            "drawdown_percentiles": {k: round(v, 6) for k, v in self.drawdown_percentiles.items()},
            "final_return_percentiles": {k: round(v, 6) for k, v in self.final_return_percentiles.items()},
            "baseline": self.baseline,
            "config": self.config,
        }


def extract_trade_pnls(trades: list) -> np.ndarray:
    """从 VectorResult.trades 提取已实现盈亏序列。"""
    pnls: List[float] = []
    for t in trades or []:
        if "profit" not in t:
            continue
        try:
            pnls.append(float(t["profit"]))
        except (TypeError, ValueError):
            continue
    return np.asarray(pnls, dtype=float)


def extract_daily_returns(equity_curve: list) -> np.ndarray:
    eqs = np.asarray([float(p["equity"]) for p in equity_curve], dtype=float)
    if len(eqs) < 2:
        return np.asarray([], dtype=float)
    return np.diff(eqs) / np.maximum(eqs[:-1], 1e-12)


def max_drawdown_from_equity(equity: np.ndarray) -> float:
    if equity.size < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.maximum(peak, 1e-12)
    return float(abs(dd.min()))


def simulate_paths(
    series: np.ndarray,
    *,
    method: Method,
    iterations: int,
    initial_capital: float,
    seed: Optional[int],
    series_kind: Literal["pnl", "return"],
) -> np.ndarray:
    """
    生成权益路径矩阵 shape=(iterations, n_steps+1)，含初始资金列。

    series_kind=pnl: 累加绝对盈亏
    series_kind=return: 复合日收益
    """
    if series.size == 0:
        raise ValueError("蒙特卡洛序列为空，无法抽样")
    if iterations < 1 or iterations > _MAX_ITERATIONS:
        raise ValueError(f"iterations 须在 1~{_MAX_ITERATIONS}")

    rng = np.random.default_rng(seed)
    n = series.size

    if method == "trade_reshuffle":
        paths = np.empty((iterations, n), dtype=float)
        for i in range(iterations):
            paths[i] = rng.permutation(series)
    elif method in ("trade_bootstrap", "return_bootstrap"):
        paths = rng.choice(series, size=(iterations, n), replace=True)
    else:
        raise ValueError(f"未知 method={method}")

    if series_kind == "pnl":
        equity = initial_capital + np.cumsum(paths, axis=1)
    else:
        equity = initial_capital * np.cumprod(1.0 + paths, axis=1)

    initial_col = np.full((iterations, 1), initial_capital, dtype=float)
    return np.concatenate([initial_col, equity], axis=1)


def percentile_curves_from_paths(
    equity_paths: np.ndarray, percentiles: Sequence[float]
) -> Dict[str, List[Dict[str, float]]]:
    """沿路径轴计算分位权益曲线。"""
    curves: Dict[str, List[Dict[str, float]]] = {}
    n_steps = equity_paths.shape[1]
    for p in percentiles:
        key = f"p{int(p)}" if float(p).is_integer() else f"p{p}"
        qs = np.percentile(equity_paths, p, axis=0)
        curves[key] = [{"step": int(i), "equity": round(float(qs[i]), 2)} for i in range(n_steps)]
    return curves


class MonteCarloRunner:
    """基线 Vector 回测 → 交易/收益蒙特卡洛。"""

    def __init__(
        self,
        executor: Optional[VectorExecutor] = None,
        vector_config: Optional[VectorConfig] = None,
    ) -> None:
        self.executor = executor or VectorExecutor(vector_config or VectorConfig())

    def run(
        self,
        strategy_cls: Type[Strategy],
        df: pd.DataFrame,
        params: Optional[Dict[str, Any]] = None,
        config: Optional[MonteCarloConfig] = None,
        baseline: Optional[VectorResult] = None,
    ) -> MonteCarloReport:
        if not strategy_cls.is_vectorizable():
            raise ValueError(f"{strategy_cls.__name__} 不支持矢量化；蒙特卡洛须实现 signals()")

        cfg = config or MonteCarloConfig()
        params = dict(params or {})
        initial = self.executor.config.initial_capital

        if baseline is None:
            baseline = self.executor.run(strategy_cls, params, df)

        base_metrics = metrics_from_equity(baseline.equity_curve, initial)
        pnls = extract_trade_pnls(baseline.trades)
        requested = cfg.method
        series_kind: Literal["pnl", "return"] = "pnl"
        series = pnls
        method_used: str = requested

        if requested == "return_bootstrap":
            series = extract_daily_returns(baseline.equity_curve)
            series_kind = "return"
            method_used = "return_bootstrap"
        elif len(pnls) < cfg.min_trades:
            logger.info(
                "monte_carlo_fallback_returns",
                extra={"n_trades": len(pnls), "min": cfg.min_trades},
            )
            series = extract_daily_returns(baseline.equity_curve)
            series_kind = "return"
            method_used = "return_bootstrap"
        else:
            series_kind = "pnl"
            method_used = requested

        if series.size < 2:
            raise ValueError("基线路径过短，无法进行蒙特卡洛抽样")

        sim_method: Method = "return_bootstrap" if method_used == "return_bootstrap" else requested

        equity_paths = simulate_paths(
            series,
            method=sim_method,
            iterations=cfg.iterations,
            initial_capital=initial,
            seed=cfg.seed,
            series_kind=series_kind,
        )

        dds = np.asarray(
            [max_drawdown_from_equity(equity_paths[i]) for i in range(equity_paths.shape[0])],
            dtype=float,
        )
        final_rets = (equity_paths[:, -1] - initial) / initial

        pcts = tuple(cfg.percentiles)
        curves = percentile_curves_from_paths(equity_paths, pcts)

        def _pct_map(arr: np.ndarray) -> Dict[str, float]:
            out: Dict[str, float] = {}
            for p in pcts:
                key = f"p{int(p)}" if float(p).is_integer() else f"p{p}"
                out[key] = float(np.percentile(arr, p))
            return out

        return MonteCarloReport(
            method_used=method_used,
            n_paths=int(equity_paths.shape[0]),
            n_steps=int(equity_paths.shape[1]),
            percentile_curves=curves,
            worst_drawdown=float(dds.max()) if dds.size else 0.0,
            drawdown_percentiles=_pct_map(dds),
            final_return_percentiles=_pct_map(final_rets),
            baseline={
                "total_return": round(base_metrics.total_return, 6),
                "sharpe": round(base_metrics.sharpe, 4),
                "max_drawdown": round(base_metrics.max_drawdown, 6),
                "n_trades": int(len(pnls)),
                "n_bars": int(len(baseline.equity_curve)),
            },
            config={
                "iterations": cfg.iterations,
                "method_requested": cfg.method,
                "seed": cfg.seed,
                "percentiles": list(pcts),
                "series_kind": series_kind,
                "series_length": int(series.size),
            },
        )
