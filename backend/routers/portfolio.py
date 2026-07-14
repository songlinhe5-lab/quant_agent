"""
TRADE-03 · 投资组合优化 API

端点:
- POST /portfolio/optimize — 组合优化
- GET  /portfolio/efficient-frontier — 有效前沿
- POST /portfolio/compare — 多模型对比
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.portfolio_optimizer import portfolio_optimizer

router = APIRouter(prefix="/portfolio", tags=["Portfolio Optimization"])
logger = logging.getLogger(__name__)


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class OptimizeReq(BaseModel):
    symbols: List[str]
    model: str = "markowitz"  # markowitz / risk_parity / max_sharpe / equal_weight
    max_weight: float = 0.3
    target_return: Optional[float] = None
    risk_free_rate: float = 0.02
    period: str = "1y"  # 1y / 3y / 5y


class CompareReq(BaseModel):
    symbols: List[str]
    max_weight: float = 0.3
    risk_free_rate: float = 0.02
    period: str = "1y"


class FrontierReq(BaseModel):
    symbols: List[str]
    n_points: int = 20
    max_weight: float = 0.3
    risk_free_rate: float = 0.02
    period: str = "1y"


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


async def _fetch_returns(symbols: List[str], period: str) -> pd.DataFrame:
    """
    从 kline_warehouse 获取历史收益率矩阵。

    开发环境: 使用 MockProvider 生成模拟数据。
    生产环境: 从 kline_warehouse 读取真实 K 线并计算日收益率。
    """
    try:
        from backend.services.kline_warehouse import kline_warehouse

        # 尝试从真实数据获取
        frames = {}
        for symbol in symbols:
            klines = await kline_warehouse.get_klines(
                symbol=symbol,
                period="day",
                count=252 * {"1y": 1, "3y": 3, "5y": 5}.get(period, 1),
            )
            if klines:
                closes = [k["close"] for k in klines]
                frames[symbol] = pd.Series(closes).pct_change().dropna()

        if len(frames) < 2:
            raise ValueError("数据不足")

        df = pd.DataFrame(frames).dropna()
        return df
    except Exception as e:
        logger.warning(f"从 kline_warehouse 获取数据失败: {e}, 使用模拟数据")
        return _generate_mock_returns(symbols, period)


def _generate_mock_returns(symbols: List[str], period: str) -> pd.DataFrame:
    """生成模拟日收益率 (开发环境兜底)。"""
    n_days = {"1y": 252, "3y": 756, "5y": 1260}.get(period, 252)
    np.random.seed(42)
    len(symbols)

    # 生成带相关性的随机收益率
    # 基础因子
    market = np.random.normal(0.0003, 0.01, n_days)
    data = {}
    for i, sym in enumerate(symbols):
        beta = 0.8 + np.random.uniform(-0.3, 0.5)
        alpha = np.random.uniform(-0.0001, 0.0002)
        idio = np.random.normal(0, 0.015, n_days)
        returns = alpha + beta * market + idio
        data[sym] = returns

    return pd.DataFrame(data)


# ── API 端点 ──────────────────────────────────────────────────────────────────


@router.post("/optimize")
async def optimize_portfolio(req: OptimizeReq):
    """
    TRADE-03: 组合优化。

    支持模型: markowitz / risk_parity / max_sharpe / equal_weight
    """
    if len(req.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")

    returns_df = await _fetch_returns(req.symbols, req.period)

    try:
        if req.model == "markowitz":
            result = portfolio_optimizer.mean_variance(
                returns_df,
                target_return=req.target_return,
                max_weight=req.max_weight,
                risk_free_rate=req.risk_free_rate,
            )
        elif req.model == "risk_parity":
            result = portfolio_optimizer.risk_parity(
                returns_df,
                max_weight=req.max_weight,
                risk_free_rate=req.risk_free_rate,
            )
        elif req.model == "max_sharpe":
            result = portfolio_optimizer.max_sharpe(
                returns_df,
                risk_free_rate=req.risk_free_rate,
                max_weight=req.max_weight,
            )
        elif req.model == "equal_weight":
            n = len(req.symbols)
            w = np.ones(n) / n
            mu = returns_df.mean().values * 252
            cov = returns_df.cov().values * 252
            result = portfolio_optimizer._build_result(w, mu, cov, list(returns_df.columns), req.risk_free_rate)
        else:
            raise HTTPException(status_code=400, detail=f"未知模型: {req.model}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"组合优化失败: {e}")
        raise HTTPException(status_code=500, detail=f"优化失败: {e}")

    return {
        "status": "success",
        "data": {
            "model": req.model,
            "symbols": req.symbols,
            "period": req.period,
            "result": {
                "weights": result.weights,
                "expected_return": result.expected_return,
                "expected_volatility": result.expected_volatility,
                "sharpe_ratio": result.sharpe_ratio,
                "risk_contributions": result.risk_contributions,
                "effective_n": result.effective_n,
            },
        },
    }


@router.post("/efficient-frontier")
async def get_efficient_frontier(req: FrontierReq):
    """TRADE-03: 有效前沿数据。"""
    if len(req.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")

    returns_df = await _fetch_returns(req.symbols, req.period)

    try:
        frontier = portfolio_optimizer.efficient_frontier(
            returns_df,
            n_points=req.n_points,
            max_weight=req.max_weight,
            risk_free_rate=req.risk_free_rate,
        )
    except Exception as e:
        logger.error(f"有效前沿计算失败: {e}")
        raise HTTPException(status_code=500, detail=f"计算失败: {e}")

    return {"status": "success", "data": frontier}


@router.post("/compare")
async def compare_models(req: CompareReq):
    """TRADE-03: 多模型对比 (等权 vs Markowitz vs 风险平价 vs MaxSharpe)。"""
    if len(req.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")

    returns_df = await _fetch_returns(req.symbols, req.period)

    try:
        comparison = portfolio_optimizer.compare_models(
            returns_df,
            max_weight=req.max_weight,
            risk_free_rate=req.risk_free_rate,
        )
    except Exception as e:
        logger.error(f"模型对比失败: {e}")
        raise HTTPException(status_code=500, detail=f"对比失败: {e}")

    return {"status": "success", "data": comparison}
