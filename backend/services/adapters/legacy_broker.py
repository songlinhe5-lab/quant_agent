"""
Legacy Broker Gateway（BE-ARCH-01）

封装 Futu 交易上下文与 Kill Switch 物理清仓；Router 禁止 `from futu import …`。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services.datasource.router import data_source_router

logger = logging.getLogger("BrokerGateway")


class BrokerGateway:
    """实现 BrokerPort 表面 + Kill Switch。"""

    def __init__(self) -> None:
        from backend.services.futu import futu_service

        self._futu = futu_service

    def _resolve_market(self, ticker: Optional[str], market: Optional[str]):
        from backend.services.futu.enums import TrdMarket

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
        from backend.services.futu.enums import TrdSide

        trd_market = self._resolve_market(ticker, market)
        trd_side = TrdSide.BUY if side.upper() == "BUY" else TrdSide.SELL
        return await data_source_router.fetch_futu(
            "PLACE_ORDER",
            ticker=ticker,
            qty=qty,
            price=price,
            trd_side=trd_side.value,
            market=trd_market.value,
        )

    async def cancel_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]:
        from backend.services.futu.enums import ModifyOrderOp

        trd_market = self._resolve_market(None, market)
        return await data_source_router.fetch_futu(
            "MODIFY_ORDER",
            order_id=order_id,
            op=ModifyOrderOp.CANCEL.value,
            market=trd_market.value,
        )

    async def query_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]:
        trd_market = self._resolve_market(None, market)
        return await data_source_router.fetch_futu("QUERY_ORDER", order_id=order_id, market=trd_market.value)

    async def get_account_info(self, market: Optional[str] = None) -> dict[str, Any]:
        return await data_source_router.fetch_futu("ACCOUNT_INFO", market=market or "HK")

    def has_trade_ctx(self) -> bool:
        """BE-ARCH-07c: 主服务不再本地持有 trade_ctx, 改为远程 futu 可达性检查。"""
        from backend.services.datasource.router import data_source_router

        try:
            res = data_source_router.health_check("futu")
            return bool(res.get("available")) if isinstance(res, dict) else False
        except Exception:
            return False

    async def execute_emergency_liquidation(self) -> dict[str, Any]:
        """
        Kill Switch 物理撤单+市价平仓。
        返回 {"ok": bool, "reason": str|None}。

        BE-ARCH-07c: 主服务不再本地持有 trade_ctx 直连, 改经 DataSourceRouter
        HTTP 代理调用子服务 futu worker 的 EMERGENCY_LIQUIDATION action。
        """
        from backend.services.datasource.router import data_source_router

        res = await data_source_router.fetch_futu("EMERGENCY_LIQUIDATION", market="HK")
        if isinstance(res, dict) and res.get("status") == "error":
            logger.error(f"🚨 [KILL SWITCH] 远程清仓失败: {res.get('message')}")
            return {"ok": False, "reason": res.get("message", "remote_error")}
        if isinstance(res, dict) and res.get("ok") is True:
            logger.warning(f"✅ [KILL SWITCH] 远程清仓执行完毕: {res.get('message')}")
            return {"ok": True, "reason": None}
        # 结构异常兜底
        logger.error(f"🚨 [KILL SWITCH] 远程清仓返回异常: {res}")
        return {"ok": False, "reason": "unexpected_remote_response"}


broker_gateway = BrokerGateway()
