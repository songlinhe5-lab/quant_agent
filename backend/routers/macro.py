"""
Macro Router (HTTP 边界层)

本模块只负责 HTTP 映射、依赖注入 (DI) 与 WebSocket 连接管理，
所有编排逻辑下沉到 ``backend.app.macro_app``。保持 Thin Router：禁止在此写入
业务编排。

WebSocket 处理器属于传输层关注点，保留在 router；其引用的 ``redis_client`` 与
内部 fetch 函数通过 ``macro_app`` 模块动态访问，确保单测 patch 目标
(``backend.app.macro_app.*``) 能正确生效。
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.app import macro_app
from backend.app.macro_app import (
    get_capital_flow,
    get_capital_flow_dashboard,
    get_data_center_dashboard,
    get_earnings_calendar,
    get_macro_assets,
    get_macro_calendar,
    get_macro_news,
    get_macro_series,
    get_margin_trading_data,
    get_sector_fund_flow,
    get_sentiment_history,
)
from backend.core.database import get_db

router = APIRouter(prefix="/macro", tags=["Macro"])


@router.get("/calendar")
async def get_macro_calendar_route(
    days_ahead: int = Query(7, ge=0, le=30, description="获取未来 N 天内的高影响宏观经济事件"),  # noqa: E501
    days_back: int = Query(0, ge=0, le=30, description="获取过去 N 天内已公布的宏观经济事件"),  # noqa: E501
):
    """获取全球核心经济体的宏观日历数据 (支持过去和未来)"""
    return await get_macro_calendar(days_ahead, days_back)


@router.get("/series")
async def get_macro_series_route(
    series_id: str = Query(..., description="FRED 经济序列 ID"),
    limit: int = Query(100, le=1000, description="返回的数据点数量"),
):
    """获取 FRED 宏观经济时间序列数据"""
    return await get_macro_series(series_id, limit)


@router.get("/sentiment-history")
def get_sentiment_history_route(
    limit: int = Query(200, le=2000, description="获取历史数据点数量"),
    db: Session = Depends(get_db),
):
    """获取情绪风向标历史趋势数据 (P/C Ratio, VIX, Credit Spread)"""
    return get_sentiment_history(limit, db)


@router.get("/sector-fund-flow")
async def get_sector_fund_flow_route():
    """获取板块资金流向数据"""
    return await get_sector_fund_flow()


@router.get("/capital-flow")
async def get_capital_flow_route():
    """获取跨市场资金流向数据"""
    return await get_capital_flow()


@router.get("/capital-flow-dashboard")
async def get_capital_flow_dashboard_route(
    force_refresh: bool = Query(False, description="是否绕过缓存强制刷新"),
):
    """FUNDFLOW-01: 北向/南向资金 + 三市场板块资金流聚合看板"""
    return await get_capital_flow_dashboard(force_refresh)


@router.get("/news")
async def get_macro_news_route(
    category: str = Query("general", description="新闻分类: general, forex, crypto, merger"),  # noqa: E501
    limit: int = Query(50, le=200, description="返回条数限制"),
):
    """获取全球市场前沿新闻"""
    return await get_macro_news(category, limit)


@router.get("/dashboard")
async def get_data_center_dashboard_route(
    force_refresh: bool = Query(False, description="强制绕过缓存拉取最新数据"),
    days_back: int = Query(3, ge=0, le=30, description="获取过去 N 天内已公布的宏观经济事件"),  # noqa: E501
):
    """聚合大盘看板所需的所有核心数据"""
    return await get_data_center_dashboard(force_refresh, days_back)


@router.get("/earnings")
async def get_earnings_calendar_route(
    days_ahead: int = Query(7, ge=1, le=30, description="向后展望天数"),
    days_back: int = Query(0, ge=0, le=30, description="向前回溯天数（含已发布）"),
    force_refresh: bool = Query(False, description="强制绕过缓存"),
):
    """财报日历（供 Calendars Earnings Tab 复用，复用既有聚合逻辑）"""
    return await get_earnings_calendar(days_ahead, days_back, force_refresh)


@router.get("/assets")
async def get_macro_assets_route(
    force_refresh: bool = Query(False, description="强制绕过缓存拉取最新数据"),
):
    """获取大类资产与宏观风险雷达数据"""
    return await get_macro_assets(force_refresh)


@router.get("/margin-trading")
async def get_margin_trading_data_route():
    """获取三个市场的融资融券余额数据"""
    return await get_margin_trading_data()


# BE-15: WebSocket 握手鉴权密钥（与全局 SECRET_KEY 对齐）
_WS_SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
_WS_ALGORITHM = "HS256"


@router.websocket("/news/ws")
async def websocket_live_news(websocket: WebSocket):
    """Websocket 接口：实时推送最新的宏观新闻流 (BE-15 增强版)"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    try:
        from jose import jwt as _jwt

        payload = _jwt.decode(token, _WS_SECRET_KEY, algorithms=[_WS_ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close(code=4003, reason="Invalid token payload")
            return
    except Exception:
        await websocket.close(code=4002, reason="Token expired or invalid")
        return
    await websocket.accept()
    pubsub = macro_app.redis_client.pubsub()

    async def listen_redis():
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                data["channel"] = message["channel"]
                await websocket.send_json(data)

    async def listen_client():
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    try:
        await pubsub.subscribe("macro_news")
        result = await macro_app._fetch_macro_news_from_stream(limit=20)
        await websocket.send_json(
            {
                "type": "news_snapshot",
                "message": f"当前共 {len(result)} 条最新新闻",
                "data": result,
            }
        )
        listen_r_task = asyncio.create_task(listen_redis())
        listen_c_task = asyncio.create_task(listen_client())
        done, pending = await asyncio.wait([listen_r_task, listen_c_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        print("⚠️ [Websocket] 前端已断开宏观新闻连接。")
    except Exception as e:
        print(f"❌ [Websocket] 宏观新闻推送异常: {str(e)}")
    finally:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        await pubsub.close()


@router.websocket("/calendar/ws")
async def websocket_macro_calendar(websocket: WebSocket):
    """Websocket 接口：推送当天的宏观事件报警 (BE-15 增强版)"""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    try:
        from jose import jwt as _jwt

        payload = _jwt.decode(token, _WS_SECRET_KEY, algorithms=[_WS_ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close(code=4003, reason="Invalid token payload")
            return
    except Exception:
        await websocket.close(code=4002, reason="Token expired or invalid")
        return
    await websocket.accept()
    pubsub = macro_app.redis_client.pubsub()

    async def listen_redis():
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                data["channel"] = message["channel"]
                await websocket.send_json(data)

    async def listen_client():
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    try:
        await pubsub.subscribe("macro_alerts")
        result = await macro_app._fetch_macro_calendar_data(days_ahead=1)
        today_events = []
        if result.get("status") == "success" and "data" in result:
            current_date = datetime.now(timezone.utc).date()
            for event in result["data"]:
                if event.get("date"):
                    try:
                        d = datetime.strptime(event.get("date").split("T")[0], "%Y-%m-%d").date()
                        if d == current_date:
                            today_events.append(event)  # noqa: E701
                    except Exception:
                        pass  # noqa: E701
        await websocket.send_json(
            {
                "type": "macro_alert",
                "message": f"今日共 {len(today_events)} 个高影响事件",
                "events": today_events,
            }
        )

        listen_r_task = asyncio.create_task(listen_redis())
        listen_c_task = asyncio.create_task(listen_client())

        done, pending = await asyncio.wait([listen_r_task, listen_c_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        # 💡 等待任务真正取消并归还 Redis 控制权，防止触发并发读写 RuntimeError 导致 close 被跳过  # noqa: E501
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        print("⚠️ [Websocket] 前端已断开宏观日历报警连接。")
    except Exception as e:
        print(f"❌ [Websocket] 宏观报警推送异常: {str(e)}")
    finally:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        await pubsub.close()
