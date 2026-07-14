"""
BT-06 · 过拟合检测

1. Deflated Sharpe Ratio（Bailey & López de Prado, 2014）— 校正多重试炼选择偏差
2. 参数敏感性：相邻参数格夏普悬崖 → 过拟合警告

消费 BT-05 网格结果（或注入 results）；不重复造回测内核。

设计文档：docs/15 §4.2 · docs/TODO BT-06 · MASTER_REVIEW（PBO / Deflated Sharpe）
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_EULER = 0.5772156649015329


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """标准正态分位数（Acklam 有理近似，精度对 DSR 足够）。"""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    # Coefficients for central region
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def sharpe_variance(
    sr: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Sharpe 估计量方差（非正态修正）。

    V[SR] ≈ (1 - skew*SR + ((kurtosis-1)/4)*SR^2) / (T-1)
    """
    t = max(int(n_obs) - 1, 1)
    return (1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * (sr**2)) / t


def expected_max_sharpe(n_trials: int, sr_var: float) -> float:
    """零假设（真实 SR=0）下 N 次试验最大夏普的期望上界 SR*。"""
    n = max(int(n_trials), 1)
    if sr_var <= 0:
        return 0.0
    # Φ^{-1}(1 - 1/N) 与 Φ^{-1}(1 - 1/(N e))
    p1 = max(min(1.0 - 1.0 / n, 1.0 - 1e-12), 1e-12)
    p2 = max(min(1.0 - 1.0 / (n * math.e), 1.0 - 1e-12), 1e-12)
    z = (1.0 - _EULER) * norm_ppf(p1) + _EULER * norm_ppf(p2)
    return math.sqrt(sr_var) * z


def deflated_sharpe_ratio(
    observed_sr: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> Dict[str, float]:
    """
    返回 DSR 概率及中间量。

    DSR = Φ( (SR̂ - SR*) / σ_SR ) ∈ (0,1)
    解读：接近 1 → 校正多重试炼后仍显著；偏低 → 可能过拟合。
    """
    sr_var = sharpe_variance(observed_sr, n_obs, skew, kurtosis)
    sr_star = expected_max_sharpe(n_trials, sr_var)
    sigma = math.sqrt(max(sr_var, 1e-18))
    z = (observed_sr - sr_star) / sigma
    dsr = norm_cdf(z)
    return {
        "dsr": float(dsr),
        "observed_sr": float(observed_sr),
        "sr_star": float(sr_star),
        "sr_variance": float(sr_var),
        "z_score": float(z),
        "n_trials": float(n_trials),
        "n_obs": float(n_obs),
        "skew": float(skew),
        "kurtosis": float(kurtosis),
    }


def returns_moments_from_equity(equity_curve: list) -> Tuple[float, float, int]:
    """从权益曲线估计日收益 skew / kurtosis / n_obs。"""
    if not equity_curve or len(equity_curve) < 3:
        return 0.0, 3.0, max(len(equity_curve), 0)
    eqs = np.asarray([float(p["equity"]) for p in equity_curve], dtype=float)
    rets = np.diff(eqs) / np.maximum(eqs[:-1], 1e-12)
    if len(rets) < 3:
        return 0.0, 3.0, len(rets) + 1
    # Fisher kurtosis → Pearson (normal=3)
    mean = float(np.mean(rets))
    std = float(np.std(rets, ddof=1)) or 1e-12
    z = (rets - mean) / std
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))  # Pearson
    return skew, kurt, len(rets) + 1


@dataclass
class CliffFinding:
    params: Dict[str, Any]
    sharpe: float
    neighbor_params: Dict[str, Any]
    neighbor_sharpe: float
    drop: float
    axis: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "params": self.params,
            "sharpe": round(self.sharpe, 6),
            "neighbor_params": self.neighbor_params,
            "neighbor_sharpe": round(self.neighbor_sharpe, 6),
            "drop": round(self.drop, 6),
            "axis": self.axis,
        }


@dataclass
class SensitivityReport:
    cliffs: List[CliffFinding] = field(default_factory=list)
    best_params: Optional[Dict[str, Any]] = None
    best_sharpe: Optional[float] = None
    max_cliff_drop: float = 0.0
    cliff_detected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cliffs": [c.to_dict() for c in self.cliffs],
            "best_params": self.best_params,
            "best_sharpe": None if self.best_sharpe is None else round(self.best_sharpe, 6),
            "max_cliff_drop": round(self.max_cliff_drop, 6),
            "cliff_detected": self.cliff_detected,
        }


def _param_key(params: Dict[str, Any]) -> tuple:
    return tuple(sorted((k, params[k]) for k in sorted(params.keys())))


