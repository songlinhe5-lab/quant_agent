"""
BT-03 · Walk-Forward 滚动验证

消费 VectorBT 快路径（VectorExecutor）：滚动/锚定窗口拆分 IS 训练与 OOS 验证，
检测策略样本外性能漂移。

设计文档：docs/15 §4.2 · docs/TODO BT-03
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Type

import numpy as np
import pandas as pd

from backend.engine.drivers.vector import VectorConfig, VectorExecutor
from backend.engine.strategy import Strategy

logger = logging.getLogger(__name__)

_MAX_GRID_COMBOS = 48


@dataclass
class WalkForwardConfig:
    """滚动验证窗口配置。"""

    train_bars: int = 120
    test_bars: int = 40
    step_bars: Optional[int] = None  # 默认 = test_bars
    anchored: bool = False  # True=扩展训练集；False=滚动定长
    param_grid: Optional[Dict[str, Sequence[Any]]] = None
    target_metric: str = "sharpe"  # sharpe | total_return
    max_grid_combos: int = _MAX_GRID_COMBOS
    # 漂移阈值
    is_oos_sharpe_gap: float = 0.5  # IS 夏普 − OOS 夏普 超过则告警
    oos_sharpe_slope_warn: float = -0.15  # 折间 OOS 夏普线性斜率低于此告警
    min_folds: int = 2


@dataclass
class FoldMetrics:
    total_return: float
    sharpe: float
    max_drawdown: float
    n_bars: int


@dataclass
class WalkForwardFold:
    fold_index: int
    train_start: int
    train_end: int  # exclusive
    test_start: int
    test_end: int  # exclusive
    params: Dict[str, Any]
    is_metrics: FoldMetrics
    oos_metrics: FoldMetrics
    oos_equity: list = field(default_factory=list)


@dataclass
class WalkForwardReport:
    folds: List[WalkForwardFold]
    drift_detected: bool
    drift_reasons: List[str]
    summary: Dict[str, Any]
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "folds": [
                {
                    "fold_index": f.fold_index,
                    "train_range": [f.train_start, f.train_end],
                    "test_range": [f.test_start, f.test_end],
                    "params": f.params,
                    "is_metrics": _metrics_to_dict(f.is_metrics),
                    "oos_metrics": _metrics_to_dict(f.oos_metrics),
                }
                for f in self.folds
            ],
            "drift_detected": self.drift_detected,
            "drift_reasons": self.drift_reasons,
            "summary": self.summary,
            "config": self.config,
        }


def _metrics_to_dict(m: FoldMetrics) -> Dict[str, Any]:
    return {
        "total_return": round(m.total_return, 6),
        "sharpe": round(m.sharpe, 4),
        "max_drawdown": round(m.max_drawdown, 6),
        "n_bars": m.n_bars,
    }


def metrics_from_equity(equity_curve: list, initial_capital: float, periods_per_year: float = 252.0) -> FoldMetrics:
    """从权益曲线计算可比较的数值指标（不依赖 VectorBT 字符串 metrics）。"""
    if not equity_curve:
        return FoldMetrics(0.0, 0.0, 0.0, 0)

    eqs = np.asarray([float(p["equity"]) for p in equity_curve], dtype=float)
    n = len(eqs)
    if n < 2 or initial_capital <= 0:
        total = (eqs[-1] - initial_capital) / initial_capital if initial_capital else 0.0
        return FoldMetrics(float(total), 0.0, 0.0, n)

    total_return = float((eqs[-1] - initial_capital) / initial_capital)
    rets = np.diff(eqs) / np.maximum(eqs[:-1], 1e-12)
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    mean = float(np.mean(rets)) if len(rets) else 0.0
    sharpe = float(mean / std * np.sqrt(periods_per_year)) if std > 1e-12 else 0.0

    peak = np.maximum.accumulate(eqs)
    dd = (eqs - peak) / np.maximum(peak, 1e-12)
    max_dd = float(abs(dd.min())) if len(dd) else 0.0
    return FoldMetrics(total_return, sharpe, max_dd, n)


def generate_windows(n_bars: int, cfg: WalkForwardConfig) -> List[tuple[int, int, int, int]]:
    """生成 (train_start, train_end, test_start, test_end) 窗口列表。"""
    if cfg.train_bars < 10 or cfg.test_bars < 5:
        raise ValueError("train_bars>=10 and test_bars>=5 required")
    step = cfg.step_bars if cfg.step_bars is not None else cfg.test_bars
    if step < 1:
        raise ValueError("step_bars must be >= 1")

    windows: List[tuple[int, int, int, int]] = []
    train_end = cfg.train_bars
    while True:
        test_start = train_end
        test_end = test_start + cfg.test_bars
        if test_end > n_bars:
            break
        train_start = 0 if cfg.anchored else test_start - cfg.train_bars
        if train_start < 0:
            break
        windows.append((train_start, train_end, test_start, test_end))
        train_end += step
    return windows


def _expand_param_grid(
    base: Dict[str, Any], grid: Optional[Dict[str, Sequence[Any]]], max_combos: int
) -> List[Dict[str, Any]]:
    if not grid:
        return [dict(base)]
    keys = list(grid.keys())
    values = [list(grid[k]) for k in keys]
    combos: List[Dict[str, Any]] = []
    for prod in itertools.product(*values):
        params = dict(base)
        params.update(dict(zip(keys, prod)))
        combos.append(params)
        if len(combos) >= max_combos:
            logger.warning(
                "walk_forward_grid_truncated",
                extra={"max": max_combos, "keys": keys},
            )
            break
    return combos or [dict(base)]


def _score(m: FoldMetrics, target: str) -> float:
    if target == "total_return":
        return m.total_return
    return m.sharpe


class WalkForwardRunner:
    """Walk-Forward 执行器（强制矢量化策略）。"""

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
        config: Optional[WalkForwardConfig] = None,
    ) -> WalkForwardReport:
        if not strategy_cls.is_vectorizable():
            raise ValueError(f"{strategy_cls.__name__} 不支持矢量化；Walk-Forward 必须实现 signals()")

        cfg = config or WalkForwardConfig()
        base_params = dict(params or {})
        n = len(df)
        windows = generate_windows(n, cfg)
        if len(windows) < cfg.min_folds:
            raise ValueError(
                f"数据不足以生成 {cfg.min_folds} 个窗口 "
                f"(n={n}, train={cfg.train_bars}, test={cfg.test_bars}, got={len(windows)})"
            )

        folds: List[WalkForwardFold] = []
        for i, (ts, te, vs, ve) in enumerate(windows):
            train_df = df.iloc[ts:te]
            test_df = df.iloc[vs:ve]
            best_params, is_m = self._select_params(strategy_cls, train_df, base_params, cfg)
            oos_result = self.executor.run(strategy_cls, best_params, test_df)
            oos_m = metrics_from_equity(oos_result.equity_curve, self.executor.config.initial_capital)
            folds.append(
                WalkForwardFold(
                    fold_index=i,
                    train_start=ts,
                    train_end=te,
                    test_start=vs,
                    test_end=ve,
                    params=best_params,
                    is_metrics=is_m,
                    oos_metrics=oos_m,
                    oos_equity=oos_result.equity_curve,
                )
            )

        drift, reasons = detect_performance_drift(folds, cfg)
        summary = _summarize(folds)
        return WalkForwardReport(
            folds=folds,
            drift_detected=drift,
            drift_reasons=reasons,
            summary=summary,
            config={
                "train_bars": cfg.train_bars,
                "test_bars": cfg.test_bars,
                "step_bars": cfg.step_bars if cfg.step_bars is not None else cfg.test_bars,
                "anchored": cfg.anchored,
                "target_metric": cfg.target_metric,
                "n_folds": len(folds),
                "n_bars": n,
            },
        )

    def _select_params(
        self,
        strategy_cls: Type[Strategy],
        train_df: pd.DataFrame,
        base_params: Dict[str, Any],
        cfg: WalkForwardConfig,
    ) -> tuple[Dict[str, Any], FoldMetrics]:
        candidates = _expand_param_grid(base_params, cfg.param_grid, cfg.max_grid_combos)
        best_params = candidates[0]
        best_metrics = FoldMetrics(0.0, -1e9, 0.0, 0)
        best_score = float("-inf")

        for cand in candidates:
            result = self.executor.run(strategy_cls, cand, train_df)
            m = metrics_from_equity(result.equity_curve, self.executor.config.initial_capital)
            score = _score(m, cfg.target_metric)
            if score > best_score:
                best_score = score
                best_params = cand
                best_metrics = m
        return best_params, best_metrics


def detect_performance_drift(folds: Sequence[WalkForwardFold], cfg: WalkForwardConfig) -> tuple[bool, List[str]]:
    """检测 OOS 性能漂移。"""
    reasons: List[str] = []
    if len(folds) < 2:
        return False, reasons

    is_sharpes = np.array([f.is_metrics.sharpe for f in folds], dtype=float)
    oos_sharpes = np.array([f.oos_metrics.sharpe for f in folds], dtype=float)
    oos_rets = np.array([f.oos_metrics.total_return for f in folds], dtype=float)

    mean_is = float(np.mean(is_sharpes))
    mean_oos = float(np.mean(oos_sharpes))
    gap = mean_is - mean_oos
    if gap > cfg.is_oos_sharpe_gap:
        reasons.append(f"IS/OOS 夏普缺口过大: IS={mean_is:.3f} OOS={mean_oos:.3f} gap={gap:.3f}")

    # 折间 OOS 夏普趋势（简单线性斜率）
    x = np.arange(len(oos_sharpes), dtype=float)
    if len(x) >= 3 and float(np.std(oos_sharpes)) > 1e-9:
        slope = float(np.polyfit(x, oos_sharpes, 1)[0])
        if slope < cfg.oos_sharpe_slope_warn:
            reasons.append(f"OOS 夏普逐折恶化 slope={slope:.4f}")

    # 多数折 OOS 亏损而 IS 盈利
    is_pos = sum(1 for f in folds if f.is_metrics.total_return > 0)
    oos_neg = sum(1 for f in folds if f.oos_metrics.total_return < 0)
    if is_pos >= len(folds) * 0.6 and oos_neg >= len(folds) * 0.6:
        reasons.append(f"样本内多数盈利({is_pos}/{len(folds)}) 但样本外多数亏损({oos_neg}/{len(folds)})")

    # 末期相对初期显著变差
    if len(oos_rets) >= 3 and oos_rets[-1] < oos_rets[0] - 0.05:
        reasons.append(f"末折 OOS 收益相对首折下滑: {oos_rets[0]:.3f} → {oos_rets[-1]:.3f}")

    return bool(reasons), reasons


def _summarize(folds: Sequence[WalkForwardFold]) -> Dict[str, Any]:
    oos_rets = [f.oos_metrics.total_return for f in folds]
    oos_sharpes = [f.oos_metrics.sharpe for f in folds]
    is_sharpes = [f.is_metrics.sharpe for f in folds]
    return {
        "n_folds": len(folds),
        "oos_total_return_mean": round(float(np.mean(oos_rets)), 6),
        "oos_total_return_std": round(float(np.std(oos_rets)), 6),
        "oos_sharpe_mean": round(float(np.mean(oos_sharpes)), 4),
        "oos_sharpe_std": round(float(np.std(oos_sharpes)), 4),
        "is_sharpe_mean": round(float(np.mean(is_sharpes)), 4),
        "is_oos_sharpe_gap": round(float(np.mean(is_sharpes) - np.mean(oos_sharpes)), 4),
        "oos_positive_fold_ratio": round(sum(1 for r in oos_rets if r > 0) / max(len(oos_rets), 1), 4),
    }


# ─── 内置可矢量化策略（API / 单测公用） ───


class SmaCrossStrategy(Strategy):
    """均线穿越（Walk-Forward 默认策略）。"""

    def on_bar(self, ctx, bar) -> None:
        pass

    @classmethod
    def signals(cls, df: pd.DataFrame, params: Dict[str, Any]) -> Optional[pd.Series]:
        period = int(params.get("period", 20))
        close = df["close"] if "close" in df.columns else df["Close"]
        if len(df) < period:
            return pd.Series(0, index=df.index)
        sma = close.rolling(period).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[close > sma] = 1
        signal[close < sma] = -1
        return signal
