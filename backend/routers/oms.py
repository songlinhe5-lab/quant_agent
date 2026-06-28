import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from backend.core.redis_client import redis_client

router = APIRouter(prefix="/oms", tags=["OMS & Live Bots"])

# 💡 在真实的系统中，这些初始数据应该从数据库或 OMS 引擎的持久化状态中读取。
# 此处我们暂时使用之前的 Mock 数据作为首次加载的快照。
try:
    from backend.services.oms_mock_data import (
        ACTIVE_ORDERS,
        ALGO_EXECUTIONS,
        HISTORICAL_TRADES,
        INITIAL_BOTS,
    )
except ImportError:
    INITIAL_BOTS = []
    ACTIVE_ORDERS = []
    HISTORICAL_TRADES = []
    ALGO_EXECUTIONS = []

# --- 💡 新增：后台模拟日志生成器，让机器人终端看起来更真实 ---

# 全局任务句柄，确保日志生成器只运行一个实例
_log_generator_task: Optional[asyncio.Task] = None

async def mock_bot_log_generator():
    """
    后台模拟任务：为正在运行的 Bot 动态生成日志并推送到 Redis
    """
    while True:
        try:
            # 💡 只为处于 'running' 状态的机器人生成日志
            running_bots = [bot for bot in INITIAL_BOTS if bot.get("status") == "running"]  # noqa: E501
            if not running_bots:
                await asyncio.sleep(5)
                continue

            # 随机挑选一个正在运行的 bot
            bot_to_log = random.choice(running_bots)

            # 模拟生成不同类型的日志
            log_type = random.choices(["info", "success", "warn"], weights=[0.7, 0.2, 0.1], k=1)[0]  # noqa: E501

            if log_type == "info":
                msg = random.choice(["Scanning market for entry signals...", f"Current position size: {random.randint(100, 500)} shares.", "ATR(14) is stable, maintaining trailing stop.", "Market volume is low, holding position."])  # noqa: E501
            elif log_type == "success":
                msg = f"✅ Trade executed: BOUGHT {random.randint(1,5)*100} shares of {bot_to_log['ticker']} @ {random.uniform(150, 160):.2f}"  # noqa: E501
            else: # warn
                msg = f"⚠️ High volatility detected! VIX spiked by {random.uniform(5, 15):.1f}%. Tightening stop loss."  # noqa: E501

            log_entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": log_type}  # noqa: E501

            payload = {"bot_id": bot_to_log["id"], "log": log_entry}

            await redis_client.publish("oms:bot_log:stream", json.dumps(payload))

        except Exception as e:
            print(f"Error in mock log generator: {e}")

        # 随机休眠 2-8 秒
        await asyncio.sleep(random.uniform(2, 8))

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

@router.get("/state")
async def get_oms_initial_state():
    """获取 OMS 模块的初始状态 (Bots, Orders, Trades)"""
    return {
        "status": "success",
        "data": {
            "bots": INITIAL_BOTS,
            "active_orders": ACTIVE_ORDERS,
            "historical_trades": HISTORICAL_TRADES,
            "algo_executions": ALGO_EXECUTIONS
        }
    }

