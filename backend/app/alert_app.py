"""告警编排层 (Alert Orchestration)。

将 routers/alert.py 中的用例编排逻辑（规则/事件内存存储、CRUD、引擎状态、投递查询、
响应模型映射）收口到本模块，使 router 仅承担「请求校验 + HTTP 映射 + WebSocket 推送」。

`alert_dispatcher` 为下游服务，仍在 router 侧按需懒加载调用（见 routers/alert.py）。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    NotificationPriority,
)
from backend.core.exceptions import AppError
from backend.core.logger import logger

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


async def create_rule(req: CreateRuleRequest) -> RuleResponse:
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


async def list_rules(
    ticker: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> List[RuleResponse]:
    """查询告警规则列表"""
    rules = list(_rules_store.values())

    if ticker:
        rules = [r for r in rules if r.ticker == ticker]
    if enabled is not None:
        rules = [r for r in rules if r.enabled == enabled]

    rules.sort(key=lambda r: r.created_at, reverse=True)
    return [_rule_to_response(r) for r in rules]


async def get_rule(rule_id: str) -> RuleResponse:
    """查询单条规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise AppError(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _rule_to_response(rule)


async def update_rule(rule_id: str, req: UpdateRuleRequest) -> RuleResponse:
    """更新告警规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise AppError(status_code=404, detail=f"规则 {rule_id} 不存在")

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


async def delete_rule(rule_id: str) -> None:
    """删除告警规则"""
    if rule_id not in _rules_store:
        raise AppError(status_code=404, detail=f"规则 {rule_id} 不存在")
    del _rules_store[rule_id]
    logger.info(f"[AlertAPI] 删除规则: {rule_id}")


async def toggle_rule(rule_id: str) -> RuleResponse:
    """启停告警规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise AppError(status_code=404, detail=f"规则 {rule_id} 不存在")

    rule.enabled = not rule.enabled
    rule.updated_at = time.time()
    status = "启用" if rule.enabled else "停用"
    logger.info(f"[AlertAPI] {status}规则: {rule_id}")
    return _rule_to_response(rule)


# ─────────────────────────────────────────
#  告警事件
# ─────────────────────────────────────────


async def list_events(
    ticker: Optional[str] = None,
    severity: Optional[AlertSeverity] = None,
    since: Optional[float] = None,
    limit: int = 50,
) -> List[EventResponse]:
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


async def get_event(event_id: str) -> EventResponse:
    """查询单条事件"""
    for event in _events_store:
        if event.event_id == event_id:
            return _event_to_response(event)
    raise AppError(status_code=404, detail=f"事件 {event_id} 不存在")


async def ack_event(event_id: str) -> EventResponse:
    """确认告警事件"""
    for event in _events_store:
        if event.event_id == event_id:
            event.acknowledged = True
            return _event_to_response(event)
    raise AppError(status_code=404, detail=f"事件 {event_id} 不存在")


# ─────────────────────────────────────────
#  引擎状态
# ─────────────────────────────────────────


async def engine_status() -> EngineStatusResponse:
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


async def get_event_deliveries(event_id: str) -> List[DeliveryRecordResponse]:
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
