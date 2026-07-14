"""
AI-02 (能力) · 因子挖掘 API 端点

- POST /factor/suggest — LLM 建议因子
- POST /factor/search — 因子参数网格搜索
"""

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services.factor_miner import FactorSuggestion, factor_miner

router = APIRouter(prefix="/factor", tags=["factor"])


class FactorSuggestRequest(BaseModel):
    symbol: str
    objective: str = "maximize_sharpe"


class FactorSearchRequest(BaseModel):
    symbol: str
    factors: List[Dict[str, Any]]  # [{name, expression, param_range, rationale}]


@router.post("/suggest")
async def suggest_factors(req: FactorSuggestRequest):
    """LLM 建议因子"""
    suggestions = await factor_miner.suggest_factors(req.symbol, req.objective)
    return {
        "symbol": req.symbol,
        "objective": req.objective,
        "factors": [
            {
                "name": s.name,
                "expression": s.expression,
                "param_range": s.param_range,
                "rationale": s.rationale,
            }
            for s in suggestions
        ],
    }


@router.post("/search")
async def search_factors(req: FactorSearchRequest):
    """因子参数网格搜索"""
    factors = [
        FactorSuggestion(
            name=f.get("name", ""),
            expression=f.get("expression", ""),
            param_range=f.get("param_range", {}),
            rationale=f.get("rationale", ""),
        )
        for f in req.factors
    ]
    results = await factor_miner.grid_search_factors(req.symbol, factors)
    return {
        "symbol": req.symbol,
        "results": [
            {
                "factor_name": r.factor_name,
                "best_params": r.best_params,
                "best_sharpe": r.best_sharpe,
                "best_return": r.best_return,
                "total_combos": r.total_combos,
                "top_results": r.top_results[:5],
            }
            for r in results
        ],
    }
