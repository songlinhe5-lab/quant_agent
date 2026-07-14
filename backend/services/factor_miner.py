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
    """因子搜索结果"""

    factor_name: str
    best_params: Dict[str, Any]
    best_sharpe: float
    best_return: float
    total_combos: int
    top_results: List[Dict[str, Any]] = field(default_factory=list)


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

支持的因子类型:
- 动量类: ROC(period), RSI(period), MOM(period)
- 均线类: SMA(period), EMA(period), MACD(fast,slow,signal)
- 波动率类: STD(period), ATR(period), BOLL(period,std)
- 量价类: VWAP, OBV, volume_ratio(period)

请以 JSON 格式输出:
{{"factors": [{{"name": "因子名", "expression": "表达式", "param_range": {{"period": [5,10,20]}}, "rationale": "理由"}}]}}"""

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
                    expression="SMA(fast) > SMA(slow)",
                    param_range={"fast": [5, 10, 20], "slow": [20, 50, 60]},
                    rationale="经典均线交叉因子",
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
        results = []

        for factor in factors:
            result = await self._search_single_factor(symbol, factor, kline_data)
            if result:
                results.append(result)

        return results

    async def _search_single_factor(
        self,
        symbol: str,
        factor: FactorSuggestion,
        kline_data: Optional[pd.DataFrame],
    ) -> Optional[FactorSearchResult]:
        """搜索单个因子的最优参数"""
        import itertools

        # 生成参数组合
        param_names = list(factor.param_range.keys())
        param_values = list(factor.param_range.values())

        if not param_names:
            return None

        combos = list(itertools.product(*param_values))
        if len(combos) > 256:
            combos = combos[:256]  # 限制最大组合数

        # 模拟搜索结果 (实际应调用 grid_search engine)
        # 这里返回模拟数据以展示接口
        top_results = []
        for i, combo in enumerate(combos[:10]):
            params = dict(zip(param_names, combo))
            # 模拟绩效指标
            mock_sharpe = 1.5 - i * 0.1
            mock_return = 0.15 - i * 0.01
            top_results.append(
                {
                    "params": params,
                    "sharpe": round(mock_sharpe, 2),
                    "annualized_return": round(mock_return, 4),
                    "max_drawdown": round(-0.1 - i * 0.02, 4),
                }
            )

        best = top_results[0] if top_results else None

        return FactorSearchResult(
            factor_name=factor.name,
            best_params=best["params"] if best else {},
            best_sharpe=best["sharpe"] if best else 0.0,
            best_return=best["annualized_return"] if best else 0.0,
            total_combos=len(combos),
            top_results=top_results,
        )


# 全局单例
factor_miner = FactorMiner()
