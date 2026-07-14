import asyncio
import json
import logging
import os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import get_db
from backend.core.redis_client import redis_client
from backend.services.algo_analytics import algo_analytics
from backend.services.algo_engine import algo_engine
from backend.services.audit_service import log_audit
from backend.services.bot_runtime import bot_runtime
from backend.services.oms_service import oms_service

router = APIRouter(prefix="/oms", tags=["OMS & Live Bots"])
logger = logging.getLogger("OMS")


class CancelOrderReq(BaseModel):
    idempotency_key: str


class KillSwitchReq(BaseModel):
    timestamp: int


class AlgoOrderReq(BaseModel):
    algo_type: str
    symbol: str
    side: str
    target_qty: int
    duration_minutes: int


class ModifyOrderReq(BaseModel):
    price: float


class ModeSwitchReq(BaseModel):
    mode: str  # "SANDBOX" | "PAPER" | "LIVE"


@router.get("/state")
async def get_oms_initial_state(db: Session = Depends(get_db)):
    """
    获取 OMS 模块初始状态。
    OMS-01~04: 活动挂单与历史成交从 DB/Redis 读取真实数据。
    OMS-05~07: Bot 算力节点从 BotRuntimeManager 读取真实 CPU/MEM/日志。
    """
    # 活动挂单: 从 Redis 缓存 / PostgreSQL 读取真实订单
    active_orders = await oms_service.get_active_orders(db)
    # 历史成交: 从 trade_logs 表读取真实记录
    historical_trades = await oms_service.get_historical_trades(db, limit=50)
    # Bot 算力节点: 从 BotRuntimeManager 获取真实运行状态 (OMS-05~07)
    bots = await bot_runtime.get_all_bots()

    # OMS-08~09: 算法拆单从 algo_engine 读取真实执行状态
    algo_executions = await algo_engine.get_all_algo_orders()
    # OMS-11: 当前交易模式 (从 Redis 热读取)
    trading_mode = await _get_trading_mode()

    return {
        "status": "success",
        "data": {
            "bots": bots,
            "active_orders": active_orders,
            "historical_trades": historical_trades,
            "algo_executions": algo_executions,
            "trading_mode": trading_mode,
        },
    }


async def execute_emergency_liquidation(db: Session):
    """兼容旧 import：转发至 oms_app（BE-ARCH-02）。"""
    from backend.app.oms_app import run_emergency_liquidation

    await run_emergency_liquidation(db)


@router.post("/kill_switch")
async def trigger_kill_switch(
    request: Request,
    background_tasks: BackgroundTasks,
    req: KillSwitchReq,
    db: Session = Depends(get_db),
):
    """
    【全局熔断 Kill Switch】
    瞬间阻断所有实盘 Bot 的进程信号并下达市价全平指令给券商网关
    """
    try:
        from backend.app.oms_app import engage_kill_switch_flags, run_emergency_liquidation

        await engage_kill_switch_flags()
        background_tasks.add_task(run_emergency_liquidation, db)
        log_audit(db, action="kill_switch", detail={"timestamp": req.timestamp}, request=request)

        return {
            "status": "success",
            "message": "Kill switch engaged. All positions are being closed.",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to broadcast kill switch signal: {str(e)}")  # noqa: E501


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    request: Request,
    order_id: str,
    req: CancelOrderReq,
    db: Session = Depends(get_db),
):
    """
    带【防并发幂等性锁】的撤单接口 (OMS-03: 同步更新 DB 状态, OMS-12: 审计日志)
    """
    lock_key = f"oms:cancel_lock:{req.idempotency_key}"

    # 利用 Redis 的 NX (Not Exists) 保证同一个幂等性 Key 只能处理一次
    is_set = await redis_client.set(lock_key, "1", nx=True, ex=60)
    if not is_set:
        return {"status": "success", "message": "Cancel request already in progress"}

    try:
        await redis_client.publish("oms:order_cancel", json.dumps({"order_id": order_id}))  # noqa: E501
        # OMS-03: 同步更新 DB 订单状态为 CANCELLED
        await oms_service.update_order_status(db, order_id, "CANCELLED")
        # OMS-12: 审计日志
        log_audit(db, action="order_cancel", detail={"order_id": order_id}, request=request)
        return {"status": "success", "message": "Cancel requested"}
    except Exception:
        await redis_client.delete(lock_key)
        raise HTTPException(status_code=500, detail="Cancellation dispatch failed")


