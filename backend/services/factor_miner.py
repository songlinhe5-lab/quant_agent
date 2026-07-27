"""
AI-02 (能力) · AI 驱动因子挖掘

- LLM 生成因子表达式 + 参数范围建议
- 结合现有 grid_search 基础设施进行参数搜索
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.services.llm_service import ModelTier, llm_service

logger = logging.getLogger(__name__)


@dataclass
class FactorSuggestion:
    """LLM 建议的因子"""

    name: str
    expression: str
    param_range: Dict[str, List[Any]] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class FactorSearchResult:
    """因子搜索结果(零幻觉: skipped 状态的 sharpe/return 为 None, 绝不捏造)"""

    factor_name: str
    best_params: Dict[str, Any]
    best_sharpe: Optional[float]
    best_return: Optional[float]
    total_combos: int
    top_results: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "success"  # success | skipped
    skipped_reason: Optional[str] = None
    source: str = "grid_search"


class FactorMiner:
    """AI 驱动因子挖掘器"""

    async def suggest_factors(self, symbol: str, objective: str = "maximize_sharpe") -> List[FactorSuggestion]:
        """
        LLM 生成因子表达式 + 参数范围建议。

        Args:
            symbol: 标的代码 (如 AAPL)
            objective: 优化目标 (maximize_sharpe / minimize_drawdown / maximize_return)
        """
        prompt = f"""作为量化因子挖掘专家，请为标的 {symbol} 设计交易因子。

优化目标: {objective}

请设计 3-5 个技术因子，每个因子包含:
1. 因子名称 (英文)
2. 因子表达式 (基于 OHLCV 数据)
3. 参数搜索范围
4. 设计理由

回测引擎当前可真实评估的因子类型(请优先设计此类):
- 均线类: SMA(period), EMA(period), 均线穿越(period)

注意: RSI/MACD/动量/波动率/量价等其他类型当前引擎尚未接入回测,
若建议将返回"暂不可回测"。参数范围请以 period 给出, 例如 {{"period": [10, 20, 50]}}。

