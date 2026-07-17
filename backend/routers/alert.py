"""
告警中心 API 路由 (ALERT-02 + ALERT-03c/03d)
============================================

告警规则 CRUD + 告警事件查询 + 引擎状态 + WebSocket 推送 + 投递查询。

端点:
  POST   /api/v1/alert/rules          — 创建规则
  GET    /api/v1/alert/rules          — 查询规则列表
  GET    /api/v1/alert/rules/{id}     — 查询单条规则
  PUT    /api/v1/alert/rules/{id}     — 更新规则
  DELETE /api/v1/alert/rules/{id}     — 删除规则
  POST   /api/v1/alert/rules/{id}/toggle — 启停规则
  GET    /api/v1/alert/events         — 查询告警事件历史（支持 since 补拉）
  POST   /api/v1/alert/events/{id}/ack — 确认告警
  GET    /api/v1/alert/events/{id}/deliveries — 查询事件投递记录 (ALERT-03d)
  GET    /api/v1/alert/engine/status  — 引擎状态（含 dispatcher health）
  WS     /api/v1/alert/ws             — 实时告警推送 (ALERT-03c)

设计文档: docs/01 §十 告警中心 + docs/18 多通道推送路由设计
任务编号: ALERT-02 / ALERT-03c / ALERT-03d
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    NotificationPriority,
)
from backend.core.logger import logger

router = APIRouter(prefix="/alert", tags=["Alert Center"])


# ─────────────────────────────────────────
#  请求/响应 Schema
# ─────────────────────────────────────────


class CreateRuleRequest(BaseModel):
    """创建告警规则请求"""

    name: str = Field(..., description="规则名称")
    ticker: str = Field(..., description="标的代码")
    rule_type: AlertRuleType = Field(..., description="规则类型")
    threshold: float = Field(..., description="阈值")
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING)
    channels: List[AlertChannel] = Field(default_factory=lambda: [AlertChannel.IN_APP])
    cooldown_seconds: int = Field(default=300, ge=60)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateRuleRequest(BaseModel):
    """更新告警规则请求"""

    name: Optional[str] = None
    threshold: Optional[float] = None
    severity: Optional[AlertSeverity] = None
    channels: Optional[List[AlertChannel]] = None
    cooldown_seconds: Optional[int] = Field(default=None, ge=60)
    metadata: Optional[Dict[str, Any]] = None


class RuleResponse(BaseModel):
    """规则响应"""

    rule_id: str
    name: str
    ticker: str
    rule_type: AlertRuleType
    threshold: float
    severity: AlertSeverity
    channels: List[AlertChannel]
    cooldown_seconds: int
    enabled: bool
    trigger_count: int
    last_triggered_at: Optional[float]
    created_at: float
    updated_at: float


class EventResponse(BaseModel):
    """事件响应"""

    event_id: str
    rule_id: str = ""
    ticker: str = ""
    rule_type: Optional[AlertRuleType] = None
    severity: AlertSeverity = AlertSeverity.INFO
    message: str = ""
    trigger_value: Optional[float] = None
    threshold: Optional[float] = None
    triggered_at: float
    acknowledged: bool = False
    source: str = "user_rule"
    priority: Optional[NotificationPriority] = None
    ui_hint: Dict[str, Any] = Field(default_factory=dict)


class EngineStatusResponse(BaseModel):
    """引擎状态响应（ALERT-03c 扩展 dispatcher health）"""

    running: bool
    active_rules: int
    eval_count: int
    trigger_count: int
    tracked_tickers: int
    dispatcher: Optional[Dict[str, Any]] = None


class DeliveryRecordResponse(BaseModel):
    """投递记录响应 (ALERT-03d)"""

    delivery_id: str
    event_id: str
    channel: str
    priority: str
    status: str
    attempt: int = 1
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    created_at: float


# ─────────────────────────────────────────
#  内存存储 (后续迁移 PostgreSQL)
# ─────────────────────────────────────────

_rules_store: Dict[str, AlertRule] = {}
_events_store: List[AlertEvent] = []
MAX_EVENTS = 500


# ─────────────────────────────────────────
#  规则 CRUD
# ─────────────────────────────────────────


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule(req: CreateRuleRequest):
    """创建告警规则"""
    rule_id = str(uuid.uuid4())
    now = time.time()

    rule = AlertRule(
        rule_id=rule_id,
        name=req.name,
        ticker=req.ticker,
        rule_type=req.rule_type,
        threshold=req.threshold,
        severity=req.severity,
        channels=req.channels,
        cooldown_seconds=req.cooldown_seconds,
        metadata=req.metadata,
        created_at=now,
        updated_at=now,
    )

    _rules_store[rule_id] = rule
    logger.info(f"[AlertAPI] 创建规则: {rule_id} ({req.name}) ticker={req.ticker} type={req.rule_type.value}")

    return _rule_to_response(rule)


@router.get("/rules", response_model=List[RuleResponse])
async def list_rules(
    ticker: Optional[str] = Query(default=None, description="按标的过滤"),
    enabled: Optional[bool] = Query(default=None, description="按启用状态过滤"),
):
    """查询告警规则列表"""
    rules = list(_rules_store.values())

    if ticker:
        rules = [r for r in rules if r.ticker == ticker]
    if enabled is not None:
        rules = [r for r in rules if r.enabled == enabled]

    rules.sort(key=lambda r: r.created_at, reverse=True)
    return [_rule_to_response(r) for r in rules]


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str):
    """查询单条规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _rule_to_response(rule)


