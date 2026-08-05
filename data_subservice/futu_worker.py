"""Futu worker — 物理解耦版（import _internal，无 backend 依赖）。

作为主节点 data_subservice 的唯一 Futu OpenD 长连接出口，由 main.py 在
COLLECTOR_FUTU=true 时拉起。主服务经 HTTP 调 /api/v1/data (source=futu) 分发到此。
"""

from typing import Any, Dict

from futu import ModifyOrderOp, TrdMarket, TrdSide

from data_subservice._internal.logger import logger
from data_subservice.futu_src import futu_service


def _as_enum(enum_cls, value):
    """HTTP 传输的枚举 value (字符串/int) 还原为 futu enum 实例。"""
    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    # 先按 value 构造 (如 TrdSide("BUY") 或 TrdMarket("HK"))
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        pass
    # 再按成员名构造 (如 "BUY" / "HK")
    try:
        return enum_cls[value]
    except (KeyError, TypeError):
        return value


async def handle_futu(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 futu 数据源请求，路由到 futu_service。"""
    try:
        if action == "QUOTE":
            return await futu_service.get_quote(params.get("symbol"))
        elif action == "HISTORY":
            return await futu_service.get_history(
                params.get("symbol"),
                ktype=params.get("ktype", "K_DAY"),
                num=params.get("num", 60),
            )
        elif action == "ORDER_BOOK":
            return await futu_service.get_order_book(params.get("symbol"))
        elif action == "OPTION_CHAIN":
            return await futu_service.get_option_chain(
                params.get("symbol"), expiration_date=params.get("expiration_date", "")
            )
        elif action == "FUND_FLOW":
            return await futu_service.get_fund_flow(params.get("symbol"))
        elif action == "FUNDAMENTAL":
            return await futu_service.get_fundamental(params.get("symbol"))
        elif action == "WARRANT_CHAIN":
            return await futu_service.get_warrant_chain(params.get("symbol"))
        elif action == "SNAPSHOT":
            return await futu_service.get_market_snapshots(params.get("symbols", []))
        elif action == "STOCK_BASICINFO":
            return await futu_service.get_stock_basicinfo(params.get("market", "HK"), params.get("sec_type", "STOCK"))
        elif action == "ACCOUNT_INFO":
            return await futu_service.get_account_info(params.get("market", "HK"))
        elif action == "PLACE_ORDER":
            return await futu_service.place_order(
                ticker=params.get("ticker"),
                qty=params.get("qty", 0),
                price=params.get("price", 0.0),
                trd_side=_as_enum(TrdSide, params.get("trd_side")),
                market=_as_enum(TrdMarket, params.get("market")),
            )
        elif action == "SCREEN_STOCKS":
            return await futu_service.screen_stocks(
                market=params.get("market", "HK"),
                filters=params.get("filters", []),
            )
        elif action == "MODIFY_ORDER":
            return await futu_service.modify_order(
                order_id=params.get("order_id"),
                op=_as_enum(ModifyOrderOp, params.get("op")),
                market=_as_enum(TrdMarket, params.get("market")),
            )
        elif action == "QUERY_ORDER":
            return await futu_service.query_order(
                order_id=params.get("order_id"),
                market=_as_enum(TrdMarket, params.get("market")),
            )
        elif action == "HEALTH":
            return {"available": futu_service.status == "CONNECTED", "source": "futu"}
        else:
            return {"error": f"未知 futu action: {action}"}
    except Exception as e:
        logger.error(f"❌ [Futu Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "futu"}
