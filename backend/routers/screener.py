"""
Screener Router (HTTP 边界层)

本模块只负责 HTTP 映射与依赖注入 (DI)，所有编排逻辑下沉到
``backend.app.screener_app``。保持 Thin Router：禁止在此写入业务编排。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

# 以下为测试兼容重新导出（非 router 直接使用）
from backend.app.screener_app import (  # noqa: F401
    SUGGESTIONS,
    CEPRuleCreate,
    CrossSectionRequest,
    DictionaryBatchItem,
    DictionaryDeleteItem,
    DictionaryItem,
    PortfolioBacktestRequest,
    ScreenerHistoryItem,
    ScreenerHistoryRequest,
    ScreenerRequest,
    ScreenerSubscribeRequest,
    ScreenerSubscriptionTimeUpdateRequest,
    ScreenerTranslateRequest,
    SummarizePayload,
    _clean_json_dsl,
    _parse_human_number,
    add_dictionary_batch,
    add_dictionary_item,
    cep_matches_sse,
    create_cep_rule,
    cross_sectional_screen,
    delete_cep_rule,
    delete_dictionary_item,
    delete_subscription,
    get_dictionary,
    get_screener_history,
    get_screener_suggestions,
    get_subscriptions,
    list_cep_rules,
    portfolio_backtest,
    reload_indicators,
    run_screener,
    save_screener_history,
    subscribe_screener,
    summarize_screener_results,
    toggle_subscription,
    translate_dsl,
    update_subscription_time,
)
from backend.core import models
from backend.core.database import get_db
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/screener", tags=["Screener"])


async def get_subscription(
    sub_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """依赖注入：解析并返回当前用户拥有的订阅记录，不存在则 404。"""
    sub = db.query(models.ScreenerSubscription).filter_by(id=sub_id, user_id=current_user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub


# ---------------------------------------------------------------------------
# 路由定义 (仅做 HTTP 映射 + 参数透传)
# ---------------------------------------------------------------------------


@router.get("/suggestions")
async def api_get_suggestions(limit: int = Query(default=6, ge=1, le=50)):
    return await get_screener_suggestions(limit=limit)


@router.post("/translate")
async def api_translate(req: ScreenerTranslateRequest):
    return await translate_dsl(req)


@router.post("/run")
async def api_run_screener(req: ScreenerRequest):
    # 注意: /run 为公开选股查询端点 (ARCH-09 前即无鉴权)，app 层
    # run_screener(req) 不接收 current_user，禁止在此加 Depends(get_current_user)。
    return await run_screener(req)


@router.get("/history")
async def api_get_history(current_user: models.User = Depends(get_current_user)):
    return await get_screener_history(current_user)


@router.post("/history")
async def api_save_history(
    req: ScreenerHistoryRequest,
    current_user: models.User = Depends(get_current_user),
):
    return await save_screener_history(req, current_user)


@router.post("/reload-indicators")
async def api_reload_indicators():
    return await reload_indicators()


@router.get("/dictionary")
async def api_get_dictionary(current_user: models.User = Depends(get_current_user)):
    return await get_dictionary(current_user)


@router.post("/dictionary")
async def api_add_dictionary_item(
    item: DictionaryItem,
    current_user: models.User = Depends(get_current_user),
):
    return await add_dictionary_item(item, current_user)


@router.delete("/dictionary")
async def api_delete_dictionary_item(
    item: DictionaryDeleteItem,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return await delete_dictionary_item(item, db, current_user)


@router.post("/dictionary/batch")
async def api_add_dictionary_batch(
    req: DictionaryBatchItem,
    current_user: models.User = Depends(get_current_user),
):
    return await add_dictionary_batch(req, current_user)


@router.post("/subscribe")
async def api_subscribe(
    req: ScreenerSubscribeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return await subscribe_screener(req, db, current_user)


@router.get("/subscriptions")
async def api_get_subscriptions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return await get_subscriptions(db, current_user)


@router.put("/subscription/time")
async def api_update_subscription_time(
    req: ScreenerSubscriptionTimeUpdateRequest,
    db: Session = Depends(get_db),
    sub=Depends(get_subscription),
):
    return await update_subscription_time(req, db, sub)


@router.delete("/subscription/{sub_id}")
async def api_delete_subscription(db: Session = Depends(get_db), sub=Depends(get_subscription)):
    return await delete_subscription(db, sub)


@router.post("/subscription/{sub_id}/toggle")
async def api_toggle_subscription(db: Session = Depends(get_db), sub=Depends(get_subscription)):
    return await toggle_subscription(db, sub)


@router.post("/summarize")
async def api_summarize(payload: SummarizePayload):
    return await summarize_screener_results(payload)


@router.post("/cross-sectional")
async def api_cross_sectional(req: CrossSectionRequest):
    return await cross_sectional_screen(req)


@router.post("/portfolio-backtest")
async def api_portfolio_backtest(req: PortfolioBacktestRequest):
    return await portfolio_backtest(req)


@router.post("/cep/rule")
async def api_create_cep_rule(req: CEPRuleCreate):
    return await create_cep_rule(req)


@router.get("/cep/rules")
async def api_list_cep_rules():
    return await list_cep_rules()


@router.delete("/cep/rule/{rule_id}")
async def api_delete_cep_rule(rule_id: str):
    return await delete_cep_rule(rule_id)


@router.get("/cep/matches/sse")
async def api_cep_matches_sse(since: float = 0.0):
    return await cep_matches_sse(since)
