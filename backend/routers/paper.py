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

import json
import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.domain import performance as perf
from backend.routers.auth import get_current_user
from backend.services.paper_ledger_service import paper_ledger_service

router = APIRouter(prefix="/paper", tags=["Paper Trading"])
logger = logging.getLogger(__name__)


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
        import asyncio

        from backend.core.redis_client import redis_client

        # 尝试从 Redis 获取回测报告快照（fire-and-forget）
        key = f"backtest:{benchmark_ref}:nav"
        try:
            loop = asyncio.get_running_loop()
            # fire-and-forget: 触发异步回填 NAV，结果由前端异步 API 获取，此处不 await
            # redis_client.get 返回 Awaitable，create_task 严格期望 Coroutine，运行时等价
            _ = loop.create_task(redis_client.get(key))  # type: ignore[arg-type]
        except RuntimeError:
            # 当前无事件循环，降级跳过（由前端异步 API 回填）
            pass
        return None
    except Exception:
        return None


# ─── AI-07: 纸面组合·实盘教练 ───


class ReadinessResp(BaseModel):
    status: str  # success | warning
    ready_for_live: bool | None = None
    metrics: dict = {}
    coach_advice: str | None = None
    confidence: float | None = None
    message: str | None = None


class DriftWarningResp(BaseModel):
    status: str  # success | warning
    drift_pct: float | None = None
    tracking_error: float | None = None
    warning: str | None = None
    message: str | None = None


def _compute_paper_metrics(db: Session, portfolio_id: str) -> dict:
    """复用 paper_ledger_service + perf 计算实盘教练所需指标（规则层，无需 LLM）。"""
    portfolio = paper_ledger_service.get_portfolio(db, portfolio_id)
    positions = paper_ledger_service.get_positions(db, portfolio_id)
    nav_rows = paper_ledger_service.get_nav_daily(db, portfolio_id, days=30)

    metrics: dict = {
        "status": portfolio.get("status") if portfolio else None,
        "position_count": len(positions),
        "max_drawdown": None,
        "consecutive_losses": None,
        "cumulative_drift": None,
        "tracking_error": None,
    }
    if not nav_rows:
        return metrics

    nav = pd.Series([r["nav"] for r in nav_rows])
    returns = nav.pct_change().dropna()
    metrics["max_drawdown"] = round(float(perf.max_drawdown(nav)), 4)
    # 连续下跌天数（连续亏损）
    neg = (returns < 0).tolist()
    best = cur = 0
    for v in neg:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    metrics["consecutive_losses"] = best

    # 偏离基准（复用 compare 逻辑）
    benchmark_ref = portfolio.get("benchmark_backtest_ref") if portfolio else None
    if benchmark_ref:
        try:
            bench = _load_benchmark_nav(benchmark_ref, 30)
            if bench is not None and not bench.empty:
                bench_cum = perf.cumulative_return(bench)
                paper_cum = perf.cumulative_return(nav)
                if len(paper_cum) > 0 and len(bench_cum) > 0:
                    metrics["cumulative_drift"] = round(float(paper_cum.iloc[-1] - bench_cum.iloc[-1]), 4)
                    if len(returns) > 1:
                        metrics["tracking_error"] = round(
                            float(perf.tracking_error(returns, bench_cum.pct_change().dropna())), 4
                        )
        except Exception:
            pass
    return metrics


@router.get(
    "/portfolios/{portfolio_id}/readiness", response_model=ReadinessResp, dependencies=[Depends(get_current_user)]
)
async def ai_readiness(portfolio_id: str, db: Session = Depends(get_db)):
    """
    AI-07 实盘教练：综合体检（状态/回撤/连续亏损/偏离基准）→ 能否实盘建议。
    规则层给出结论，LLM 增强理由；LLM 缺失时仅返回规则层。
    """
    metrics = _compute_paper_metrics(db, portfolio_id)

    # 规则层：硬性熔断条件
    blockers: list[str] = []
    if metrics["status"] != "running":
        blockers.append(f"组合状态为 {metrics['status']}，未运行")
    if metrics["max_drawdown"] is not None and metrics["max_drawdown"] < -0.20:
        blockers.append(f"最大回撤 {metrics['max_drawdown'] * 100:.1f}% 超过 20% 阈值")
    if metrics["cumulative_drift"] is not None and abs(metrics["cumulative_drift"]) > 0.05:
        blockers.append(f"净值偏离基准 {metrics['cumulative_drift'] * 100:.1f}% 超过 5%")
    if metrics["position_count"] == 0:
        blockers.append("无持仓，样本不足")

    ready_for_live = len(blockers) == 0
    rule_message = "；".join(blockers) if blockers else "规则层体检通过"

    # LLM 层：增强建议
    coach_advice = None
    confidence = None
    message = None
    if not settings.llm_model:
        message = "LLM 模型未配置，仅返回规则层体检"
    else:
        from backend.bootstrap.lifecycle import global_llm_client

        if global_llm_client is None:
            message = "LLM 客户端未初始化，仅返回规则层体检"
        else:
            prompt = (
                "你是量化实盘教练。基于以下纸面组合体检指标，给出'能否转入实盘'的教练建议。\n"
                f"指标：{metrics}\n规则层结论：{rule_message}\n"
                '仅输出 JSON：{"coach_advice": string(中文建议，含具体改进动作), '
                '"confidence": number(0-1)}\n无可靠依据时 confidence 取低值，不要编造数字。'
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
                coach_advice = parsed.get("coach_advice")
                confidence = parsed.get("confidence")
            except Exception as e:
                logger.warning(f"AI-07 readiness LLM 失败: {e}")
                message = "LLM 教练建议失败，仅返回规则层体检"

    status = "warning" if not ready_for_live else "success"
    return ReadinessResp(
        status=status,
        ready_for_live=ready_for_live,
        metrics=metrics,
        coach_advice=coach_advice,
        confidence=confidence,
        message=rule_message + (f"；{message}" if message else ""),
    )


@router.get(
    "/portfolios/{portfolio_id}/drift-warning",
    response_model=DriftWarningResp,
    dependencies=[Depends(get_current_user)],
)
def ai_drift_warning(portfolio_id: str, db: Session = Depends(get_db)):
    """
    AI-07 漂移预警：对比 benchmark 净值偏离，超阈值给预警。
    规则层（复用 compare 逻辑），不依赖 LLM。
    """
    metrics = _compute_paper_metrics(db, portfolio_id)
    drift = metrics.get("cumulative_drift")
    te = metrics.get("tracking_error")

    if drift is None:
        return DriftWarningResp(
            status="warning", drift_pct=None, tracking_error=te, message="无基准或净值数据，无法计算偏离"
        )

    if abs(drift) > 0.05:
        warning = f"净值偏离基准 {drift * 100:.1f}%，超过 5% 阈值，建议复核策略逻辑或与基准的匹配度"
        return DriftWarningResp(status="warning", drift_pct=drift, tracking_error=te, warning=warning)

    return DriftWarningResp(status="success", drift_pct=drift, tracking_error=te, warning=None)
