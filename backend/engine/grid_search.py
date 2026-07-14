"""
BT-05 · 参数网格搜索

笛卡尔积展开参数网格 → ProcessPoolExecutor 并发 Vector 快路径回测 →
按目标指标排序 + 夏普热力图矩阵（供 ECharts heatmap）。

设计文档：docs/15 §4.2 · docs/TODO BT-05 · docs/01 §5.4
"""

from __future__ import annotations

import itertools
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Type

import pandas as pd

from backend.engine.drivers.vector import VectorConfig, VectorExecutor
from backend.engine.strategy import Strategy
from backend.engine.walk_forward import metrics_from_equity

logger = logging.getLogger(__name__)

_MAX_COMBOS = 256

# ProcessPool worker 状态（initializer 注入）
_G_DF: Optional[pd.DataFrame] = None
_G_VCFG: Optional[Dict[str, Any]] = None
_G_STRATEGY_KEY: Optional[str] = None


def _strategy_from_key(key: str) -> Type[Strategy]:
    from backend.engine.walk_forward import SmaCrossStrategy

    registry: Dict[str, Type[Strategy]] = {"sma_cross": SmaCrossStrategy}
    if key not in registry:
        raise ValueError(f"未知 strategy_key={key!r}")
    return registry[key]


def _pool_init(df: pd.DataFrame, vcfg: Dict[str, Any], strategy_key: str) -> None:
    global _G_DF, _G_VCFG, _G_STRATEGY_KEY
    _G_DF = df
    _G_VCFG = vcfg
    _G_STRATEGY_KEY = strategy_key


def _pool_eval(params: Dict[str, Any]) -> Dict[str, Any]:
    assert _G_DF is not None and _G_VCFG is not None and _G_STRATEGY_KEY is not None
    return _eval_one(_G_STRATEGY_KEY, params, _G_DF, _G_VCFG)


def _eval_one(
    strategy_key: str,
    params: Dict[str, Any],
    df: pd.DataFrame,
    vcfg: Dict[str, Any],
) -> Dict[str, Any]:
    strategy_cls = _strategy_from_key(strategy_key)
    cfg = VectorConfig(**vcfg)
    executor = VectorExecutor(cfg)
    try:
        result = executor.run(strategy_cls, params, df)
        m = metrics_from_equity(result.equity_curve, cfg.initial_capital)
        return {
            "params": dict(params),
            "sharpe": round(m.sharpe, 6),
            "total_return": round(m.total_return, 6),
            "max_drawdown": round(m.max_drawdown, 6),
            "ok": True,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001 — 单格失败不拖垮整网
        logger.warning("grid_search_combo_failed", extra={"params": params, "error": str(e)})
        return {
            "params": dict(params),
            "sharpe": float("-inf"),
            "total_return": float("-inf"),
            "max_drawdown": 1.0,
            "ok": False,
            "error": str(e),
        }


@dataclass
class GridSearchConfig:
    param_grid: Dict[str, Sequence[Any]] = field(default_factory=dict)
    base_params: Dict[str, Any] = field(default_factory=dict)
    target_metric: str = "sharpe"  # sharpe | total_return | max_drawdown
    max_combos: int = _MAX_COMBOS
    max_workers: int = 0  # 0 → min(4, cpu_count)；1 → 串行
    heatmap_x: Optional[str] = None
    heatmap_y: Optional[str] = None


@dataclass
class GridSearchReport:
    results: List[Dict[str, Any]]
    best: Optional[Dict[str, Any]]
    heatmap: Dict[str, Any]
    n_combos: int
    n_ok: int
    workers: int
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": self.results,
            "best": self.best,
            "heatmap": self.heatmap,
            "n_combos": self.n_combos,
            "n_ok": self.n_ok,
            "workers": self.workers,
            "config": self.config,
        }


def expand_param_grid(
    base: Dict[str, Any],
    grid: Dict[str, Sequence[Any]],
    max_combos: int = _MAX_COMBOS,
) -> List[Dict[str, Any]]:
    if not grid:
        raise ValueError("param_grid 不能为空")
    keys = list(grid.keys())
    values = [list(grid[k]) for k in keys]
    if any(len(v) == 0 for v in values):
        raise ValueError("param_grid 各维至少 1 个取值")
    combos: List[Dict[str, Any]] = []
    for prod in itertools.product(*values):
        params = dict(base)
        params.update(dict(zip(keys, prod)))
        combos.append(params)
        if len(combos) >= max_combos:
            logger.warning("grid_search_truncated", extra={"max": max_combos, "keys": keys})
            break
    return combos


