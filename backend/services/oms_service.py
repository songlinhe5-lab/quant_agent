"""
OMS 核心服务层 (OMS-01~04)
桥接 OMS 面板与真实交易链路，替代内存 Mock 数据。

职责:
- OMS-01: 订单持久化 (PostgreSQL orders 表)
- OMS-02: 成交记录打通 (trade_logs → OMS 面板)
- OMS-03: 真实订单状态同步 (DB + Redis PubSub)
- OMS-04: 持仓实时同步 (Futu → Redis 缓存)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.core.models import Order, TradeLog
from backend.core.redis_client import redis_client

logger = logging.getLogger("OMS")

# ── Redis 键空间约定 ────────────────────────────────────────────────────────
REDIS_ACTIVE_ORDERS_KEY = "quant:oms:active_orders"
REDIS_POSITIONS_KEY = "quant:oms:positions:{market}"
REDIS_OMS_STATUS_KEY = "quant:oms:status"


class OmsService:
    """OMS 核心服务 - 订单持久化 + 实时状态同步"""

    # ── 订单持久化 (OMS-01) ──────────────────────────────────────────────

    async def create_order(
        self,
        db: Session,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        qty: int,
        price: float,
        is_simulated: bool = True,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建订单记录并同步到 Redis 缓存 + PubSub 广播。
        在 trade.py 下单成功后调用。
        """
        try:
            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side.upper(),
                order_type=order_type,
                qty=qty,
                filled_qty=0,
                price=price,
                status="SUBMITTED",
                is_simulated=is_simulated,
                note=note,
            )
            db.add(order)
            db.commit()
            db.refresh(order)

            # 同步到 Redis 活动挂单缓存
            await self._sync_order_to_redis(order)
            # 广播订单变更事件
            await self._publish_orders_update(db)

            logger.info(f"[OMS] 订单已持久化: {order_id} {side} {symbol} x{qty}")
            return {"status": "success", "order_id": order_id}
        except Exception as e:
            db.rollback()
            logger.error(f"[OMS] 订单持久化失败: {e}")
            return {"status": "error", "message": str(e)}

    async def update_order_status(
        self,
        db: Session,
        order_id: str,
        status: str,
        filled_qty: Optional[int] = None,
        avg_fill_price: Optional[float] = None,
    ) -> bool:
        """
        更新订单状态 (SUBMITTED → PARTIALLY_FILLED → FILLED / CANCELLED)。
        Futu 回调或定时轮询时调用。
        """
        try:
            order = db.query(Order).filter(Order.order_id == order_id).first()
            if not order:
                logger.warning(f"[OMS] 订单不存在: {order_id}")
                return False

            order.status = status
            if filled_qty is not None:
                order.filled_qty = filled_qty
            if avg_fill_price is not None:
                order.avg_fill_price = avg_fill_price

            db.commit()

            # 同步到 Redis
            await self._sync_order_to_redis(order)
            await self._publish_orders_update(db)

            logger.info(f"[OMS] 订单状态更新: {order_id} → {status}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"[OMS] 订单状态更新失败: {e}")
            return False

    # ── 活动挂单查询 (OMS-03) ────────────────────────────────────────────

    async def get_active_orders(self, db: Session) -> List[Dict[str, Any]]:
        """
        获取活动挂单列表 (SUBMITTED / PARTIALLY_FILLED)。
        优先从 Redis 缓存读取，缓存未命中时从 DB 加载并回写。
        """
        # 1. 尝试从 Redis 缓存读取
        cached = await redis_client.get(REDIS_ACTIVE_ORDERS_KEY)
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. 缓存未命中，从 DB 加载
        orders = (
            db.query(Order)
            .filter(Order.status.in_(["SUBMITTED", "PARTIALLY_FILLED", "PENDING"]))
            .order_by(Order.created_at.desc())
            .all()
        )

        result = [self._order_to_api_format(o) for o in orders]

        # 3. 回写 Redis 缓存 (5 分钟 TTL)
        await redis_client.set(REDIS_ACTIVE_ORDERS_KEY, json.dumps(result), ex=300)
        return result

    async def get_historical_trades(self, db: Session, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取历史成交记录 (OMS-02)。
        从 trade_logs 表读取真实成交数据。
        """
        trades = db.query(TradeLog).order_by(TradeLog.timestamp.desc()).limit(limit).all()
        return [self._trade_to_api_format(t) for t in trades]

    # ── 持仓同步 (OMS-04) ────────────────────────────────────────────────

    async def sync_positions_from_futu(self, market: str = "HK") -> List[Dict[str, Any]]:
        """
        从 Futu 拉取真实持仓列表，写入 Redis 缓存。
        由后台守护进程定时调用。
        """
        try:
            from backend.services.futu_service import futu_service

            acc_info = await futu_service.get_account_info(market)
            if acc_info.get("status") != "success":
                logger.warning(f"[OMS] 持仓同步失败 ({market}): {acc_info.get('message')}")
                return []

            positions = acc_info.get("positions", [])
            redis_key = REDIS_POSITIONS_KEY.format(market=market)
            await redis_client.set(redis_key, json.dumps(positions), ex=30)

            # 广播持仓变更
            await redis_client.publish(
                "oms:positions:update",
                json.dumps({"market": market, "positions": positions}),
            )

            logger.debug(f"[OMS] 持仓同步完成 ({market}): {len(positions)} 条")
            return positions
        except Exception as e:
            logger.error(f"[OMS] 持仓同步异常 ({market}): {e}")
            return []

    async def get_cached_positions(self, market: str = "HK") -> List[Dict[str, Any]]:
        """从 Redis 缓存读取最新持仓"""
        redis_key = REDIS_POSITIONS_KEY.format(market=market)
        cached = await redis_client.get(redis_key)
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    # ── Kill Switch 增强 (OMS-03) ────────────────────────────────────────

    async def mark_all_orders_cancelled(self, db: Session) -> int:
        """熔断时将所有活动订单标记为 CANCELLED"""
        try:
            count = (
                db.query(Order)
                .filter(Order.status.in_(["SUBMITTED", "PARTIALLY_FILLED", "PENDING"]))
                .update({"status": "CANCELLED"})
            )
            db.commit()
            # 清空 Redis 活动挂单缓存
            await redis_client.delete(REDIS_ACTIVE_ORDERS_KEY)
            await self._publish_orders_update(db)
            logger.warning(f"[OMS] 熔断: {count} 笔订单已标记为 CANCELLED")
            return count
        except Exception as e:
            db.rollback()
            logger.error(f"[OMS] 熔断订单标记失败: {e}")
            return 0

    # ── 内部工具方法 ──────────────────────────────────────────────────────

    async def _sync_order_to_redis(self, order: Order) -> None:
        """将单个订单同步到 Redis 活动挂单列表"""
        # 读取当前缓存
        cached = await redis_client.get(REDIS_ACTIVE_ORDERS_KEY)
        orders_list = json.loads(cached) if cached else []

        # 如果订单已终结，从活动列表中移除
        if order.status in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED"):
            orders_list = [o for o in orders_list if o.get("id") != order.order_id]
        else:
            order_dict = self._order_to_api_format(order)
            # 更新或追加
            found = False
            for i, o in enumerate(orders_list):
                if o.get("id") == order.order_id:
                    orders_list[i] = order_dict
                    found = True
                    break
            if not found:
                orders_list.insert(0, order_dict)

        await redis_client.set(REDIS_ACTIVE_ORDERS_KEY, json.dumps(orders_list), ex=300)

    async def _publish_orders_update(self, db: Session) -> None:
        """通过 PubSub 广播活动挂单变更"""
        orders = await self.get_active_orders(db)
        await redis_client.publish("oms:orders:update", json.dumps(orders))

    @staticmethod
    def _order_to_api_format(order: Order) -> Dict[str, Any]:
        """将 DB Order 模型转为前端 API 格式"""
        return {
            "id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "price": f"{order.price:.2f}" if order.price else "0.00",
            "qty": order.qty,
            "filled": order.filled_qty,
            "status": order.status,
            "time": order.created_at.strftime("%H:%M:%S") if order.created_at else "",
        }

    @staticmethod
    def _trade_to_api_format(trade: TradeLog) -> Dict[str, Any]:
        """将 DB TradeLog 模型转为前端 API 格式"""
        return {
            "id": str(trade.id),
            "symbol": trade.ticker,
            "side": trade.action,
            "avg_price": f"{trade.price:.2f}" if trade.price else "0.00",
            "qty": trade.qty,
            "pnl": 0.0,  # TradeLog 无 PnL 字段，后续可扩展
            "time": trade.timestamp.strftime("%H:%M:%S") if trade.timestamp else "",
        }


# 导出全局单例
oms_service = OmsService()
