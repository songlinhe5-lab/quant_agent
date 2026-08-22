"""Futu worker — 物理解耦版（import _internal，无 backend 依赖）。

作为主节点 data_subservice 的唯一 Futu OpenD 长连接出口，由 main.py 在
DS_CAPABILITIES=futu 时拉起。主服务经 HTTP 调 /api/v1/data (source=futu) 分发到此。
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
        elif action == "TOP_BROKERS":
            return await futu_service.get_top_brokers(
                params.get("symbol"), days_before=int(params.get("days_before", 0))
            )
        elif action == "CAPITAL_FLOW":
            return await futu_service.get_capital_flow(
                params.get("symbol"), period_type=params.get("period_type", "INTRADAY")
            )
        elif action == "FUNDAMENTAL":
            return await futu_service.get_fundamental(params.get("symbol"))
        elif action == "FINANCIALS":
            return await futu_service.get_financials(
                params.get("symbol"),
                statement_type=params.get("statement_type"),
                financial_type=params.get("financial_type"),
                currency_code=params.get("currency_code"),
                num=int(params.get("num", 1)),
            )
        elif action == "VALUATION":
            return await futu_service.get_valuation(params.get("symbol"))
        elif action == "SHORT_SELLING":
            # F1 · 卖空数据：子模式 rank(卖空榜) / daily(每日卖空量)
            sub = (params.get("sub_action") or params.get("mode") or "rank").lower()
            if sub == "daily":
                return await futu_service.get_daily_short_volume(
                    params.get("symbol") or params.get("ticker"),
                    date=params.get("date"),
                )
            # 默认 rank（卖空成交榜）
            return await futu_service.get_short_selling_rank(
                params.get("symbol") or params.get("ticker"),
                market=params.get("market"),
                count=int(params.get("count", 10)),
            )
        elif action == "OPTION_STRATEGY":
            return await futu_service.get_option_strategy(
                params.get("symbol") or params.get("ticker"),
                strategy_type=params.get("strategy_type", "STRANGLE"),
                spread=int(params.get("spread", 5)),
            )
        elif action == "OPTION_VOLATILITY":
            return await futu_service.get_option_volatility(
                params.get("symbol") or params.get("ticker"),
            )
        elif action == "CAPITAL_DISTRIBUTION":
            # F4-1 主力筹码分层（8 档 in/out，支撑 G3）
            return await futu_service.get_capital_distribution(
                params.get("symbol") or params.get("ticker"),
            )
        elif action == "ANALYST_CONSENSUS":
            # F4-4 分析师共识（卖方观点，非事实）
            return await futu_service.get_research_analyst_consensus(
                params.get("symbol") or params.get("ticker"),
            )
        elif action == "FED_WATCH":
            # F4-2 FedWatch FOMC 隐含概率（市场级，无 code 参数）
            return await futu_service.get_fed_watch()
        elif action == "HEAT_MAP":
            # F4-3 板块热力图（需 market 参数）
            return await futu_service.get_heat_map(market=params.get("market", "HK"))
        elif action == "HK_SECTOR_FLOW":
            # F4-5 港股行业板块资金流聚合（板块资金流向面板）
            return await futu_service.get_hk_sector_flow()
        elif action == "RATING_SUMMARY":
            # P1.2 分析师评级明细（INSTITUTION/ANALYST）
            return await futu_service.get_research_rating_summary(
                params.get("symbol") or params.get("ticker"),
                rating_dimension_type=params.get("rating_dimension_type", "INSTITUTION"),
                uid=params.get("uid"),
                num=int(params.get("num", 10)) if params.get("num") else None,
            )
        elif action == "REVENUE_BREAKDOWN":
            # P1.3 主营构成（收入拆分）
            return await futu_service.get_financials_revenue_breakdown(
                params.get("symbol") or params.get("ticker"),
                financial_type=params.get("financial_type", "ANNUAL"),
                date=params.get("date"),
                currency_code=params.get("currency_code"),
            )
        elif action == "SHORT_INTEREST":
            # P1.4 累计卖空持仓（short interest）
            return await futu_service.get_short_interest(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "SHAREHOLDERS_OVERVIEW":
            return await futu_service.get_shareholders_overview(params.get("symbol") or params.get("ticker"))
        elif action == "SHAREHOLDERS_HOLDING_CHANGES":
            return await futu_service.get_shareholders_holding_changes(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "SHAREHOLDERS_INSTITUTIONAL":
            return await futu_service.get_shareholders_institutional(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "SHAREHOLDERS_HOLDER_DETAIL":
            return await futu_service.get_shareholders_holder_detail(
                params.get("symbol") or params.get("ticker"),
                request_type=params.get("request_type", "ALL"),
                num=int(params.get("num", 10)),
            )
        elif action == "INSIDER_HOLDER_LIST":
            return await futu_service.get_insider_holder_list(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "INSIDER_TRADE_LIST":
            return await futu_service.get_insider_trade_list(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "CORP_ACTIONS_DIVIDENDS":
            return await futu_service.get_corporate_actions_dividends(params.get("symbol") or params.get("ticker"))
        elif action == "CORP_ACTIONS_BUYBACKS":
            return await futu_service.get_corporate_actions_buybacks(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "CORP_ACTIONS_SPLITS":
            return await futu_service.get_corporate_actions_stock_splits(
                params.get("symbol") or params.get("ticker"),
                num=int(params.get("num", 10)),
            )
        elif action == "WARRANT_CHAIN":
            return await futu_service.get_warrant_chain(params.get("symbol"))
        elif action == "SNAPSHOT":
            return await futu_service.get_market_snapshots(params.get("symbols", []))
        elif action == "STOCK_BASICINFO":
            return await futu_service.get_stock_basicinfo(params.get("market", "HK"), params.get("sec_type", "STOCK"))
        elif action == "ACCOUNT_INFO":
            # DIST-23: OpenD 行情已 CONNECTED 但交易未解锁时, get_account_info 返回
            # {"error": "fetch_account_info failed: Conn", "locked": True}。
            # 此前此 error 会沿链路触发主服务 futu_master 全局熔断 → 误杀 QUOTE 行情。
            # 现约定: 交易未解锁属预期状态(非故障), 返回 success + 空账户数据 +
            # trade_unlocked:false, 让上层熔断隔离逻辑(router.py)无需兜底也能安全放行行情。
            info = await futu_service.get_account_info(params.get("market", "HK"))
            if isinstance(info, dict) and info.get("locked"):
                logger.warning(
                    "[Futu Worker] ACCOUNT_INFO: OpenD 交易连接未解锁(locked), "
                    "返回空账户数据, 不计入故障(不影响行情通道)"
                )
                return {
                    "status": "success",
                    "source": "futu",
                    "trade_unlocked": False,
                    "data": {
                        "accounts": [],
                        "total_assets": None,
                        "cash": None,
                        "market_value": None,
                        "note": "OpenD 交易连接未解锁, 账户数据不可用",
                    },
                }
            return info
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
        elif action == "EMERGENCY_LIQUIDATION":
            return await futu_service.emergency_liquidation(params.get("market", "HK"))
        # BE-ARCH-08c⑤: 前端 WS 订阅回传 — 主服务经 router 以 SUBSCRIBE/UNSUBSCRIBE 抵达,
        # 通知 OpenD 真正订阅/退订实时推送 (此前无此分支, 新标的只能等 10s 轮询碰巧触发)。
        elif action == "SUBSCRIBE":
            return await futu_service.subscribe_quote(params.get("symbol"))
        elif action == "UNSUBSCRIBE":
            return await futu_service.unsubscribe_quote(params.get("symbol"))
        elif action in ("COMPANY_NEWS", "STOCK_NEWS", "NEWS"):
            # 个股资讯（富途新闻/公告/评级），港股主数据源
            return await futu_service.get_search_news(
                params.get("symbol") or params.get("ticker"),
                max_count=int(params.get("limit", 10)),
            )
        elif action == "HEALTH":
            return {"available": futu_service.status == "CONNECTED", "source": "futu"}
        else:
            return {"error": f"未知 futu action: {action}"}
    except Exception as e:
        logger.error(f"❌ [Futu Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "futu"}
