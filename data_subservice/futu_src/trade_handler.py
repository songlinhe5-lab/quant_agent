"""
Futu 交易服务模块
负责下单、改单、撤单、订单查询、账户信息等功能
"""

import asyncio
import os
from typing import Any, Dict, Optional

import pandas as pd
from futu import RET_OK, ModifyOrderOp, OrderType, TrdEnv, TrdMarket, TrdSide

from data_subservice._internal.logger import logger
from data_subservice._internal.retry_utils import with_global_retry

from ._compat import safe_float


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
            logger.info(f"[TradeHandler] 下单结果通知: {notify_msg}")

        return {
            "status": "success",
            "order_id": order_id,
            "order_status": order_status,
            "dealt_avg_price": dealt_avg_price,
            "message": f"成功获取订单状态：{order_status}",
        }

    @with_global_retry
    async def emergency_liquidation(self, market: str = "HK") -> Dict[str, Any]:
        """Kill Switch: 物理撤单 + 市价平仓 (模拟盘)。

        BE-ARCH-07c: 主服务不再本地持有 trade_ctx, 该逻辑下沉至子服务 futu worker。
        复用 place_order/modify_order 的直连通道完成撤单与市价平仓。
        """
        market_map = {
            "HK": TrdMarket.HK,
            "US": TrdMarket.US,
            "CN": TrdMarket.CN,
            "SH": TrdMarket.CN,
            "SZ": TrdMarket.CN,
            "HK_CCASS": TrdMarket.HKCC,
        }
        trd_market = market_map.get(market.upper(), TrdMarket.HK)

        # 未连接时直接返回错误, 避免触发 Futu SDK 后台线程无限重试
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "ok": False, "reason": "futu_opend_not_connected"}

        trd_ctx = self.conn_mgr.get_trade_context(market=trd_market, trd_env=TrdEnv.SIMULATE)
        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        cancelled = 0
        closed = 0
        # 1) 撤单
        ret, order_data = await asyncio.to_thread(
            trd_ctx.order_list_query,
            status_filter_list=["SUBMITTED", "WAITING_SUBMIT"],
            trd_env=TrdEnv.SIMULATE,
        )
        if ret == RET_OK and isinstance(order_data, pd.DataFrame) and not order_data.empty:
            for _, row in order_data.iterrows():
                c_ret, _ = await asyncio.to_thread(
                    trd_ctx.modify_order,
                    ModifyOrderOp.CANCEL,
                    str(row["order_id"]),
                    0,
                    0.0,
                    trd_env=row.get("trd_env", TrdEnv.SIMULATE),
                )
                if c_ret == RET_OK:
                    cancelled += 1

        # 2) 市价平仓
        ret_pos, pos_data = await asyncio.to_thread(trd_ctx.position_list_query, trd_env=TrdEnv.SIMULATE)
        if ret_pos == RET_OK and isinstance(pos_data, pd.DataFrame) and not pos_data.empty:
            for _, row in pos_data.iterrows():
                qty = float(row.get("qty", 0))
                if qty == 0:
                    continue
                pos_side = row.get("position_side", "LONG")
                trd_side = TrdSide.SELL if pos_side == "LONG" else TrdSide.BUY
                _, _ = await asyncio.to_thread(
                    trd_ctx.place_order,
                    price=1.0,
                    qty=abs(qty),
                    code=row["code"],
                    trd_side=trd_side,
                    order_type=OrderType.MARKET,
                    trd_env=row.get("trd_env", TrdEnv.SIMULATE),
                )
                closed += 1

        return {
            "status": "success",
            "ok": True,
            "reason": None,
            "cancelled": cancelled,
            "closed": closed,
            "message": f"Kill Switch 执行完毕: 撤单 {cancelled} 笔, 平仓 {closed} 个标的。",
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
                # DIST-23(2026-08-11 实战): 解锁失败(OpenD 交易未解锁)属预期状态,
                # 标记 locked=True 让上层(futu_worker)返回 success+空数据, 不误伤行情通道。
                unlocked = await self.conn_mgr.unlock_trade_if_needed(trd_ctx)
                if not unlocked:
                    return {
                        "status": "error",
                        "locked": True,
                        "message": "OpenD 交易连接未解锁(需在 OpenD 界面手动解锁或配置 FUTU_TRD_UNLOCK_PWD)",
                    }

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

    # ── P1 组合期权交易（预留骨架，AGENTS.md §6 沙箱约束）──────────────────
    @staticmethod
    def _build_combo_legs(legs: Any) -> tuple:
        """把 [{code, trd_side, qty_ratio}] 转成 futu ComboLeg 对象列表。

        ComboLeg 字段: code / trd_side / qty_ratio / position_id / pred_side。
        解析失败返回 (None, err_msg)。
        """
        from futu import ComboLeg, TrdSide

        if not isinstance(legs, (list, tuple)) or len(legs) == 0:
            return None, "combo_legs 须为非空 [{code, trd_side, qty_ratio}] 列表"
        built = []
        for leg in legs:
            if not isinstance(leg, dict) or not leg.get("code"):
                return None, f"非法组合腿: {leg}"
            o = ComboLeg()
            o.code = str(leg["code"])
            side_str = str(leg.get("trd_side", "BUY")).upper()
            o.trd_side = TrdSide.BUY if side_str in ("BUY", "1") else TrdSide.SELL
            o.qty_ratio = int(leg.get("qty_ratio", 1))
            o.position_id = leg.get("position_id") or ""
            o.pred_side = leg.get("pred_side") or ""
            built.append(o)
        return built, None

    def _resolve_trd_env(self, force_real: bool = False) -> TrdEnv:
        """沙箱约束：默认 SIMULATE，仅 REAL_TRADE_EXECUTE 标志 + force_real 才 REAL。

        AGENTS.md §6 红线：交易默认纯模拟推演；实盘需环境标志 REAL_TRADE_EXECUTE 且调用方
        二次确认(force_real=True)。两者缺一即回落 SIMULATE。
        """
        allow_real = os.getenv("REAL_TRADE_EXECUTE", "0") == "1"
        if allow_real and force_real:
            return TrdEnv.REAL
        return TrdEnv.SIMULATE

    @with_global_retry
    async def place_combo_order(
        self,
        combo_legs: Any,
        price: float,
        qty: int,
        market: TrdMarket,
        order_type: str = "NORMAL",
        force_real: bool = False,
        remark: str = "",
    ) -> Dict[str, Any]:
        """P1 组合期权下单（骨架，预留 OMS 实装位）。

        ⚠️ P1.3：OMS 实盘工具尚未实装，本方法仅走 SIMULATE 沙箱推演；
        当 REAL_TRADE_EXECUTE=1 且 force_real=True 时才触达 REAL，且仍建议先二次确认。
        组合腿解析失败 / 未连交易网关 / SDK 不支持均降级返回，绝不静默下单。
        """
        from futu import OrderType, TrdEnv

        built, err = self._build_combo_legs(combo_legs)
        if err:
            return {"status": "error", "message": err}
        trd_env = self._resolve_trd_env(force_real=force_real)
        trd_ctx = self.conn_mgr.get_trade_context(market=market, trd_env=trd_env)
        if trd_ctx is None:
            return {"status": "error", "message": "Futu OpenD 交易网关未连接"}

        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        ot = OrderType.NORMAL if str(order_type).upper() in ("NORMAL", "LIMIT") else OrderType.MARKET
        try:
            ret, data = await asyncio.to_thread(
                trd_ctx.place_combo_order,
                combo_leg_list=built,
                price=float(price),
                qty=int(qty),
                order_type=ot,
                trd_env=trd_env,
                remark=remark,
            )
            if ret != RET_OK:
                return {"status": "error", "message": f"组合下单失败: {data}"}
            oid = str(data["order_id"].iloc[0]) if isinstance(data, pd.DataFrame) and not data.empty else str(data)
            env_label = "REAL" if trd_env == TrdEnv.REAL else "SIMULATE"
            return {
                "status": "success",
                "message": f"组合订单已提交({env_label})！订单号: {oid}",
                "order_id": oid,
                "environment": env_label,
                "note": "OMS 组合实盘工具尚未实装，当前为骨架预留；SIMULATE 盘可推演组合成交",
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ place_combo_order 失败: %s", e)
            return {"status": "error", "message": f"组合下单异常: {str(e)}"}

    @with_global_retry
    async def comboorder_tradinginfo_query(
        self,
        combo_legs: Any,
        price: float,
        qty: int,
        market: TrdMarket,
        order_type: str = "NORMAL",
        order_id: Optional[str] = None,
        force_real: bool = False,
    ) -> Dict[str, Any]:
        """P1 组合订单交易信息查询（组合下单前可用性/购买力预检，骨架）。

        仅查询，不触达成交；默认 SIMULATE，REAL 需 REAL_TRADE_EXECUTE + force_real。
        """
        from futu import OrderType, TrdEnv

        built, err = self._build_combo_legs(combo_legs)
        if err:
            return {"status": "error", "message": err}
        trd_env = self._resolve_trd_env(force_real=force_real)
        trd_ctx = self.conn_mgr.get_trade_context(market=market, trd_env=trd_env)
        if trd_ctx is None:
            return {"status": "error", "message": "Futu OpenD 交易网关未连接"}

        await self.conn_mgr.unlock_trade_if_needed(trd_ctx)

        ot = OrderType.NORMAL if str(order_type).upper() in ("NORMAL", "LIMIT") else OrderType.MARKET
        try:
            ret, data = await asyncio.to_thread(
                trd_ctx.comboorder_tradinginfo_query,
                combo_leg_list=built,
                price=float(price),
                qty=int(qty),
                order_type=ot,
                order_id=order_id,
                trd_env=trd_env,
            )
            if ret != RET_OK:
                return {"status": "error", "message": f"组合订单信息查询失败: {data}"}
            env_label = "REAL" if trd_env == TrdEnv.REAL else "SIMULATE"
            rows = data.to_dict("records") if isinstance(data, pd.DataFrame) else data
            return {
                "status": "success",
                "message": f"组合订单信息已获取({env_label})",
                "environment": env_label,
                "count": len(rows) if isinstance(rows, list) else 0,
                "data": rows,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ comboorder_tradinginfo_query 失败: %s", e)
            return {"status": "error", "message": f"组合订单信息查询异常: {str(e)}"}
