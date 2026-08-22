"""
Risk API 路由
提供风控面板数据 + RISK-01~08 进阶风控能力端点
"""

import json

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.logger import logger
from backend.routers.auth import get_current_user
from backend.services.datalake.kline_warehouse import kline_warehouse
from backend.services.risk.risk_attribution import calc_attribution
from backend.services.risk.risk_cvar import decompose_cvar
from backend.services.risk.risk_engine import risk_engine
from backend.services.risk.risk_liquidity import liquidity_assessor
from backend.services.risk.risk_sector import sector_analyzer
from backend.services.risk.risk_stress import stress_tester

router = APIRouter(prefix="/risk", tags=["Risk"])


# ── 辅助: 获取指定市场的持仓 + K 线数据 ─────────────────────────────────────


async def _get_market_data(market: str):
    """获取指定市场的持仓和 K 线数据，供进阶端点复用"""
    result = await risk_engine.get_portfolio_risk()
    # empty(无账户空态) 与 error(系统错误) 均返回空数据，交由调用方兜底
    if result.get("status") in ("error", "empty"):
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
    # 💡 无账户空态(empty)以 200 + 空 accounts 返回，前端展示"暂无账户数据"；
    #    仅真正的系统错误(error)才抛 500。
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.get("/positions-breakdown")
async def get_positions_breakdown():
    """持仓明细 + 个股风控指标"""
    result = await risk_engine.get_portfolio_risk()
    # 空态(empty)返回空持仓列表(200)，仅系统错误抛 500
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
    # 空态(empty)返回空矩阵(200)，仅系统错误抛 500
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


# ── AI-05: 风险预警员（雷达维度变红 → LLM 预警 + 压测情景推荐）─────────────


class RiskDimension(BaseModel):
    axis: str
    current: float
    limit: float


class AlertNarrativeReq(BaseModel):
    dimensions: list[RiskDimension] = []  # 六维风险雷达 {axis,current,limit}
    portfolio_beta: float | None = None


class AlertNarrativeResp(BaseModel):
    status: str  # success | safe | warning
    breaches: list[str] = []  # 超限维度名
    narrative: str | None = None  # LLM 预警文本
    suggested_scenarios: list[str] = []  # 推荐压测情景（真实情景名）
    hedge_hint: str | None = None  # 对冲/降险建议
    message: str | None = None


@router.post("/alert-narrative", response_model=AlertNarrativeResp, dependencies=[Depends(get_current_user)])
async def ai_alert_narrative(req: AlertNarrativeReq):
    """
    AI-05 风险预警员：雷达维度变红（current>limit）→ LLM 生成自然语言预警 +
    推荐压测情景 + 对冲建议。复用 stress_tester.list_scenarios() 真实情景名。
    无超限维度时返回 safe（不打 LLM）；LLM 缺失/失败仅返回规则层。
    """
    breaches = [d.axis for d in req.dimensions if d.current > d.limit]
    scenarios: list[str] = []
    try:
        raw_scenarios = stress_tester.list_scenarios()
        scenarios = [str(s) for s in raw_scenarios]
    except Exception:
        scenarios = []

    if not breaches:
        return AlertNarrativeResp(
            status="safe",
            breaches=[],
            narrative="当前六维风险均在限额内，风险可控，无需预警。",
            suggested_scenarios=[],
            hedge_hint=None,
            message="无超限维度",
        )

    # 规则层：列出超限维度（无 LLM 也能给结论）
    rule_message = "超限维度：" + "、".join(breaches)

    if not settings.llm_model:
        return AlertNarrativeResp(
            status="warning",
            breaches=breaches,
            narrative=None,
            suggested_scenarios=[],
            hedge_hint=None,
            message=rule_message + "；LLM 模型未配置",
        )

    from backend.bootstrap.lifecycle import global_llm_client

    if global_llm_client is None:
        return AlertNarrativeResp(
            status="warning",
            breaches=breaches,
            narrative=None,
            suggested_scenarios=[],
            hedge_hint=None,
            message=rule_message + "；LLM 客户端未初始化",
        )

    dims_text = "\n".join(
        f"- {d.axis}: 当前 {d.current} / 限额 {d.limit}" for d in req.dimensions if d.current > d.limit
    )
    beta_text = f"\n组合 Beta={req.portfolio_beta}" if req.portfolio_beta is not None else ""
    scenario_text = f"\n可用压测情景：{', '.join(scenarios)}" if scenarios else ""
    prompt = (
        "你是量化风险预警员。以下风险维度已突破限额，请生成预警研判。\n"
        f"超限维度：\n{dims_text}{beta_text}{scenario_text}\n"
        '仅输出 JSON：{"narrative": string(中文预警，说明风险点与紧迫度), '
        '"suggested_scenarios": list[string](从可用情景中推荐 2-3 个), '
        '"hedge_hint": string(中文降险/对冲建议), "confidence": number(0-1)}\n'
        "无可靠依据时 confidence 取低值，不要编造具体数字。"
    )
    try:
        resp = await global_llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("LLM 返回空内容")
        parsed = json.loads(content)
        suggested = parsed.get("suggested_scenarios") or []
        # 仅保留真实存在的情景名，过滤编造
        suggested_valid = [s for s in suggested if s in scenarios] if scenarios else []
        return AlertNarrativeResp(
            status="warning",
            breaches=breaches,
            narrative=parsed.get("narrative"),
            suggested_scenarios=suggested_valid,
            hedge_hint=parsed.get("hedge_hint"),
            message=None,
        )
    except Exception as e:
        logger.warning(f"AI-05 alert-narrative LLM 失败: {e}")
        return AlertNarrativeResp(
            status="warning",
            breaches=breaches,
            narrative=None,
            suggested_scenarios=[],
            hedge_hint=None,
            message=rule_message + "；LLM 预警失败",
        )
