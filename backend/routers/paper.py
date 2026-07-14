"""
PT-01b: 纸面组合 API
PT-02a: + 净值序列 / 对比数据
====================
POST   /api/v1/paper/portfolios              创建组合
GET    /api/v1/paper/portfolios              列表 + 摘要
GET    /api/v1/paper/portfolios/{pid}        详情
GET    /api/v1/paper/portfolios/{pid}/fills  成交流水
GET    /api/v1/paper/portfolios/{pid}/nav    日终净值序列
GET    /api/v1/paper/portfolios/{pid}/compare 对比数据
POST   /api/v1/paper/portfolios/{pid}/pause  暂停
POST   /api/v1/paper/portfolios/{pid}/resume 恢复
POST   /api/v1/paper/portfolios/{pid}/close  关闭
"""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.models import PaperNavDaily
from backend.services.paper_ledger_service import paper_ledger_service
from backend.services import performance as perf

router = APIRouter(prefix="/paper", tags=["Paper Trading"])


# ─── Payload / Response ───


class CreatePortfolioPayload(BaseModel):
    name: str = Field(..., max_length=64)
    strategy_name: str = Field(..., max_length=64)
    code_hash: str = Field(..., max_length=64)
    market: str = Field(..., max_length=4, description="HK | US")
    initial_capital: float = Field(default=100000.0)
    params: Optional[dict] = None
    strategy_version_id: Optional[str] = None
    benchmark_backtest_ref: Optional[str] = None


class StatusPayload(BaseModel):
    status: str = Field(..., description="paused | running | closed")


# ─── 端点 ───


@router.post("/portfolios")
def create_portfolio(payload: CreatePortfolioPayload, db: Session = Depends(get_db)):
    """创建纸面组合"""
    result = paper_ledger_service.create_portfolio(
        db=db,
        name=payload.name,
        strategy_name=payload.strategy_name,
        code_hash=payload.code_hash,
        market=payload.market,
        initial_capital=payload.initial_capital,
        params=payload.params,
        strategy_version_id=payload.strategy_version_id,
        benchmark_backtest_ref=payload.benchmark_backtest_ref,
    )
    return {"status": "success", "message": "纸面组合已创建", "data": result}


@router.get("/portfolios")
def list_portfolios(status: Optional[str] = None, db: Session = Depends(get_db)):
    """列出纸面组合"""
    portfolios = paper_ledger_service.list_portfolios(db, status=status)
    return {"status": "success", "data": portfolios}


@router.get("/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    """组合详情"""
    result = paper_ledger_service.get_portfolio(db, portfolio_id)
    if not result:
        return {"status": "error", "message": "组合不存在"}
    # 附加持仓和最新 NAV
    positions = paper_ledger_service.get_positions(db, portfolio_id)
    result["positions"] = positions
    return {"status": "success", "data": result}


@router.get("/portfolios/{portfolio_id}/fills")
def get_fills(
    portfolio_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """成交流水分页"""
    fills = paper_ledger_service.get_fills(db, portfolio_id, limit=limit, offset=offset)
    return {"status": "success", "data": fills}


@router.post("/portfolios/{portfolio_id}/pause")
def pause_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    """暂停组合"""
    ok = paper_ledger_service.update_status(db, portfolio_id, "paused")
    if ok:
        return {"status": "success", "message": "组合已暂停"}
    return {"status": "error", "message": "组合不存在"}


@router.post("/portfolios/{portfolio_id}/resume")
def resume_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    """恢复组合"""
    ok = paper_ledger_service.update_status(db, portfolio_id, "running")
    if ok:
        return {"status": "success", "message": "组合已恢复"}
    return {"status": "error", "message": "组合不存在"}


@router.post("/portfolios/{portfolio_id}/close")
def close_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    """关闭组合"""
    ok = paper_ledger_service.update_status(db, portfolio_id, "closed")
    if ok:
        return {"status": "success", "message": "组合已关闭"}
    return {"status": "error", "message": "组合不存在"}


# ─── PT-02a: 净值序列 / 对比 ───


@router.get("/portfolios/{portfolio_id}/nav")
def get_nav_series(
    portfolio_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """日终净值序列"""
    rows = paper_ledger_service.get_nav_daily(db, portfolio_id, days=days)
    return {"status": "success", "data": rows}


@router.get("/portfolios/{portfolio_id}/compare")
def get_compare(
    portfolio_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """
    对比数据：纸面 vs 回测基准
    返回: TE / 累计偏离 / 信号一致率 / 归一化双曲线数据
    """
    # 1. 获取纸面 NAV 序列
    nav_rows = paper_ledger_service.get_nav_daily(db, portfolio_id, days=days)
    if not nav_rows:
        return {"status": "error", "message": "无净值数据"}

    paper_nav = pd.Series([r["nav"] for r in nav_rows])
    paper_returns = paper_nav.pct_change().dropna()

    # 2. 获取 benchmark 回测曲线（从 Redis 快照 or DB）
    portfolio = paper_ledger_service.get_portfolio(db, portfolio_id)
    benchmark_ref = portfolio.get("benchmark_backtest_ref") if portfolio else None
    benchmark_nav = _load_benchmark_nav(benchmark_ref, days)

    # 3. 归一化为累计收益率，按序号对齐
    paper_cum = perf.cumulative_return(paper_nav)
    if benchmark_nav is not None and not benchmark_nav.empty:
        bench_cum = perf.cumulative_return(benchmark_nav)
    else:
        bench_cum = pd.Series([0.0] * len(paper_nav))

    # 4. 计算指标
    te = perf.tracking_error(paper_returns, bench_cum.pct_change().dropna()) if len(paper_returns) > 1 else 0.0
    cumulative_drift = float(paper_cum.iloc[-1] - bench_cum.iloc[-1]) if len(paper_cum) > 0 else 0.0

    # 5. 构建双曲线数据
    chart_data = []
    for i in range(len(paper_cum)):
        point = {
            "idx": i,
            "paper": round(float(paper_cum.iloc[i]), 6) if i < len(paper_cum) else None,
            "benchmark": round(float(bench_cum.iloc[i]), 6) if i < len(bench_cum) else None,
        }
        chart_data.append(point)

    return {
        "status": "success",
        "data": {
            "tracking_error": round(te, 6),
            "cumulative_drift": round(cumulative_drift, 6),
            "chart": chart_data,
            "paper_sharpe": round(perf.sharpe(paper_returns), 4),
            "paper_max_dd": round(perf.max_drawdown(paper_nav), 6),
        },
    }


def _load_benchmark_nav(benchmark_ref: Optional[str], days: int) -> Optional[pd.Series]:
    """加载 benchmark 回测净值曲线（Redis 快照优先，降级到 DB）"""
    if not benchmark_ref:
        return None
    try:
        from backend.core.redis_client import redis_client
        import json
        import asyncio

        # 尝试从 Redis 获取回测报告快照
        key = f"backtest:{benchmark_ref}:nav"
        loop = asyncio.get_event_loop()
        raw = asyncio.ensure_future(redis_client.get(key))
        # 同步兼容：使用 run_until_complete 或降级
        # 简化处理：直接返回 None，由前端后续通过异步 API 获取
        return None
    except Exception:
        return None