@router.post("/orders/{order_id}/modify")
async def modify_order(
    request: Request,
    order_id: str,
    req: ModifyOrderReq,
    db: Session = Depends(get_db),
):
    """
    修改订单价格 (改单) 接口 (OMS-03: 同步更新 DB, OMS-12: 审计日志)
    """
    try:
        # 1. 派发改单指令给底层交易网关
        payload = {"order_id": order_id, "new_price": req.price}
        await redis_client.publish("oms:order_modify", json.dumps(payload))

        # 2. OMS-03: 同步更新 DB 中的订单价格
        order = db.query(models.Order).filter(models.Order.order_id == order_id).first()
        if order:
            order.price = req.price
            db.commit()
            await oms_service._sync_order_to_redis(order)
            await oms_service._publish_orders_update(db)

        # OMS-12: 审计日志
        log_audit(db, action="order_modify", detail={"order_id": order_id, "new_price": req.price}, request=request)

        return {"status": "success", "message": "改单指令已下发"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Modification dispatch failed: {str(e)}")  # noqa: E501


@router.get("/positions")
async def get_real_positions(market: str = "HK"):
    """OMS-04: 获取 Redis 缓存中的真实持仓列表"""
    positions = await oms_service.get_cached_positions(market)
    return {"status": "success", "data": positions, "market": market}


# ── Bot 算力节点控制接口 (OMS-05) ─────────────────────────────────────────


@router.post("/bots/{bot_id}/pause")
async def pause_bot(bot_id: str):
    """OMS-05: 暂停 Bot 算力节点"""
    success = await bot_runtime.pause_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"无法暂停 Bot {bot_id}，可能未在运行中")
    return {"status": "success", "message": f"Bot {bot_id} 已暂停"}


@router.post("/bots/{bot_id}/resume")
async def resume_bot(bot_id: str):
    """OMS-05: 恢复 Bot 算力节点"""
    success = await bot_runtime.resume_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"无法恢复 Bot {bot_id}，可能未处于暂停状态")
    return {"status": "success", "message": f"Bot {bot_id} 已恢复"}