async def execute_emergency_liquidation():
    """
    执行物理级熔断清仓逻辑：
    1. 撤销所有未成交挂单
    2. 获取所有当前持仓
    3. 以市价平掉所有多空仓位
    """
    logger = logging.getLogger("OMS")
    logger.warning("🚨 [KILL SWITCH] 正在执行全网物理熔断清仓...")

    try:
        from futu import ModifyOrderOp, OrderType, TrdSide

        from backend.services.futu_service import futu_service

        ctx = getattr(futu_service, "trade_ctx", None)
        if not ctx:
            logger.error("🚨 [KILL SWITCH] 未检测到有效的底层交易网关上下文 (trade_ctx)，降级为仅阻断新订单流。")  # noqa: E501

            # 💡 本地沙箱体验补充：如果没有连接真实券商，则在内存中模拟强平并广播，完成前端视觉闭环  # noqa: E501
            ACTIVE_ORDERS.clear()
            for bot in INITIAL_BOTS:
                if bot.get("status") != "error":
                    bot["status"] = "error"
                    bot["logs"].append({"time": datetime.now().strftime("%H:%M:%S"), "msg": "🚨 物理熔断触发，进程已强杀 (Mock)", "type": "warn"})  # noqa: E501

            for algo in ALGO_EXECUTIONS:
                if algo.get("status") in ["RUNNING", "PAUSED"]:
                    algo["status"] = "ERROR"
                    algo["message"] = "风控拦截：全局物理熔断已触发"

            await redis_client.publish("oms:orders:update", json.dumps(ACTIVE_ORDERS))
            await redis_client.publish("oms:bots:update", json.dumps(INITIAL_BOTS))
            await redis_client.publish("oms:algo_executions:update", json.dumps(ALGO_EXECUTIONS))  # noqa: E501
            return

        # 💡 1. 撤销所有活跃订单 (防并发：在独立的线程中执行同步的底层 SDK 调用)
        def cancel_all_orders():
            ret, data = ctx.order_list_query(status_filter_list=['SUBMITTED', 'WAITING_SUBMIT'])  # noqa: E501
            if ret == 0 and not data.empty:
                for _, row in data.iterrows():
                    ctx.modify_order(ModifyOrderOp.CANCEL, row['order_id'], 0, 0, trd_env=row['trd_env'])  # noqa: E501
                    logger.warning(f"🛑 [KILL SWITCH] 撤单指令已发送: {row['order_id']}")  # noqa: E501

        # 💡 2. 遍历持仓并下达市价平仓指令
        def close_all_positions():
            ret_pos, pos_data = ctx.position_list_query()
            if ret_pos == 0 and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = float(row.get('qty', 0))
                    if qty == 0:
                        continue

                    symbol = row['code']
                    pos_side = row.get('position_side', 'LONG') # 兼容不同账户类型

                    trd_side = TrdSide.SELL if pos_side == 'LONG' else TrdSide.BUY

                    logger.warning(f"💥 [KILL SWITCH] 正在市价平仓: {symbol} 数量 {abs(qty)} 方向 {trd_side}")  # noqa: E501
                    ctx.place_order(
                        price=0.0,
                        qty=abs(qty),
                        code=symbol,
                        trd_side=trd_side,
                        order_type=OrderType.MARKET,
                        trd_env=row['trd_env']
                    )

        # 由于 Futu API 大部分为同步阻塞调用，将其包装进线程池中运行，避免阻塞 FastAPI 事件循环  # noqa: E501
        await asyncio.to_thread(cancel_all_orders)
        await asyncio.sleep(0.5) # 💡 给交易所撤单确认时间，释放冻结的持仓资产
        await asyncio.to_thread(close_all_positions)

        logger.warning("✅ [KILL SWITCH] 物理清仓程序全部下达完毕。")

    except Exception as e:
        logger.error(f"🚨 [KILL SWITCH] 物理清仓执行异常: {str(e)}")

@router.post("/kill_switch")
async def trigger_kill_switch(background_tasks: BackgroundTasks, req: KillSwitchReq):
    """
    【全局熔断 Kill Switch】
    瞬间阻断所有实盘 Bot 的进程信号并下达市价全平指令给券商网关
    """
    try:
        # 发布高优 PubSub 事件，由底层 C++/Rust 网关或者守护进程拦截并紧急市价平仓
        await redis_client.publish("oms:kill_switch", "ENGAGE")
        # 记录持久化状态 (进入风控审核期前禁止新订单)
        await redis_client.set("oms:status", "KILLED", ex=3600)

        # 💡 将物理级清仓逻辑委托给后台任务，保证 API 的极速响应
        background_tasks.add_task(execute_emergency_liquidation)

        return {"status": "success", "message": "Kill switch engaged. All positions are being closed."}  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to broadcast kill switch signal: {str(e)}")  # noqa: E501

