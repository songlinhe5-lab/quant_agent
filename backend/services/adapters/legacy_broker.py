"""
Legacy Broker Gateway（BE-ARCH-01）

封装 Futu 交易上下文与 Kill Switch 物理清仓；Router 禁止 `from futu import …`。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("BrokerGateway")


class BrokerGateway:
    """实现 BrokerPort 表面 + Kill Switch。"""

    def __init__(self) -> None:
        from backend.services.futu_service import futu_service

        self._futu = futu_service

    def _resolve_market(self, ticker: Optional[str], market: Optional[str]):
        from futu import TrdMarket

        if market is not None:
            if isinstance(market, TrdMarket):
                return market
            m = str(market).upper()
            return TrdMarket.HK if m == "HK" else TrdMarket.US
        if ticker and "HK" in ticker.upper():
            return TrdMarket.HK
        return TrdMarket.US

    async def place_order(
        self,
        ticker: str,
        qty: int,
        price: float,
        side: str,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        from futu import TrdSide

        trd_market = self._resolve_market(ticker, market)
        trd_side = TrdSide.BUY if side.upper() == "BUY" else TrdSide.SELL
        return await self._futu.place_order(ticker, qty, price, trd_side, trd_market)

    async def cancel_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]:
        from futu import ModifyOrderOp

        trd_market = self._resolve_market(None, market)
        return await self._futu.modify_order(order_id, ModifyOrderOp.CANCEL, trd_market)

    async def query_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]:
        trd_market = self._resolve_market(None, market)
        return await self._futu.query_order(order_id, trd_market)

    async def get_account_info(self, market: Optional[str] = None) -> dict[str, Any]:
        if market is None:
            return await self._futu.get_account_info()
        return await self._futu.get_account_info(market)

    def has_trade_ctx(self) -> bool:
        return getattr(self._futu, "trade_ctx", None) is not None

    async def execute_emergency_liquidation(self) -> dict[str, Any]:
        """
        Kill Switch 物理撤单+市价平仓。
        返回 {"ok": bool, "reason": str|None}；无 trade_ctx 时 ok=False。
        """
        from futu import ModifyOrderOp, OrderType, TrdSide

        ctx = getattr(self._futu, "trade_ctx", None)
        if not ctx:
            logger.error("🚨 [KILL SWITCH] 未检测到有效的底层交易网关上下文 (trade_ctx)")
            return {"ok": False, "reason": "no_trade_ctx"}

        def cancel_all_orders() -> None:
            ret, data = ctx.order_list_query(status_filter_list=["SUBMITTED", "WAITING_SUBMIT"])
            if ret == 0 and not data.empty:
                for _, row in data.iterrows():
                    ctx.modify_order(
                        ModifyOrderOp.CANCEL,
                        row["order_id"],
                        0,
                        0,
                        trd_env=row["trd_env"],
                    )
                    logger.warning(f"🛑 [KILL SWITCH] 撤单指令已发送: {row['order_id']}")

        def close_all_positions() -> None:
            ret_pos, pos_data = ctx.position_list_query()
            if ret_pos == 0 and not pos_data.empty:
                for _, row in pos_data.iterrows():
                    qty = float(row.get("qty", 0))
                    if qty == 0:
                        continue
                    symbol = row["code"]
                    pos_side = row.get("position_side", "LONG")
                    trd_side = TrdSide.SELL if pos_side == "LONG" else TrdSide.BUY
                    logger.warning(f"💥 [KILL SWITCH] 正在市价平仓: {symbol} 数量 {abs(qty)} 方向 {trd_side}")
                    ctx.place_order(
                        price=0.0,
                        qty=abs(qty),
                        code=symbol,
                        trd_side=trd_side,
                        order_type=OrderType.MARKET,
                        trd_env=row["trd_env"],
                    )

        await asyncio.to_thread(cancel_all_orders)
        await asyncio.sleep(0.5)
        await asyncio.to_thread(close_all_positions)
        logger.warning("✅ [KILL SWITCH] 物理清仓程序全部下达完毕。")
        return {"ok": True, "reason": None}


broker_gateway = BrokerGateway()