@router.post("/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    """OMS-05: 终止 Bot 算力节点"""
    success = await bot_runtime.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Bot {bot_id} 不存在")
    return {"status": "success", "message": f"Bot {bot_id} 已终止"}


@router.post("/algo/start")
async def start_algo_order(request: Request, req: AlgoOrderReq):
    """
    OMS-08: 接收并启动前端下发的算法拆单任务 (TWAP/VWAP/ICEBERG)
    通过 algo_engine 真实执行拆单逻辑
    """
    try:
        order = await algo_engine.start_algo(
            algo_type=req.algo_type,
            symbol=req.symbol,
            side=req.side,
            target_qty=req.target_qty,
            duration_minutes=req.duration_minutes,
        )
        # OMS-12: 审计日志
        db_session = None
        try:
            from backend.core.database import SessionLocal

            db_session = SessionLocal()
            log_audit(
                db_session,
                action="algo_start",
                detail={
                    "algo_id": order.algo_id,
                    "algo_type": req.algo_type,
                    "symbol": req.symbol,
                    "side": req.side,
                    "target_qty": req.target_qty,
                },
                request=request,
            )
        finally:
            if db_session:
                db_session.close()

        return {"status": "success", "message": "算法任务下达成功", "data": order.to_api_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/algo/{algo_id}/pause")
async def pause_algo_order(algo_id: str):
    """OMS-08: 暂停算法拆单"""
    success = await algo_engine.pause_algo(algo_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"无法暂停算法 {algo_id}")
    return {"status": "success", "message": f"算法 {algo_id} 已暂停"}


@router.post("/algo/{algo_id}/resume")
async def resume_algo_order(algo_id: str):
    """OMS-08: 恢复算法拆单"""
    success = await algo_engine.resume_algo(algo_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"无法恢复算法 {algo_id}")
    return {"status": "success", "message": f"算法 {algo_id} 已恢复"}


@router.post("/algo/{algo_id}/cancel")
async def cancel_algo_order(algo_id: str):
    """OMS-08: 取消算法拆单"""
    success = await algo_engine.cancel_algo(algo_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"算法 {algo_id} 不存在")
    return {"status": "success", "message": f"算法 {algo_id} 已取消"}


class AlgoAnalyticsReq(BaseModel):
    benchmark_price: float
    market_volume: int = 0
    market_vwap: float = 0
    fills: list = []


@router.post("/algo/analytics/{algo_id}")
async def get_algo_analytics(algo_id: str, req: AlgoAnalyticsReq):
    """
    TRADE-02: 算法执行分析报告。

    返回滑点、VWAP 偏离、参与率、Implementation Shortfall 等指标。
    """
    order = algo_engine._orders.get(algo_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"算法 {algo_id} 不存在")

    report = algo_analytics.execution_report(
        algo_id=order.algo_id,
        algo_type=order.algo_type,
        symbol=order.symbol,
        side=order.side,
        target_qty=order.target_qty,
        filled_qty=order.filled_qty,
        total_cost=order.total_cost,
        benchmark_price=req.benchmark_price,
        market_volume=req.market_volume,
        market_vwap=req.market_vwap,
        fills=req.fills,
        duration_minutes=order.duration_minutes,
    )

    return {"status": "success", "data": report}


# ── 交易模式 (OMS-11) ─────────────────────────────────────────────────────

_TRADING_MODE_KEY = "quant:oms:trading_mode"  # Redis 键: 运行时交易模式


_VALID_TRADING_MODES = frozenset({"SANDBOX", "PAPER", "LIVE"})


async def _get_trading_mode() -> str:
    """获取当前交易模式: 优先读 Redis 热切换值，降级读环境变量"""
    try:
        mode = await redis_client.get(_TRADING_MODE_KEY)
        if mode in _VALID_TRADING_MODES:
            return mode
    except Exception:
        pass
    return "LIVE" if os.getenv("FUTU_TRD_ENV", "SIMULATE").upper() == "REAL" else "SANDBOX"


@router.get("/mode")
async def get_trading_mode():
    """OMS-11 / FE-PROD-02: 获取当前交易模式 (SANDBOX/PAPER/LIVE)"""
    mode = await _get_trading_mode()
    return {"status": "success", "data": {"mode": mode}}


@router.post("/mode/switch")
async def switch_trading_mode(request: Request, req: ModeSwitchReq, db: Session = Depends(get_db)):
    """
    OMS-11 / FE-PROD-02: 热切换交易模式 (SANDBOX/PAPER/LIVE)
    写入 Redis 后立即生效；非 LIVE 均不走真实资金（PAPER = 纸面账本语义）。
    """
    if req.mode not in _VALID_TRADING_MODES:
        raise HTTPException(status_code=400, detail="模式必须为 SANDBOX、PAPER 或 LIVE")

    current = await _get_trading_mode()

    # 写入 Redis — 立即生效
    await redis_client.set(_TRADING_MODE_KEY, req.mode)

    # PubSub 广播模式变更，前端 WebSocket 实时更新
    await redis_client.publish("oms:mode_change", json.dumps({"mode": req.mode, "previous": current}))

    # OMS-12: 审计日志
    log_audit(db, action="mode_switch", detail={"from": current, "to": req.mode}, request=request)

    return {
        "status": "success",
        "message": f"交易模式已切换: {current} → {req.mode}，立即生效。",
        "data": {"mode": req.mode, "previous": current},
    }


@router.websocket("/ws")
async def websocket_oms_updates(websocket: WebSocket):
    """Websocket 接口：实时推送 OMS 订单、成交与机器人状态"""
    await websocket.accept()

    pubsub = redis_client.pubsub()

    # 订阅所有 OMS 相关的 Redis 消息通道
    channels = [
        "oms:bots:update",
        "oms:orders:update",
        "oms:trades:new",
        "oms:bot_log:stream",
        "oms:algo_executions:update",
        "oms:positions:update",
        "oms:mode_change",
    ]  # noqa: E501

    async def listen_redis():
        await pubsub.subscribe(*channels)
        async for message in pubsub.listen():
            if message["type"] == "message":
                raw_channel = message["channel"]
                channel = raw_channel.decode("utf-8") if isinstance(raw_channel, bytes) else str(raw_channel)  # noqa: E501
                data = json.loads(message["data"])

                # 根据不同的消息通道，包装成不同类型的事件发给前端
                if channel == "oms:bots:update":
                    await websocket.send_json({"type": "bots_update", "data": data})
                elif channel == "oms:orders:update":
                    await websocket.send_json({"type": "active_orders_update", "data": data})  # noqa: E501
                elif channel == "oms:trades:new":
                    await websocket.send_json({"type": "new_trade", "data": data})
                elif channel == "oms:bot_log:stream":
                    await websocket.send_json({"type": "bot_log", "data": data})
                elif channel == "oms:algo_executions:update":
                    await websocket.send_json({"type": "algo_executions_update", "data": data})  # noqa: E501
                elif channel == "oms:positions:update":
                    await websocket.send_json({"type": "positions_update", "data": data})  # noqa: E501
                elif channel == "oms:mode_change":
                    await websocket.send_json({"type": "mode_change", "data": data})  # noqa: E501

    async def listen_client():
        try:
            while True:
                await websocket.receive_text()  # 仅监听心跳或客户端断连
        except WebSocketDisconnect:
            print("⚠️ [OMS Websocket] 前端已断开连接。")
        except Exception:
            pass

    listen_r_task = asyncio.create_task(listen_redis())
    listen_c_task = asyncio.create_task(listen_client())

    # 任何一个协程结束（如客户端断连），立刻终止另一个，释放资源
    done, pending = await asyncio.wait([listen_r_task, listen_c_task], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        await pubsub.unsubscribe(*channels)
    except Exception:
        pass
    await pubsub.close()
