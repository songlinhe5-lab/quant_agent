"""
算法拆单引擎 (OMS-08~09)

职责:
- OMS-08: TWAP/VWAP/ICEBERG 真实拆单执行，通过 oms_service 下单
- OMS-09: 算法执行进度 Redis Hash 持久化 + DB 归档已完成任务

算法策略:
- TWAP: 等时间切片，每 interval 秒下固定数量
- VWAP: 模拟成交量加权切片 (简化版: 前密后疏的指数衰减权重)
- ICEBERG: 每次仅显示 iceberg_qty，成交后自动补下一笔
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger("OMS.AlgoEngine")

# Redis 键空间
_ALGO_ACTIVE_KEY = "quant:oms:algo:active"       # Hash: algo_id → JSON
_ALGO_HISTORY_KEY = "quant:oms:algo:history"      # List: 已完成任务 JSON
_ALGO_STREAM_CHANNEL = "oms:algo_executions:update"  # PubSub 广播

# 港股每手股数硬编码映射 (常用标的，作为 Futu API 无 lot_size 时的兜底)
_HK_LOT_SIZE_MAP: Dict[str, int] = {
    "00700.HK": 100,  # 腾讯
    "09988.HK": 100,  # 阿里巴巴
    "00772.HK": 200,  # 阅文集团
    "03690.HK": 100,  # 美团
    "09999.HK": 100,  # 网易
    "01024.HK": 100,  # 快手
    "09618.HK": 50,   # 京东
    "02015.HK": 100,  # 理想汽车
    "09868.HK": 100,  # 小鹏汽车
    "00005.HK": 500,  # 汇丰控股
    "00939.HK": 1000, # 建设银行
    "01398.HK": 1000, # 工商银行
    "03988.HK": 1000, # 中国银行
    "02628.HK": 1000, # 中国人寿
    "02318.HK": 500,  # 中国平安
}


async def _get_lot_size(symbol: str) -> int:
    """获取股票每手股数: 优先从 market_snapshot 获取，降级用硬编码映射，美股默认 1"""
    # 美股直接返回 1
    if not symbol.upper().endswith(".HK"):
        return 1

    # 尝试从 market_snapshot 获取 (包含 lot_size)
    try:
        from backend.services.futu_service import futu_service
        snapshot = await futu_service.get_market_snapshots([symbol])
        if snapshot.get("status") == "success":
            data_list = snapshot.get("data", [])
            if data_list:
                lot = data_list[0].get("lot_size", 0)
                if lot and lot > 0:
                    logger.info(f"[AlgoEngine] {symbol} 从 snapshot 获取 lot_size={lot}")
                    return int(lot)
    except Exception as e:
        logger.debug(f"[AlgoEngine] snapshot 获取 lot_size 失败: {e}")

    # 尝试从行情获取 (备用)
    try:
        from backend.services.futu_service import futu_service
        quote = await futu_service.get_quote(symbol)
        lot = quote.get("lot_size", 0)
        if lot and lot > 0:
            logger.info(f"[AlgoEngine] {symbol} 从 quote 获取 lot_size={lot}")
            return int(lot)
    except Exception:
        pass

    # 硬编码兜底
    lot = _HK_LOT_SIZE_MAP.get(symbol.upper(), 0)
    if lot > 0:
        logger.info(f"[AlgoEngine] {symbol} 使用硬编码 lot_size={lot}")
        return lot

    # 最终默认值
    logger.warning(f"[AlgoEngine] {symbol} lot_size 未知，使用默认 100 (港股)")
    return 100


class AlgoOrder:
    """单个算法拆单订单"""

    def __init__(
        self,
        algo_id: str,
        algo_type: str,
        symbol: str,
        side: str,
        target_qty: int,
        duration_minutes: int = 60,
        iceberg_visible_qty: int = 100,
    ):
        self.algo_id = algo_id
        self.algo_type = algo_type
        self.symbol = symbol
        self.side = side
        self.target_qty = target_qty
        self.duration_minutes = duration_minutes
        self.iceberg_visible_qty = iceberg_visible_qty
        self.filled_qty: int = 0
        self.total_cost: float = 0.0
        self.lot_size: int = 1  # 每手股数 (港股/美股默认 1，启动时从行情获取)
        self.status: str = "RUNNING"  # RUNNING / PAUSED / COMPLETED / ERROR / CANCELLED
        self.message: str = f"算法启动，准备拆分 {side} 订单"
        self.task: Optional[asyncio.Task] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_requested = False
        self._started_at = time.time()

    @property
    def avg_price(self) -> str:
        if self.filled_qty <= 0:
            return "0.00"
        return f"{self.total_cost / self.filled_qty:.2f}"

    @property
    def progress(self) -> int:
        if self.target_qty <= 0:
            return 100
        return min(100, int(self.filled_qty / self.target_qty * 100))

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "id": self.algo_id,
            "algo_type": self.algo_type,
            "symbol": self.symbol,
            "target_qty": self.target_qty,
            "filled_qty": self.filled_qty,
            "avg_price": self.avg_price,
            "progress": self.progress,
            "status": self.status,
            "message": self.message,
        }


class AlgoEngine:
    """
    算法拆单引擎 (OMS-08~09)

    管理所有算法拆单订单的生命周期与执行逻辑
    """

    def __init__(self):
        self._orders: Dict[str, AlgoOrder] = {}

    # ── 生命周期管理 ─────────────────────────────────────────────────────

    async def start_algo(
        self,
        algo_type: str,
        symbol: str,
        side: str,
        target_qty: int,
        duration_minutes: int = 60,
    ) -> AlgoOrder:
        """启动算法拆单任务"""
        algo_id = f"algo_{algo_type.lower()}_{int(time.time())}"
        order = AlgoOrder(
            algo_id=algo_id,
            algo_type=algo_type,
            symbol=symbol,
            side=side,
            target_qty=target_qty,
            duration_minutes=duration_minutes,
        )

        # 获取 lot_size (港股必须整手下单)
        lot = await _get_lot_size(symbol)
        order.lot_size = lot
        # 向上取整到整手
        if order.target_qty % lot != 0:
            order.target_qty = ((order.target_qty // lot) + 1) * lot
            logger.info(f"[AlgoEngine] target_qty 向上取整到 {order.target_qty} (lot_size={lot})")

        self._orders[algo_id] = order

        # 写入 Redis 活动表
        await self._save_algo_state(order)
        await self._broadcast_update()

        # 启动 asyncio.Task 执行拆单
        order.task = asyncio.create_task(self._run_algo_loop(order))

        logger.info(f"[AlgoEngine] 算法启动: {algo_id} ({algo_type} {side} {symbol} x{target_qty})")
        return order

    async def pause_algo(self, algo_id: str) -> bool:
        """暂停算法执行"""
        order = self._orders.get(algo_id)
        if not order or order.status != "RUNNING":
            return False
        order._pause_event.clear()
        order.status = "PAUSED"
        order.message = "算法已暂停，等待恢复"
        await self._save_algo_state(order)
        await self._broadcast_update()
        return True

    async def resume_algo(self, algo_id: str) -> bool:
        """恢复算法执行"""
        order = self._orders.get(algo_id)
        if not order or order.status != "PAUSED":
            return False
        order._pause_event.set()
        order.status = "RUNNING"
        order.message = f"算法已恢复，继续拆分 {order.side} 订单"
        await self._save_algo_state(order)
        await self._broadcast_update()
        return True

    async def cancel_algo(self, algo_id: str) -> bool:
        """取消算法拆单"""
        order = self._orders.get(algo_id)
        if not order:
            return False

        order._stop_requested = True
        order._pause_event.set()
        if order.task and not order.task.done():
            order.task.cancel()
            try:
                await order.task
            except (asyncio.CancelledError, Exception):
                pass

        order.status = "CANCELLED"
        order.message = "算法已手动取消"
        await self._save_algo_state(order)
        await self._archive_algo(order)
        await self._broadcast_update()
        return True

    async def cancel_all(self) -> int:
        """Kill Switch: 取消所有运行中的算法"""
        count = 0
        for algo_id, order in list(self._orders.items()):
            if order.status in ("RUNNING", "PAUSED"):
                await self.cancel_algo(algo_id)
                count += 1
        return count

    # ── 查询接口 ──────────────────────────────────────────────────────────

    async def get_all_algo_orders(self) -> list[Dict[str, Any]]:
        """获取所有算法订单 (活动 + 最近已完成)"""
        result = []
        # 活动订单
        for order in self._orders.values():
            result.append(order.to_api_dict())
        return result

    # ── 内部: 算法执行主循环 ─────────────────────────────────────────────

    async def _run_algo_loop(self, order: AlgoOrder) -> None:
        """算法拆单主循环"""
        try:
            if order.algo_type == "TWAP":
                await self._run_twap(order)
            elif order.algo_type == "VWAP":
                await self._run_vwap(order)
            elif order.algo_type == "ICEBERG":
                await self._run_iceberg(order)
            else:
                order.status = "ERROR"
                order.message = f"不支持的算法类型: {order.algo_type}"
        except asyncio.CancelledError:
            order.message = "算法被外部终止"
            raise
        except Exception as e:
            order.status = "ERROR"
            order.message = f"算法执行异常: {str(e)[:100]}"
            logger.warning(f"[AlgoEngine] {order.algo_id} 异常: {e}")
        finally:
            if order.status == "RUNNING":
                order.status = "COMPLETED"
                order.message = "算法拆单全部完成"
            await self._save_algo_state(order)
            await self._archive_algo(order)
            await self._broadcast_update()

    async def _run_twap(self, order: AlgoOrder) -> None:
        """TWAP: 等时间切片拆单"""
        remaining = order.target_qty - order.filled_qty
        if remaining <= 0:
            return

        # 计算切片: 每 30 秒一笔，最少 2 笔
        total_slices = max(2, order.duration_minutes * 2)
        slice_qty = max(order.lot_size, remaining // total_slices)
        # 向下取整到整手
        slice_qty = (slice_qty // order.lot_size) * order.lot_size
        if slice_qty < order.lot_size:
            slice_qty = order.lot_size

        slice_idx = 0
        while not order._stop_requested and order.filled_qty < order.target_qty:
            await order._pause_event.wait()
            if order._stop_requested:
                break

            slice_idx += 1
            current_slice = min(slice_qty, order.target_qty - order.filled_qty)
            # 确保当前切片也是整手 (最后一笔可能不足一手时取剩余)
            if current_slice < order.lot_size and current_slice < order.target_qty - order.filled_qty:
                current_slice = order.lot_size
            current_slice = min(current_slice, order.target_qty - order.filled_qty)

            # 模拟成交 (沙箱模式: 直接以当前价成交)
            fill_price = await self._simulate_fill(order.symbol, current_slice, order.side)
            order.filled_qty += current_slice
            order.total_cost += fill_price * current_slice

            remaining = order.target_qty - order.filled_qty
            eta_min = max(0, (remaining // max(1, slice_qty)) * 30 // 60)
            order.message = f"TWAP 执行中，剩余 {remaining} 股，预计 {eta_min} 分钟"

            await self._save_algo_state(order)
            await self._broadcast_update()

            if order.filled_qty >= order.target_qty:
                break

            await asyncio.sleep(30)  # 30 秒间隔

    async def _run_vwap(self, order: AlgoOrder) -> None:
        """VWAP: 模拟成交量加权拆单 (前密后疏指数衰减)"""
        remaining = order.target_qty - order.filled_qty
        if remaining <= 0:
            return

        total_slices = max(2, order.duration_minutes * 2)
        # 生成指数衰减权重: 前面的切片分更多量
        weights = [math.exp(-0.05 * i) for i in range(total_slices)]
        total_weight = sum(weights)
        slice_qtys = [max(order.lot_size, int(remaining * w / total_weight)) for w in weights]
        # 每个切片向下取整到整手
        slice_qtys = [(q // order.lot_size) * order.lot_size for q in slice_qtys]
        slice_qtys = [max(order.lot_size, q) for q in slice_qtys]

        # 修正总量误差
        diff = remaining - sum(slice_qtys)
        if slice_qtys:
            slice_qtys[0] += diff

        for slice_qty in slice_qtys:
            if order._stop_requested or order.filled_qty >= order.target_qty:
                break
            await order._pause_event.wait()
            if order._stop_requested:
                break

            actual_qty = min(slice_qty, order.target_qty - order.filled_qty)
            fill_price = await self._simulate_fill(order.symbol, actual_qty, order.side)
            order.filled_qty += actual_qty
            order.total_cost += fill_price * actual_qty

            order.message = f"VWAP 执行中，进度 {order.progress}%，均价 {order.avg_price}"
            await self._save_algo_state(order)
            await self._broadcast_update()

            if order.filled_qty >= order.target_qty:
                break

            await asyncio.sleep(30)

    async def _run_iceberg(self, order: AlgoOrder) -> None:
        """ICEBERG: 冰山委托 — 每次仅显示少量可见量，成交后自动补单"""
        # 可见量也要对齐到整手
        visible_qty = max(order.lot_size, order.iceberg_visible_qty)
        visible_qty = (visible_qty // order.lot_size) * order.lot_size

        while not order._stop_requested and order.filled_qty < order.target_qty:
            await order._pause_event.wait()
            if order._stop_requested:
                break

            current_visible = min(visible_qty, order.target_qty - order.filled_qty)
            # 最后一笔如果不足一手，且是剩余全部，则允许
            if current_visible < order.lot_size:
                if order.filled_qty + current_visible == order.target_qty:
                    pass  # 最后一笔，允许不足一手
                else:
                    current_visible = order.lot_size
            fill_price = await self._simulate_fill(order.symbol, current_visible, order.side)
            order.filled_qty += current_visible
            order.total_cost += fill_price * current_visible

            order.message = f"冰山委托: 已成交 {order.filled_qty}/{order.target_qty}，可见量 {current_visible}"
            await self._save_algo_state(order)
            await self._broadcast_update()

            if order.filled_qty >= order.target_qty:
                break

            # 冰山间隔: 15 秒 (比 TWAP 更频繁，因为每笔量小)
            await asyncio.sleep(15)

    async def _simulate_fill(self, symbol: str, qty: int, side: str) -> float:
        """
        根据交易模式执行成交:
        - SANDBOX: 模拟成交 (获取最新行情 ± 微小滑点)
        - LIVE: 通过 trade_handler 向 Futu 提交真实限价单
        """
        # 检查当前交易模式
        try:
            mode = await redis_client.get("quant:oms:trading_mode")
            if mode == "LIVE":
                return await self._execute_real_order(symbol, qty, side)
        except Exception:
            pass

        # SANDBOX 模式: 模拟成交
        try:
            from backend.services.futu_service import futu_service
            quote = await futu_service.get_quote(symbol)
            if quote and quote.get("status") == "success":
                # compress_quote_data 返回格式: last_price 在顶层
                last_price = quote.get("last_price", 0)
                if last_price > 0:
                    import random
                    slippage = random.uniform(0.0001, 0.0005)
                    if side == "BUY":
                        return last_price * (1 + slippage)
                    else:
                        return last_price * (1 - slippage)
        except Exception as e:
            logger.debug(f"[AlgoEngine] 行情获取失败 ({symbol}): {e}")

        return 100.0

    async def _execute_real_order(self, symbol: str, qty: int, side: str) -> float:
        """LIVE 模式: 通过 futu_service 提交真实限价单"""
        try:
            from futu import TrdMarket, TrdSide

            from backend.services.futu_service import futu_service

            logger.info(f"[AlgoEngine] _execute_real_order 入参: {symbol} qty={qty} side={side}")

            quote = await futu_service.get_quote(symbol)
            if quote.get("status") != "success":
                raise RuntimeError(f"无法获取 {symbol} 行情: {quote.get('message', '')}")
            # compress_quote_data 返回格式: last_price 在顶层
            last_price = quote.get("last_price", 0)
            if last_price <= 0:
                raise RuntimeError(f"{symbol} 价格无效: {last_price}")

            # 港股整手检查: 使用 _get_lot_size 获取
            lot_size = await _get_lot_size(symbol)
            logger.info(f"[AlgoEngine] 整手检查: lot_size={lot_size}, 原始 qty={qty}")
            if lot_size > 1:
                original_qty = qty
                qty = (qty // lot_size) * lot_size
                if qty <= 0:
                    raise RuntimeError(f"{symbol} 下单量 {original_qty} 不足 1 手 (lot_size={lot_size})")
                if qty != original_qty:
                    logger.info(f"[AlgoEngine] 港股整手对齐: {original_qty} → {qty} (lot_size={lot_size})")

            logger.info(f"[AlgoEngine] 最终下单: {symbol} qty={qty} price={last_price}")

            # 直接调用 futu_service.place_order
            trd_side = TrdSide.BUY if side == "BUY" else TrdSide.SELL
            market = TrdMarket.HK if symbol.upper().endswith(".HK") else TrdMarket.US
            result = await futu_service.place_order(symbol, qty, last_price, trd_side, market)

            if result.get("status") == "success" or result.get("order_id"):
                logger.info(f"[AlgoEngine] LIVE 下单成功: {side} {qty} {symbol} @ {last_price}")
                return last_price
            else:
                logger.error(f"[AlgoEngine] LIVE 下单失败: {result}")
                raise RuntimeError(f"下单失败: {result.get('message', result)}")
        except Exception as e:
            logger.error(f"[AlgoEngine] 真实下单异常 ({symbol}): {e}")
            raise

    # ── 内部: 状态持久化 (OMS-09) ────────────────────────────────────────

    async def _save_algo_state(self, order: AlgoOrder) -> None:
        """OMS-09: 将算法进度写入 Redis Hash"""
        try:
            data = json.dumps(order.to_api_dict())
            if order.status in ("RUNNING", "PAUSED"):
                await redis_client.hset(_ALGO_ACTIVE_KEY, order.algo_id, data)
            else:
                # 已完成/取消/错误 → 从活动表移除
                await redis_client.hdel(_ALGO_ACTIVE_KEY, order.algo_id)
        except Exception as e:
            logger.debug(f"[AlgoEngine] 状态写入失败: {e}")

    async def _archive_algo(self, order: AlgoOrder) -> None:
        """OMS-09: 归档已完成算法到 Redis List (最近 100 条)"""
        if order.status not in ("COMPLETED", "CANCELLED", "ERROR"):
            return
        try:
            data = json.dumps({
                **order.to_api_dict(),
                "completed_at": datetime.now().isoformat(),
            })
            await redis_client.lpush(_ALGO_HISTORY_KEY, data)
            await redis_client.ltrim(_ALGO_HISTORY_KEY, 0, 99)
            await redis_client.expire(_ALGO_HISTORY_KEY, 86400 * 7)  # 7 天 TTL
        except Exception as e:
            logger.debug(f"[AlgoEngine] 归档写入失败: {e}")

    async def _broadcast_update(self) -> None:
        """PubSub 广播算法列表变更"""
        try:
            orders = await self.get_all_algo_orders()
            await redis_client.publish(_ALGO_STREAM_CHANNEL, json.dumps(orders))
        except Exception as e:
            logger.debug(f"[AlgoEngine] 广播失败: {e}")

    # ── 启动恢复 ──────────────────────────────────────────────────────────

    async def restore_from_redis(self) -> int:
        """从 Redis 恢复之前运行中的算法订单"""
        try:
            active = await redis_client.hgetall(_ALGO_ACTIVE_KEY)
            if not active:
                return 0
            count = 0
            for algo_id, raw in active.items():
                try:
                    data = json.loads(raw)
                    if data.get("status") in ("RUNNING", "PAUSED"):
                        order = await self.start_algo(
                            algo_type=data["algo_type"],
                            symbol=data["symbol"],
                            side=data.get("side", "BUY"),
                            target_qty=data["target_qty"],
                            duration_minutes=60,
                        )
                        order.filled_qty = data.get("filled_qty", 0)
                        order.total_cost = float(data.get("avg_price", "0")) * order.filled_qty
                        if data.get("status") == "PAUSED":
                            await self.pause_algo(algo_id)
                        count += 1
                except Exception as e:
                    logger.warning(f"[AlgoEngine] 恢复 {algo_id} 失败: {e}")
            if count:
                logger.info(f"[AlgoEngine] 已从 Redis 恢复 {count} 个算法订单")
            return count
        except Exception as e:
            logger.warning(f"[AlgoEngine] 恢复失败: {e}")
            return 0

    async def shutdown(self) -> None:
        """优雅关停所有算法"""
        await self.cancel_all()
        logger.info("[AlgoEngine] 所有算法已关停")


# 导出全局单例
algo_engine = AlgoEngine()