def build_heatmap(
    results: List[Dict[str, Any]],
    param_grid: Dict[str, Sequence[Any]],
    *,
    metric: str = "sharpe",
    x_param: Optional[str] = None,
    y_param: Optional[str] = None,
    fixed_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    构建 ECharts heatmap 友好结构。

    超过 2 维时：其余参数固定为 best / fixed_params 切片。
    """
    keys = list(param_grid.keys())
    if not keys:
        return {
            "x_param": None,
            "y_param": None,
            "x_values": [],
            "y_values": [],
            "matrix": [],
            "echarts_data": [],
            "metric": metric,
            "fixed_params": {},
        }

    x_param = x_param or keys[0]
    if x_param not in param_grid:
        raise ValueError(f"heatmap_x={x_param!r} 不在 param_grid")
    if y_param is None and len(keys) > 1:
        y_param = keys[1] if keys[1] != x_param else (keys[2] if len(keys) > 2 else None)
    if y_param is not None and y_param not in param_grid:
        raise ValueError(f"heatmap_y={y_param!r} 不在 param_grid")

    fixed = dict(fixed_params or {})
    for k in keys:
        if k in (x_param, y_param):
            continue
        if k not in fixed and results:
            fixed[k] = results[0]["params"].get(k)

    x_values = list(param_grid[x_param])
    y_values = list(param_grid[y_param]) if y_param else ["_"]

    lookup: Dict[tuple, float] = {}
    for r in results:
        if not r.get("ok", True):
            continue
        p = r["params"]
        if any(p.get(k) != v for k, v in fixed.items()):
            continue
        key = (p.get(x_param), p.get(y_param) if y_param else "_")
        lookup[key] = float(r.get(metric, float("nan")))

    matrix: List[List[Optional[float]]] = []
    echarts_data: List[List[Any]] = []
    for yi, yv in enumerate(y_values):
        row: List[Optional[float]] = []
        for xi, xv in enumerate(x_values):
            val = lookup.get((xv, yv if y_param else "_"))
            row.append(None if val is None else round(val, 6))
            if val is not None:
                echarts_data.append([xi, yi, round(val, 6)])
        matrix.append(row)

    return {
        "x_param": x_param,
        "y_param": y_param,
        "x_values": x_values,
        "y_values": y_values,
        "matrix": matrix,
        "echarts_data": echarts_data,
        "metric": metric,
        "fixed_params": fixed,
    }


class GridSearchRunner:
    """参数网格搜索（可 ProcessPool 并发）。"""

    def __init__(
        self,
        vector_config: Optional[VectorConfig] = None,
        strategy_key: str = "sma_cross",
    ) -> None:
        self.vector_config = vector_config or VectorConfig()
        self.strategy_key = strategy_key

    def run(
        self,
        df: pd.DataFrame,
        config: GridSearchConfig,
        strategy_cls: Optional[Type[Strategy]] = None,
    ) -> GridSearchReport:
        if strategy_cls is not None and not strategy_cls.is_vectorizable():
            raise ValueError(f"{strategy_cls.__name__} 不支持矢量化；网格搜索须实现 signals()")
        if strategy_cls is not None:
            # 校验通过即可；进程池仍按 strategy_key 解析（需可 pickle 的注册表键）
            pass

        combos = expand_param_grid(config.base_params, dict(config.param_grid), config.max_combos)
        vcfg = {
            "initial_capital": self.vector_config.initial_capital,
            "commission_pct": self.vector_config.commission_pct,
            "slippage_pct": self.vector_config.slippage_pct,
            "freq": self.vector_config.freq,
        }

        cpu = os.cpu_count() or 2
        workers = config.max_workers if config.max_workers > 0 else min(4, cpu)
        workers = max(1, min(workers, len(combos)))

        if workers == 1:
            raw = [_eval_one(self.strategy_key, p, df, vcfg) for p in combos]
        else:
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_pool_init,
                initargs=(df, vcfg, self.strategy_key),
            ) as pool:
                raw = list(pool.map(_pool_eval, combos))

        metric = config.target_metric
        if metric not in ("sharpe", "total_return", "max_drawdown"):
            raise ValueError(f"不支持的 target_metric={metric!r}")

        ok_results = [r for r in raw if r.get("ok")]
        reverse = metric != "max_drawdown"
        ok_results.sort(key=lambda r: r.get(metric, 0.0), reverse=reverse)

        # 产品要求：热力图固定用夏普矩阵；排序仍按 target_metric
        heatmap = build_heatmap(
            ok_results,
            dict(config.param_grid),
            metric="sharpe",
            x_param=config.heatmap_x,
            y_param=config.heatmap_y,
            fixed_params=ok_results[0]["params"] if ok_results else None,
        )

        return GridSearchReport(
            results=ok_results,
            best=ok_results[0] if ok_results else None,
            heatmap=heatmap,
            n_combos=len(combos),
            n_ok=len(ok_results),
            workers=workers,
            config={
                "target_metric": metric,
                "param_keys": list(config.param_grid.keys()),
                "max_combos": config.max_combos,
            },
        )
