"""
Risk API 路由
提供风控面板数据和持仓明细
"""

from fastapi import APIRouter, HTTPException, Query

from backend.services.risk_engine import risk_engine

router = APIRouter(prefix="/risk", tags=["Risk"])


@router.get("/dashboard")
async def get_risk_dashboard(
    days: int = Query(default=1, ge=1, le=90, description="历史天数 (1=最近24h, 7=一周, 30=一月)"),
):
    """
    风控面板全量数据
    包含: KPI / 敞口 / 风险雷达 / 因子监控 / NAV 快照 / 持仓明细
    - days=1: 从 Redis 读取最近 24h 净值快照
    - days>1: 从数据库读取历史净值快照
    """
    result = await risk_engine.get_portfolio_risk(days=days)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.get("/positions-breakdown")
async def get_positions_breakdown():
    """
    持仓明细 + 个股风控指标
    返回每只持仓的详细信息和独立风控指标
    """
    result = await risk_engine.get_portfolio_risk()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    # 从 accounts 中提取所有持仓
    all_positions = []
    for market, acc_data in result.get("accounts", {}).items():
        positions = acc_data.get("positions", [])
        all_positions.extend(positions)

    return {
        "status": "success",
        "positions": all_positions,
        "ts": result.get("ts"),
    }