@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, req: CancelOrderReq):
    """
    带【防并发幂等性锁】的撤单接口
    """
    lock_key = f"oms:cancel_lock:{req.idempotency_key}"

    # 利用 Redis 的 NX (Not Exists) 保证同一个幂等性 Key 只能处理一次
    is_set = await redis_client.set(lock_key, "1", nx=True, ex=60)
    if not is_set:
        return {"status": "success", "message": "Cancel request already in progress"}

    try:
        await redis_client.publish("oms:order_cancel", json.dumps({"order_id": order_id}))  # noqa: E501
        return {"status": "success", "message": "Cancel requested"}
    except Exception:
        await redis_client.delete(lock_key)
        raise HTTPException(status_code=500, detail="Cancellation dispatch failed")

@router.post("/orders/{order_id}/modify")
async def modify_order(order_id: str, req: ModifyOrderReq):
    """
    修改订单价格 (改单) 接口
    """
    try:
        # 1. 模拟派发改单指令给底层交易网关
        payload = {"order_id": order_id, "new_price": req.price}
        await redis_client.publish("oms:order_modify", json.dumps(payload))

        # 2. 💡 本地沙箱闭环体验：直接修改内存数据并通过 WebSocket 广播给前端
        for order in ACTIVE_ORDERS:
            if order.get("id") == order_id:
                # 将修改后的浮点价格转为字符串以匹配前端渲染格式
                order["price"] = f"{req.price:.2f}"
                await redis_client.publish("oms:orders:update", json.dumps(ACTIVE_ORDERS))  # noqa: E501
                break

        return {"status": "success", "message": "改单指令已下发"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Modification dispatch failed: {str(e)}")  # noqa: E501

@router.post("/algo/start")
async def start_algo_order(req: AlgoOrderReq):
    """
    接收并启动前端下发的算法拆单任务 (TWAP/VWAP/ICEBERG)
    """
    try:
        algo_id = f"algo_{req.algo_type.lower()}_{int(time.time())}"
        algo_task = {
            "id": algo_id,
            "algo_type": req.algo_type,
            "symbol": req.symbol,
            "target_qty": req.target_qty,
            "filled_qty": 0,
            "avg_price": "0.00",
            "progress": 0,
            "status": "RUNNING",
            "message": f"算法启动，准备拆分 {req.side} 订单"
        }
        # 💡 在真实环境中，这里会将任务通过 ZeroMQ/Redis 发送给底层的 C++/Rust 拆单网关
        ALGO_EXECUTIONS.insert(0, algo_task) # 此处将任务写回模块全局模拟状态中
        # 通过 WebSocket 广播这一条最新的执行状态回滚给前端
        await redis_client.publish("oms:algo_executions:update", json.dumps(ALGO_EXECUTIONS))  # noqa: E501
        return {"status": "success", "message": "算法任务下达成功", "data": algo_task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws")
async def websocket_oms_updates(websocket: WebSocket):
    """Websocket 接口：实时推送 OMS 订单、成交与机器人状态"""
    global _log_generator_task
    await websocket.accept()

    # 💡 启动后台模拟日志生成器 (如果尚未运行)
    if _log_generator_task is None or _log_generator_task.done():
        print("🚀 [OMS Mock] Starting background bot log generator...")
        _log_generator_task = asyncio.create_task(mock_bot_log_generator())

    pubsub = redis_client.pubsub()

    # 订阅所有 OMS 相关的 Redis 消息通道
    channels = ["oms:bots:update", "oms:orders:update", "oms:trades:new", "oms:bot_log:stream", "oms:algo_executions:update"]  # noqa: E501

    async def listen_redis():
        await pubsub.subscribe(*channels)
        async for message in pubsub.listen():
            if message["type"] == "message":
                raw_channel = message["channel"]
                channel = raw_channel.decode('utf-8') if isinstance(raw_channel, bytes) else str(raw_channel)  # noqa: E501
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

    async def listen_client():
        try:
            while True:
                await websocket.receive_text() # 仅监听心跳或客户端断连
        except WebSocketDisconnect:
            print("⚠️ [OMS Websocket] 前端已断开连接。")
        except Exception:
            pass

    listen_r_task = asyncio.create_task(listen_redis())
    listen_c_task = asyncio.create_task(listen_client())

    # 任何一个协程结束（如客户端断连），立刻终止另一个，释放资源
    done, pending = await asyncio.wait(
        [listen_r_task, listen_c_task],
        return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        await pubsub.unsubscribe(*channels)
    except Exception:
        pass
    await pubsub.close()