@router.put("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(rule_id: str, req: UpdateRuleRequest):
    """更新告警规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")

    if req.name is not None:
        rule.name = req.name
    if req.threshold is not None:
        rule.threshold = req.threshold
    if req.severity is not None:
        rule.severity = req.severity
    if req.channels is not None:
        rule.channels = req.channels
    if req.cooldown_seconds is not None:
        rule.cooldown_seconds = req.cooldown_seconds
    if req.metadata is not None:
        rule.metadata = req.metadata

    rule.updated_at = time.time()
    return _rule_to_response(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str):
    """删除告警规则"""
    if rule_id not in _rules_store:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    del _rules_store[rule_id]
    logger.info(f"[AlertAPI] 删除规则: {rule_id}")


@router.post("/rules/{rule_id}/toggle", response_model=RuleResponse)
async def toggle_rule(rule_id: str):
    """启停告警规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")

    rule.enabled = not rule.enabled
    rule.updated_at = time.time()
    status = "启用" if rule.enabled else "停用"
    logger.info(f"[AlertAPI] {status}规则: {rule_id}")
    return _rule_to_response(rule)


# ─────────────────────────────────────────
#  告警事件
# ─────────────────────────────────────────


@router.get("/events", response_model=List[EventResponse])
async def list_events(
    ticker: Optional[str] = Query(default=None),
    severity: Optional[AlertSeverity] = Query(default=None),
    since: Optional[float] = Query(default=None, description="返回 triggered_at > since 的事件（WS 断连补拉）"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """查询告警事件历史（支持 since 参数用于 WS 断连补拉）"""
    events = list(_events_store)

    if ticker:
        events = [e for e in events if e.ticker == ticker]
    if severity:
        events = [e for e in events if e.severity == severity]
    if since:
        events = [e for e in events if e.triggered_at > since]

    events.sort(key=lambda e: e.triggered_at, reverse=True)
    return [_event_to_response(e) for e in events[:limit]]


@router.post("/events/{event_id}/ack", response_model=EventResponse)
async def ack_event(event_id: str):
    """确认告警事件"""
    for event in _events_store:
        if event.event_id == event_id:
            event.acknowledged = True
            return _event_to_response(event)
    raise HTTPException(status_code=404, detail=f"事件 {event_id} 不存在")


# ─────────────────────────────────────────
#  引擎状态
# ─────────────────────────────────────────


@router.get("/engine/status", response_model=EngineStatusResponse)
async def engine_status():
    """查询告警引擎状态（含 dispatcher health）"""
    dispatcher_health = None
    try:
        from backend.services.alert_dispatcher import get_alert_dispatcher

        dispatcher = get_alert_dispatcher()
        dispatcher_health = await dispatcher.health()
    except Exception:
        pass

    return EngineStatusResponse(
        running=True,
        active_rules=sum(1 for r in _rules_store.values() if r.enabled),
        eval_count=0,
        trigger_count=sum(r.trigger_count for r in _rules_store.values()),
        tracked_tickers=len(set(r.ticker for r in _rules_store.values() if r.enabled)),
        dispatcher=dispatcher_health,
    )


# ─────────────────────────────────────────
#  投递记录查询 (ALERT-03d)
# ─────────────────────────────────────────


@router.get("/events/{event_id}/deliveries", response_model=List[DeliveryRecordResponse])
async def get_event_deliveries(event_id: str):
    """查询事件的投递记录（运维可观测 + 前端投递详情）"""
    try:
        from backend.services.alert_dispatcher import get_alert_dispatcher

        dispatcher = get_alert_dispatcher()
        records = dispatcher.get_delivery_records(event_id)
        return [
            DeliveryRecordResponse(
                delivery_id=r.delivery_id,
                event_id=r.event_id,
                channel=r.channel,
                priority=r.priority,
                status=r.status,
                attempt=r.attempt,
                latency_ms=r.latency_ms,
                error=r.error,
                created_at=r.created_at,
            )
            for r in records
        ]
    except Exception:
        return []


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


# ─────────────────────────────────────────
#  辅助函数
# ─────────────────────────────────────────


def _rule_to_response(rule: AlertRule) -> RuleResponse:
    return RuleResponse(
        rule_id=rule.rule_id,
        name=rule.name,
        ticker=rule.ticker,
        rule_type=rule.rule_type,
        threshold=rule.threshold,
        severity=rule.severity,
        channels=rule.channels,
        cooldown_seconds=rule.cooldown_seconds,
        enabled=rule.enabled,
        trigger_count=rule.trigger_count,
        last_triggered_at=rule.last_triggered_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _event_to_response(event: AlertEvent) -> EventResponse:
    return EventResponse(
        event_id=event.event_id,
        rule_id=event.rule_id,
        ticker=event.ticker,
        rule_type=event.rule_type,
        severity=event.severity,
        message=event.message,
        trigger_value=event.trigger_value,
        threshold=event.threshold,
        triggered_at=event.triggered_at,
        acknowledged=event.acknowledged,
        source=event.source,
        priority=event.priority,
        ui_hint=event.ui_hint or {},
    )
