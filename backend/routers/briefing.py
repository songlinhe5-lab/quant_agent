"""
BRD-01: 早报刊物 API 路由

端点:
- POST /briefing/generate           手动触发生成盘前早报
- GET  /briefing/latest?market=全球  获取最新一份早报 (供 Dashboard 自动加载)
- GET  /briefing/share/{briefing_id} 按分享短码获取早报 (分享 URL 落地)
"""

from fastapi import APIRouter, HTTPException, Query

from backend.services.morning_briefing.generator import generate_morning_briefing
from backend.services.morning_briefing.storage import get_briefing, get_latest_briefing

router = APIRouter(prefix="/briefing", tags=["早报刊物"])


@router.post("/generate")
async def trigger_generate(
    market: str = Query("全球", description="市场范围: A股/港股/美股/全球"),
    date: str = Query(None, description="日期 YYYY-MM-DD，默认今天"),
):
    """手动触发盘前早报生成"""
    try:
        result = await generate_morning_briefing(market=market, target_date=date)
        return {"status": "success", "data": result.model_dump(mode="json")}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"早报生成失败: {e}")


@router.get("/latest")
async def latest_briefing(market: str = Query("全球", description="市场范围")):
    """获取指定市场最新一份早报"""
    review = await get_latest_briefing(market)
    if not review:
        return {"status": "empty", "message": f"{market} 暂无早报数据"}
    return {"status": "success", "data": review.model_dump(mode="json")}


@router.get("/share/{briefing_id}")
async def share_briefing(briefing_id: str):
    """按分享短码获取早报 (分享 URL 落地页数据源)"""
    result = await get_briefing(briefing_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"早报 {briefing_id} 不存在或已过期")
    return {"status": "success", "data": result.model_dump(mode="json")}
