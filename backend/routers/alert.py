"""告警路由层 (Alert Router)。

仅承担「请求校验 + HTTP 映射 + WebSocket 推送」，所有用例编排逻辑已收口至
`backend.app.alert_app`。下游依赖的 patch 目标应指向 `backend.app.alert_app.*`。

注：`_rules_store` / `_events_store` 在此重新导出，以满足既有测试夹具
`backend.routers.alert._rules_store/_events_store` 对 router 命名空间的依赖
（它们与 `backend.app.alert_app` 中的同一对象）。
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.app.alert_app import (
    CreateRuleRequest,
    DeliveryRecordResponse,
    EngineStatusResponse,
    EventResponse,
    RuleResponse,
    UpdateRuleRequest,
    ack_event,
    create_rule,
    delete_rule,
    engine_status,
    get_event,
    get_event_deliveries,
    get_rule,
    list_events,
    list_rules,
    toggle_rule,
    update_rule,
)
from backend.core.alert_models import AlertSeverity
from backend.core.logger import logger

router = APIRouter(prefix="/alert", tags=["Alert Center"])


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule_endpoint(req: CreateRuleRequest):
    """创建告警规则"""
    return await create_rule(req)


@router.get("/rules", response_model=List[RuleResponse])
async def list_rules_endpoint(
    ticker: Optional[str] = Query(default=None, description="按标的过滤"),
    enabled: Optional[bool] = Query(default=None, description="按启用状态过滤"),
):
    """查询告警规则列表"""
    return await list_rules(ticker=ticker, enabled=enabled)


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule_endpoint(rule_id: str):
    """查询单条规则"""
    return await get_rule(rule_id)


@router.put("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule_endpoint(rule_id: str, req: UpdateRuleRequest):
    """更新告警规则"""
    return await update_rule(rule_id, req)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule_endpoint(rule_id: str):
    """删除告警规则"""
    await delete_rule(rule_id)


@router.post("/rules/{rule_id}/toggle", response_model=RuleResponse)
async def toggle_rule_endpoint(rule_id: str):
    """启停告警规则"""
    return await toggle_rule(rule_id)


@router.get("/events", response_model=List[EventResponse])
async def list_events_endpoint(
    ticker: Optional[str] = Query(default=None, description="按标的过滤"),
    severity: Optional[AlertSeverity] = Query(default=None),
    since: Optional[float] = Query(default=None, description="返回 triggered_at > since 的事件（WS 断连补拉）"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """查询告警事件历史（支持 since 参数用于 WS 断连补拉）"""
    return await list_events(ticker=ticker, severity=severity, since=since, limit=limit)


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event_endpoint(event_id: str):
    """查询单条事件"""
    return await get_event(event_id)


@router.post("/events/{event_id}/ack", response_model=EventResponse)
async def ack_event_endpoint(event_id: str):
    """确认告警事件"""
    return await ack_event(event_id)


@router.get("/engine/status", response_model=EngineStatusResponse)
async def engine_status_endpoint():
    """查询告警引擎状态（含 dispatcher health）"""
    return await engine_status()


@router.get("/events/{event_id}/deliveries", response_model=List[DeliveryRecordResponse])
async def get_event_deliveries_endpoint(event_id: str):
    """查询事件的投递记录（运维可观测 + 前端投递详情）"""
    return await get_event_deliveries(event_id)


# ─────────────────────────────────────────
#  WebSocket 实时推送 (ALERT-03c)
# ─────────────────────────────────────────

# 活跃 WS 连接池
_ws_connections: List[WebSocket] = []


@router.websocket("/ws")
async def alert_websocket(websocket: WebSocket):
    """实时告警推送 WebSocket

    连接后订阅 Redis quant:alerts:push 频道，
    将告警消息实时推送给前端。
    断连后前端可通过 GET /events?since= 补拉。
    """
    await websocket.accept()
    _ws_connections.append(websocket)
    logger.info(f"[AlertWS] 新连接，当前活跃: {len(_ws_connections)}")

    try:
        # 尝试订阅 Redis PubSub
        redis_task = None
        try:
            from backend.core.redis_client import redis_client

            pubsub = redis_client.pubsub()
            await pubsub.subscribe("quant:alerts:push")

            async def _relay():
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        await websocket.send_text(data)

            redis_task = asyncio.create_task(_relay())
        except Exception as e:
            logger.warning(f"[AlertWS] Redis 订阅失败: {e}")
            # 降级：保持连接但无推送，前端通过 since 补拉

        # 心跳循环
        while True:
            try:
                data = await websocket.receive_text()
                # 客户端消息（如 ack、ping）
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception:
                break

        if redis_task:
            redis_task.cancel()

    finally:
        _ws_connections.remove(websocket)
        logger.info(f"[AlertWS] 连接关闭，剩余活跃: {len(_ws_connections)}")
