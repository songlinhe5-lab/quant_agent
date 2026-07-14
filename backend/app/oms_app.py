"""
OMS 用例（BE-ARCH-02）

Kill Switch 编排：Redis 信号 → Broker 物理清仓 → Bot/Algo 停机 → 订单落库取消。
Router 只做鉴权/参数校验/BackgroundTasks 调度。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from backend.app.broker import broker
from backend.core.redis_client import redis_client
from backend.services.algo_engine import algo_engine
from backend.services.bot_runtime import bot_runtime
from backend.services.oms_service import oms_service

logger = logging.getLogger("OMS")


async def engage_kill_switch_flags() -> None:
    """广播熔断并写入 OMS 状态（API 热路径，须极速返回）。"""
    await redis_client.publish("oms:kill_switch", "ENGAGE")
    await redis_client.set("oms:status", "KILLED", ex=3600)


async def run_emergency_liquidation(db: Session) -> dict[str, Any]:
    """
    物理级熔断清仓：
    1. BrokerGateway 撤单 + 市价平仓（无 trade_ctx 则跳过）
    2. 终止 Bot / 取消算法拆单
    3. 活动订单标记 CANCELLED
    """
    logger.warning("🚨 [KILL SWITCH] 正在执行全网物理熔断清仓...")
    try:
        result = await broker.execute_emergency_liquidation()
        if not result.get("ok"):
            await bot_runtime.stop_all_bots()
            await algo_engine.cancel_all()
            await oms_service.mark_all_orders_cancelled(db)
            return {"ok": False, "reason": result.get("reason", "no_trade_ctx")}

        logger.warning("✅ [KILL SWITCH] 物理清仓程序全部下达完毕。")
        await oms_service.mark_all_orders_cancelled(db)
        await bot_runtime.stop_all_bots()
        await algo_engine.cancel_all()
        return {"ok": True, "reason": None}
    except Exception as e:
        logger.error(f"🚨 [KILL SWITCH] 物理清仓执行异常: {str(e)}")
        return {"ok": False, "reason": str(e)}
