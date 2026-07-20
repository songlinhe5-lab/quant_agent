"""
MRKT-04: 市场复盘 API 路由

端点:
- GET /market-review/latest?market=A股     获取最新复盘
- GET /market-review/query?market=A股&date=2026-07-08  精确查询
- GET /market-review/recent?market=A股&days=3  最近N天
- GET /market-review/dates?market=A股      可用日期列表
- POST /market-review/generate             手动触发生成
"""

from fastapi import APIRouter, HTTPException, Query

from backend.services.market_review.generator import generate_market_review
from backend.services.market_review.models import MarketType
from backend.services.market_review.storage import (
    get_latest_review,
    get_market_review,
    get_recent_reviews,
    list_available_dates,
)

router = APIRouter(prefix="/market-review", tags=["市场复盘"])


def _parse_market(market: str) -> MarketType:
    """解析市场参数"""
    for m in MarketType:
        if m.value == market or m.name == market.upper():
            return m
    raise HTTPException(status_code=400, detail=f"无效市场参数: {market}，可选: A股/港股/美股")


@router.get("/latest")
async def get_latest(market: str = Query("A股", description="市场: A股/港股/美股")):
    """获取指定市场最新一份复盘报告"""
    mt = _parse_market(market)
    review = await get_latest_review(mt)
    if not review:
        return {"status": "empty", "message": f"{mt.value}暂无复盘数据"}
    return {"status": "success", "data": review.model_dump(mode="json")}


@router.get("/query")
async def query_review(
    market: str = Query(..., description="市场: A股/港股/美股"),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
):
    """精确查询指定日期+市场的复盘"""
    mt = _parse_market(market)
    review = await get_market_review(date, mt)
    if not review:
        return {"status": "empty", "message": f"{mt.value} {date} 无复盘数据"}
    return {"status": "success", "data": review.model_dump(mode="json")}


@router.get("/recent")
async def recent_reviews(
    market: str = Query("A股", description="市场: A股/港股/美股"),
    days: int = Query(3, ge=1, le=30, description="最近N天"),
):
    """获取最近N天复盘（降序）"""
    mt = _parse_market(market)
    reviews = await get_recent_reviews(mt, days=days)
    return {
        "status": "success",
        "count": len(reviews),
        "data": [r.model_dump(mode="json") for r in reviews],
    }


@router.get("/dates")
async def available_dates(
    market: str = Query("A股", description="市场: A股/港股/美股"),
    limit: int = Query(30, ge=1, le=90),
):
    """列出可用复盘日期"""
    mt = _parse_market(market)
    dates = await list_available_dates(mt, limit=limit)
    return {"status": "success", "market": mt.value, "dates": dates}


@router.post("/generate")
async def trigger_generate(
    market: str = Query(..., description="市场: A股/港股/美股"),
    date: str = Query(None, description="日期 YYYY-MM-DD，默认今天"),
):
    """手动触发复盘生成（调试/补录用）"""
    mt = _parse_market(market)
    try:
        review = await generate_market_review(market=mt, date=date)
        return {"status": "success", "data": review.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复盘生成失败: {e}")