请以 JSON 格式输出:
{{"factors": [{{"name": "因子名", "expression": "表达式", "param_range": {{"period": [10,20,50]}}, "rationale": "理由"}}]}}"""

        try:
            from pydantic import BaseModel

            class FactorResponse(BaseModel):
                factors: List[Dict[str, Any]]

            result = await llm_service.generate_pydantic(
                prompt=prompt,
                response_model=FactorResponse,
                system_prompt="你是量化因子挖掘专家，擅长设计alpha因子。",
                tier=ModelTier.FLAGSHIP,
            )

            suggestions = []
            for f in result.factors:
                suggestions.append(
                    FactorSuggestion(
                        name=f.get("name", ""),
                        expression=f.get("expression", ""),
                        param_range=f.get("param_range", {}),
                        rationale=f.get("rationale", ""),
                    )
                )
            return suggestions

        except Exception as e:
            logger.warning(f"[FactorMiner] LLM 因子建议失败: {e}")
            # 降级: 返回默认因子
            return [
                FactorSuggestion(
                    name="sma_cross",
                    expression="SMA(period) 穿越",
                    param_range={"period": [10, 20, 50, 120]},
                    rationale="经典单均线穿越因子(引擎可真实回测)",
                )
            ]

    async def grid_search_factors(
        self,
        symbol: str,
        factors: List[FactorSuggestion],
        kline_data: Optional[pd.DataFrame] = None,
    ) -> List[FactorSearchResult]:
        """
        对 LLM 建议的因子参数进行网格搜索。

        Args:
            symbol: 标的代码
            factors: LLM 建议的因子列表
            kline_data: K 线数据 (可选，若不提供则从 kline_warehouse 获取)
        """
        results: List[FactorSearchResult] = []
        for factor in factors:
            results.append(await self._search_single_factor(symbol, factor, kline_data))

        # 真实回测成功(有 sharpe)的结果优先并按夏普降序, 诚实 skipped 排后
        success = [r for r in results if r.status == "success"]
        skipped = [r for r in results if r.status == "skipped"]
        success.sort(
            key=lambda r: r.best_sharpe if r.best_sharpe is not None else -999.0,
            reverse=True,
        )
        return success + skipped

    async def _search_single_factor(
        self,
        symbol: str,
        factor: FactorSuggestion,
        kline_data: Optional[pd.DataFrame],
    ) -> FactorSearchResult:
        """对单个因子做真实网格搜索(零幻觉: 不做任何 mock 兜底)。

        仅对引擎已注册策略可回测的因子调用 run_grid_search; 其余诚实标记 skipped,
        绝不返回写死的假夏普/收益率。
        """
        strategy_key, param_grid = _resolve_backtest(factor)
        if strategy_key is None or not param_grid:
            reason = (
                "该因子类型暂无可回测策略(引擎当前仅支持均线穿越类 period 参数)"
                if strategy_key is None
                else "因子未提供可回测参数范围"
            )
            return FactorSearchResult(
                factor_name=factor.name,
                best_params={},
                best_sharpe=None,
                best_return=None,
                total_combos=0,
                status="skipped",
                skipped_reason=reason,
            )

        try:
            from backend.app.grid_search_app import GridSearchParams, run_grid_search

            resp = await run_grid_search(
                GridSearchParams(
                    ticker=symbol,
                    strategy_key=strategy_key,
                    param_grid=param_grid,
                    target_metric="sharpe",
                )
            )
        except Exception as e:  # noqa: BLE001 — 数据源/回测失败不致命, 诚实降级
            logger.warning(
                "factor_grid_search_failed",
                extra={"factor": factor.name, "error": str(e)},
            )
            return FactorSearchResult(
                factor_name=factor.name,
                best_params={},
                best_sharpe=None,
                best_return=None,
                total_combos=0,
                status="skipped",
                skipped_reason=f"回测执行失败: {e}",
            )

        data = resp.get("data") if isinstance(resp, dict) else None
        best = data.get("best") if data else None
        results = data.get("results", []) if data else []
        if best is None:
            return FactorSearchResult(
                factor_name=factor.name,
                best_params={},
                best_sharpe=None,
                best_return=None,
                total_combos=data.get("n_combos", 0) if data else 0,
                status="skipped",
                skipped_reason="无有效回测结果(行情不足或数据不可用)",
            )

        return FactorSearchResult(
            factor_name=factor.name,
            best_params=best.get("params", {}),
            best_sharpe=best.get("sharpe"),
            best_return=best.get("total_return"),
            total_combos=data.get("n_combos", 0) if data else 0,
            top_results=results[:5],
            status="success",
            source="grid_search",
        )


# ─── 因子 → 真实回测策略映射 (零幻觉: 仅映射引擎已注册策略) ───


def _resolve_backtest(factor: FactorSuggestion):
    """因子 -> (strategy_key, param_grid)。

    仅均线穿越类可真实回测(引擎当前仅注册 sma_cross, 单参数 period);
    其余因子返回 (None, None) 交由调用方诚实标记为 skipped。
    """
    text = " ".join([factor.name or "", factor.expression or "", factor.rationale or ""]).lower()
    is_ma = any(
        k in text
        for k in (
            "sma",
            "ema",
            "均线",
            "ma",
            "穿越",
            "cross",
            "金叉",
            "死叉",
            "moving average",
            "ma_cross",
        )
    )
    if not is_ma:
        return None, None
    return "sma_cross", {"period": _period_grid(factor.param_range)}


def _period_grid(param_range: Dict[str, List[Any]]) -> List[int]:
    """从因子的 param_range 抽取 period 整数网格(限制规模防组合爆炸)。"""
    default = [10, 20, 30, 60, 120, 250]
    if not param_range:
        return default
    for key in ("period", "fast", "slow", "n", "window"):
        if key in param_range and param_range[key]:
            return _to_int_grid(param_range[key], default)
    first = next(iter(param_range.values()), [])
    return _to_int_grid(first, default)


def _to_int_grid(values: List[Any], default: List[int]) -> List[int]:
    out: List[int] = []
    for v in values:
        try:
            out.append(int(round(float(v))))
        except (TypeError, ValueError):
            continue
    out = sorted(set(out))
    return out[:12] if out else default


# 全局单例
factor_miner = FactorMiner()
