"""
Futu 交易服务模块
负责下单、改单、撤单、订单查询、账户信息等功能
"""

import asyncio
import os
from typing import Any, Dict

import pandas as pd
from futu import RET_OK, ModifyOrderOp, OrderType, TrdEnv, TrdMarket, TrdSide

from backend.core.retry_utils import with_global_retry
from backend.core.utils import safe_float
from backend.services.notification_service import notification_service


class TradeHandler:
    """交易服务处理器"""

    def __init__(self, connection_manager):
        self.conn_mgr = connection_manager

    @with_global_retry
    async def place_order(
        self,
        ticker: str,
        qty: int,
        price: float,
        trd_side: TrdSide,
        market: TrdMarket,
        format_ticker_func=None,
    ) -> Dict[str, Any]:
        """下单（模拟盘）"""
        if format_ticker_func is None:
            from .utils import format_ticker

            format_ticker_func = format_ticker

        trd_ctx = self.conn_mgr.get_trade_context(market=market, trd_env=TrdEnv.SIMULATE)  # noqa: E501
        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        order_type = OrderType.NORMAL if price > 0 else OrderType.MARKET
        ret, data = await asyncio.to_thread(
            trd_ctx.place_order,
            price=price if price > 0 else 1.0,
            qty=qty,
            code=format_ticker_func(ticker),
            trd_side=trd_side,
            order_type=order_type,
            trd_env=TrdEnv.SIMULATE,
        )

        if ret != RET_OK:
            return {"status": "error", "message": f"下单失败: {data}"}

        oid = str(data["order_id"].iloc[0]) if isinstance(data, pd.DataFrame) and not data.empty else str(data)  # noqa: E501
        return {
            "status": "success",
            "message": f"委托已提交(模拟盘)！订单号: {oid}",
            "order_id": oid,
        }  # noqa: E501

    @with_global_retry
    async def modify_order(self, order_id: str, op: ModifyOrderOp, market: TrdMarket) -> Dict[str, Any]:
        """改单/撤单（模拟盘）"""
        trd_ctx = self.conn_mgr.get_trade_context(market=market, trd_env=TrdEnv.SIMULATE)  # noqa: E501
        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        ret, data = await asyncio.to_thread(trd_ctx.modify_order, op, str(order_id), 0, 0.0, trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            return {"status": "error", "message": f"撤单失败: {data}"}
        return {
            "status": "success",
            "message": f"撤单指令已提交(模拟盘)！被撤单号: {order_id}",
        }  # noqa: E501

    @with_global_retry
    async def query_order(self, order_id: str, market: TrdMarket) -> Dict[str, Any]:
        """查询订单状态"""
        trd_ctx = self.conn_mgr.get_trade_context(market=market, trd_env=TrdEnv.SIMULATE)  # noqa: E501
        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        ret, data = await asyncio.to_thread(trd_ctx.order_list_query, order_id=str(order_id), trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            return {"status": "error", "message": f"未找到指定订单: {order_id}"}

        row = data.iloc[0]
        order_status = str(row.get("order_status", "UNKNOWN"))
        dealt_avg_price = float(row.get("dealt_avg_price", 0.0))

        if "FILLED" in order_status.upper() or "CANCELLED" in order_status.upper():
            notify_msg = f"✅ 您的委托状态更新！\n标的: {row.get('code', '')}\n状态: {order_status}"  # noqa: E501
            asyncio.create_task(notification_service.send_alert(notify_msg))

        return {
            "status": "success",
            "order_id": order_id,
            "order_status": order_status,
            "dealt_avg_price": dealt_avg_price,
            "message": f"成功获取订单状态：{order_status}",
        }

    @with_global_retry
    async def get_account_info(self, market: str = "HK") -> Dict[str, Any]:
        """获取账户信息和持仓"""
        env_str = os.getenv("FUTU_TRD_ENV", "SIMULATE").upper()
        trd_env = TrdEnv.REAL if env_str == "REAL" else TrdEnv.SIMULATE
        market_map = {
            "HK": TrdMarket.HK,
            "US": TrdMarket.US,
            "CN": TrdMarket.CN,
            "SH": TrdMarket.CN,
            "SZ": TrdMarket.CN,
            "HK_CCASS": TrdMarket.HKCC,
        }
        trd_market = market_map.get(market.upper(), TrdMarket.HK)

        # 未连接时直接返回错误，避免触发 Futu SDK 后台线程无限重试
        if self.conn_mgr.status != "CONNECTED":
            if os.getenv("QUANT_ENV") == "development":
                from .mock_provider import MockProvider
                return MockProvider.mock_account_info(market, env_str)
            return {"status": "error", "message": f"Futu OpenD 未连接 (status={self.conn_mgr.status})"}

        trd_ctx = self.conn_mgr.get_trade_context(market=trd_market, trd_env=trd_env)
        try:
            if trd_env == TrdEnv.REAL:
                await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

            ret, data = await asyncio.to_thread(trd_ctx.accinfo_query, trd_env=trd_env)
            if ret != RET_OK:
                return {"status": "error", "message": f"账户信息获取失败: {data}"}

            if isinstance(data, pd.DataFrame) and not data.empty:
                row = data.iloc[0]
                positions = []
                ret_pos, data_pos = await asyncio.to_thread(trd_ctx.position_list_query, trd_env=trd_env)
                if ret_pos == RET_OK and isinstance(data_pos, pd.DataFrame) and not data_pos.empty:  # noqa: E501
                    display_cols = [
                        "code",
                        "stock_name",
                        "position_side",
                        "qty",
                        "can_sell_qty",
                        "cost_price",
                        "market_val",
                        "pl_val",
                        "pl_ratio",
                    ]
                    positions = data_pos[[col for col in display_cols if col in data_pos.columns]].to_dict(
                        orient="records"
                    )

                return {
                    "status": "success",
                    "environment": "REAL" if trd_env == TrdEnv.REAL else "SIMULATE",
                    "market": market.upper(),
                    "total_assets": safe_float(row.get("total_assets", 0)),
                    "cash": safe_float(row.get("cash", 0)),
                    "power": safe_float(row.get("power", 0)),
                    "market_val": safe_float(row.get("market_val", 0)),
                    "currency": row.get("currency", "HKD"),
                    "positions": positions,
                    "message": f"成功获取 {env_str} 账户信息与持仓列表。",
                }
            return {"status": "error", "message": "账户数据为空"}
        except Exception as e:
            return {"status": "error", "message": f"API 异常: {str(e)}"}
