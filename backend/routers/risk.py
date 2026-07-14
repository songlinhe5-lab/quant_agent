"""
Risk API 路由
提供风控面板数据 + RISK-01~08 进阶风控能力端点
"""

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core.logger import logger
from backend.services.kline_warehouse import kline_warehouse
from backend.services.risk_attribution import calc_attribution
from backend.services.risk_cvar import decompose_cvar
from backend.services.risk_engine import risk_engine
from backend.services.risk_liquidity import liquidity_assessor
from backend.services.risk_sector import sector_analyzer
from backend.services.risk_stress import stress_tester

router = APIRouter(prefix="/risk", tags=["Risk"])


# ── 辅助: 获取指定市场的持仓 + K 线数据 ─────────────────────────────────────


async def _get_market_data(market: str):
    """获取指定市场的持仓和 K 线数据，供进阶端点复用"""
    result = await risk_engine.get_portfolio_risk()
    if result.get("status") == "error":
        return None, None, None

    accounts = result.get("accounts", {})
    acc = accounts.get(market)
    if not acc:
        return None, None, None

    positions = acc.get("positions", [])
    total_nav = acc.get("kpi", {}).get("nav", 0)

    # 获取 K 线数据 (复用 risk_engine 的逻辑)
    kline_data = {}
    for pos in positions:
        ticker = pos.get("code", "")
        if not ticker:
            continue
        try:
            from backend.app.market_data import market_data

            hist = await market_data.get_history(ticker, ktype="K_DAY", num=60)
            if hist.get("status") == "success" and hist.get("data"):
                closes = [float(k["close"]) for k in hist["data"] if k.get("close")]
                if len(closes) >= 10:
                    kline_data[ticker] = closes
        except Exception as e:
            logger.warning(f"[RiskAPI] 获取 {ticker} K线失败: {e}")

    return positions, kline_data, total_nav


# ── 原有端点 ───────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def get_risk_dashboard(
    days: int = Query(default=1, ge=1, le=90, description="历史天数 (1=最近24h, 7=一周, 30=一月)"),
):
    """
    风控面板全量数据
    包含: KPI / 敞口 / 风险雷达 / 因子监控 / NAV 快照 / 持仓明细 / 相关性矩阵
    """
    result = await risk_engine.get_portfolio_risk(days=days)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.get("/positions-breakdown")
async def get_positions_breakdown():
    """持仓明细 + 个股风控指标"""
    result = await risk_engine.get_portfolio_risk()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    all_positions = []
    for market, acc_data in result.get("accounts", {}).items():
        positions = acc_data.get("positions", [])
        all_positions.extend(positions)

    return {"status": "success", "positions": all_positions, "ts": result.get("ts")}


# ── RISK-01: 板块暴露 ───────────────────────────────────────────────────────


@router.get("/sector-exposure")
async def get_sector_exposure(
    market: str = Query(default="HK", description="市场 (HK/US)"),
):
    """RISK-01: 板块暴露分析 (GICS 聚合)"""
    positions, _, _ = await _get_market_data(market)
    if positions is None:
        return {"sectors": [], "ts": 0}
    return await sector_analyzer.get_sector_exposure(positions, market)


# ── RISK-03: 相关性矩阵 ─────────────────────────────────────────────────────


@router.get("/correlation")
async def get_correlation(
    market: str = Query(default="HK", description="市场 (HK/US)"),
):
    """RISK-03: 持仓间 60 日收益率相关系数矩阵"""
    # 优先从 dashboard 缓存读取
    result = await risk_engine.get_portfolio_risk()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    acc = result.get("accounts", {}).get(market)
    if not acc:
        return {"labels": [], "matrix": [], "warnings": []}

    return acc.get("correlation", {"labels": [], "matrix": [], "warnings": []})


# ── RISK-05: CVaR 分解 ──────────────────────────────────────────────────────


@router.get("/cvar")
async def get_cvar(
    market: str = Query(default="HK", description="市场 (HK/US)"),
    alpha: float = Query(default=0.05, gt=0, lt=1, description="显著性水平"),
):
    """RISK-05: CVaR (Expected Shortfall) + 按持仓分解贡献度"""
    positions, kline_data, _ = await _get_market_data(market)
    if positions is None:
        return {"portfolio_cvar": 0.0, "var_threshold": 0.0, "decompositions": [], "ts": 0}
    return decompose_cvar(positions, kline_data, alpha)


# ── RISK-06: 流动性风险 ─────────────────────────────────────────────────────


@router.get("/liquidity")
async def get_liquidity(
    market: str = Query(default="HK", description="市场 (HK/US)"),
):
    """RISK-06: 流动性风险评估 (覆盖率 + 评分 + 大额预警)"""
    positions, kline_data, total_nav = await _get_market_data(market)
    if positions is None:
        return {"assessments": [], "portfolio_score": 0.0, "warnings": [], "ts": 0}
    return liquidity_assessor.assess(positions, kline_data, total_nav)


# ── RISK-02: Beta/Alpha 归因 ────────────────────────────────────────────────


@router.get("/attribution")
async def get_attribution(
    market: str = Query(default="HK", description="市场 (HK/US)"),
):
    """RISK-02: Jensen's Alpha 归因 (Market 因子)"""
    positions, kline_data, _ = await _get_market_data(market)
    if positions is None or not kline_data:
        return {
            "alpha": 0.0,
            "beta": 0.0,
            "r_squared": 0.0,
            "beta_contrib": 0.0,
            "total_return": 0.0,
            "attribution": {"alpha_pct": 0, "beta_pct": 0, "residual_pct": 0},
            "ts": 0,
        }

    # 计算组合收益率

    returns_dict = {}
    for ticker, closes in kline_data.items():
        returns_dict[ticker] = np.diff(np.log(closes))

    min_len = min(len(r) for r in returns_dict.values())
    aligned = {t: r[-min_len:] for t, r in returns_dict.items()}

    total_mv = sum(float(p.get("market_val", 0)) for p in positions if p.get("code") in aligned)
    if total_mv == 0:
        return {"alpha": 0.0, "beta": 0.0, "r_squared": 0.0, "ts": 0}

    portfolio_returns = np.zeros(min_len)
    for ticker, ret in aligned.items():
        w = next((float(p.get("market_val", 0)) / total_mv for p in positions if p.get("code") == ticker), 0)
        portfolio_returns += ret * w

    # 获取基准收益率
    benchmark = "^HSI" if market == "HK" else "^GSPC"
    try:
        bench_df = await kline_warehouse.get_history(benchmark, "K_DAY", num=60)
        if bench_df is not None and len(bench_df) >= 10:
            bench_returns = np.diff(np.log(bench_df["close"].values.astype(float)))
            return calc_attribution(portfolio_returns, bench_returns)
    except Exception as e:
        logger.warning(f"[RiskAPI] 基准 {benchmark} 获取失败: {e}")

    return {"alpha": 0.0, "beta": 0.0, "r_squared": 0.0, "ts": 0}


# ── RISK-04: 压力测试 ───────────────────────────────────────────────────────


class StressTestRequest(BaseModel):
    scenario: str
    market: str = "HK"


@router.post("/stress-test")
async def post_stress_test(req: StressTestRequest):
    """RISK-04: 压力测试 (历史情景 / 假设情景)"""
    positions, kline_data, _ = await _get_market_data(req.market)
    if positions is None:
        return stress_tester._empty_result(req.scenario)
    return stress_tester.run_stress(positions, kline_data, req.scenario, req.market)


@router.get("/stress-test/scenarios")
async def get_stress_scenarios():
    """列出所有可用压力测试情景"""
    return stress_tester.list_scenarios()