def detect_param_cliffs(
    results: Sequence[Dict[str, Any]],
    param_grid: Dict[str, Sequence[Any]],
    *,
    cliff_abs: float = 0.5,
    cliff_rel: float = 0.35,
    around_best_only: bool = True,
) -> SensitivityReport:
    """
    检测相邻参数格性能悬崖。

    悬崖定义：某格夏普相对某一邻格下降 drop，且
      drop >= cliff_abs  或  drop / max(|sharpe|, eps) >= cliff_rel
    """
    ok = [r for r in results if r.get("ok", True) and math.isfinite(r.get("sharpe", float("nan")))]
    if not ok:
        return SensitivityReport()

    ok_sorted = sorted(ok, key=lambda r: r["sharpe"], reverse=True)
    best = ok_sorted[0]
    lookup = {_param_key(r["params"]): r for r in ok}

    axes = list(param_grid.keys())
    value_index = {k: {v: i for i, v in enumerate(param_grid[k])} for k in axes}

    focus = [best] if around_best_only else ok
    cliffs: List[CliffFinding] = []

    for cell in focus:
        p = cell["params"]
        sr = float(cell["sharpe"])
        for axis in axes:
            vals = list(param_grid[axis])
            idx = value_index[axis].get(p.get(axis))
            if idx is None:
                continue
            for ni in (idx - 1, idx + 1):
                if ni < 0 or ni >= len(vals):
                    continue
                neighbor = dict(p)
                neighbor[axis] = vals[ni]
                nr = lookup.get(_param_key(neighbor))
                if nr is None:
                    continue
                nsr = float(nr["sharpe"])
                drop = sr - nsr
                if drop < 0:
                    continue  # 只关心从本格向下坠落（对 best 尤其关键）
                rel = drop / max(abs(sr), 1e-9)
                if drop >= cliff_abs or rel >= cliff_rel:
                    cliffs.append(
                        CliffFinding(
                            params=dict(p),
                            sharpe=sr,
                            neighbor_params=neighbor,
                            neighbor_sharpe=nsr,
                            drop=drop,
                            axis=axis,
                        )
                    )

    cliffs.sort(key=lambda c: c.drop, reverse=True)
    max_drop = cliffs[0].drop if cliffs else 0.0
    return SensitivityReport(
        cliffs=cliffs,
        best_params=dict(best["params"]),
        best_sharpe=float(best["sharpe"]),
        max_cliff_drop=max_drop,
        cliff_detected=bool(cliffs),
    )


@dataclass
class OverfitConfig:
    dsr_warn_below: float = 0.95
    cliff_abs: float = 0.5
    cliff_rel: float = 0.35
    around_best_only: bool = True


@dataclass
class OverfitReport:
    dsr: Dict[str, float]
    sensitivity: SensitivityReport
    overfit_warning: bool
    warnings: List[str]
    n_trials: int
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dsr": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.dsr.items()},
            "sensitivity": self.sensitivity.to_dict(),
            "overfit_warning": self.overfit_warning,
            "warnings": self.warnings,
            "n_trials": self.n_trials,
            "config": self.config,
        }


class OverfitAnalyzer:
    """基于网格结果 + 权益矩的过拟合分析器。"""

    def analyze(
        self,
        results: Sequence[Dict[str, Any]],
        param_grid: Dict[str, Sequence[Any]],
        *,
        n_obs: int,
        skew: float = 0.0,
        kurtosis: float = 3.0,
        config: Optional[OverfitConfig] = None,
    ) -> OverfitReport:
        cfg = config or OverfitConfig()
        ok = [r for r in results if r.get("ok", True) and math.isfinite(r.get("sharpe", float("nan")))]
        n_trials = max(len(ok), 1)
        if not ok:
            dsr = deflated_sharpe_ratio(0.0, n_trials, max(n_obs, 2), skew, kurtosis)
            sens = SensitivityReport()
            return OverfitReport(
                dsr=dsr,
                sensitivity=sens,
                overfit_warning=True,
                warnings=["无有效网格结果，无法评估过拟合"],
                n_trials=0,
                config={
                    "dsr_warn_below": cfg.dsr_warn_below,
                    "cliff_abs": cfg.cliff_abs,
                    "cliff_rel": cfg.cliff_rel,
                },
            )

        best_sr = float(max(r["sharpe"] for r in ok))
        dsr = deflated_sharpe_ratio(best_sr, n_trials, max(n_obs, 2), skew, kurtosis)
        sens = detect_param_cliffs(
            ok,
            param_grid,
            cliff_abs=cfg.cliff_abs,
            cliff_rel=cfg.cliff_rel,
            around_best_only=cfg.around_best_only,
        )

        warnings: List[str] = []
        if dsr["dsr"] < cfg.dsr_warn_below:
            warnings.append(
                f"Deflated Sharpe={dsr['dsr']:.3f} < {cfg.dsr_warn_below} "
                f"(SR*={dsr['sr_star']:.3f}, trials={n_trials})"
            )
        if sens.cliff_detected:
            warnings.append(
                f"最优参数邻域存在性能悬崖 max_drop={sens.max_cliff_drop:.3f} "
                f"({len(sens.cliffs)} 处)"
            )

        return OverfitReport(
            dsr=dsr,
            sensitivity=sens,
            overfit_warning=bool(warnings),
            warnings=warnings,
            n_trials=n_trials,
            config={
                "dsr_warn_below": cfg.dsr_warn_below,
                "cliff_abs": cfg.cliff_abs,
                "cliff_rel": cfg.cliff_rel,
            },
        )
