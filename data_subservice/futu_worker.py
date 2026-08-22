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
        elif action == "OPTION_STRATEGY_ANALYSIS":
            # P0.2 期权损益分析（盈亏平衡点/最大盈亏/Greeks 敞口）
            return await futu_service.get_option_strategy_analysis(params.get("legs"))
        elif action == "OPTION_QUOTE":
            # P0.2 期权快照（组合腿实时行情 + Greeks）
            return await futu_service.get_option_quote(params.get("legs"))
        elif action == "OPTION_UNDERLYING_HIS_VOL":
            # P0.5.2 标的已实现波动率 HV（时间序列）
            return await futu_service.get_option_underlying_his_volatility(
                params.get("symbol") or params.get("ticker"),
                begin_time=params.get("begin_time"),
                end_time=params.get("end_time"),
            )
        elif action == "OPTION_UNDERLYING_OVERVIEW":
            # P0.5.2 标的期权总览（IV/IV_RANK/HV 多周期）
            return await futu_service.get_option_underlying_overview(params.get("symbol") or params.get("ticker"))
        elif action == "OPTION_MARKET_STATISTIC":
            # P0.5.3 期权市场 Put/Call 比
            return await futu_service.get_option_market_statistic(
                option_market=params.get("option_market", "US_SECURITY"),
                data_type=params.get("data_type", "VOLUME"),
                begin_time=params.get("begin_time"),
                end_time=params.get("end_time"),
            )
        elif action == "OPTION_ZERO_DTE_SCREENER":
            # P0.5.4 0DTE 末日期权筛选器
            return await futu_service.get_option_zero_dte_screener(
                market=params.get("market", "US_SECURITY"),
                sort_type=params.get("sort_type"),
                is_asc=params.get("is_asc"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "OPTION_ZERO_DTE_CONTRACT":
            # P0.5.4 0DTE 合约明细
            return await futu_service.get_option_zero_dte_contract(
                params.get("owner"),
                params.get("chain_info"),
                strike_date_timestamp=params.get("strike_date_timestamp"),
                sort_type=params.get("sort_type"),
                is_asc=params.get("is_asc"),
            )
        elif action == "OPTION_EARNINGS_SCREENER":
            # P0.5.5 财报期权筛选器
            return await futu_service.get_option_earnings_screener(
                market=params.get("market", "US_SECURITY"),
                sort_type=params.get("sort_type"),
                is_asc=params.get("is_asc"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "OPTION_SELLER_SCREENER":
            # P0.5.6 卖方策略筛选器
            return await futu_service.get_option_seller_screener(
                market=params.get("market", "US_SECURITY"),
                seller_type=params.get("seller_type", "COVERED_CALL"),
                sort_type=params.get("sort_type"),
                is_asc=params.get("is_asc"),
            )
        elif action == "OPTION_EXERCISE_PROBABILITY":
            # P0.5.7 行权概率
            return await futu_service.get_option_exercise_probability(params.get("symbol") or params.get("ticker"))
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
        elif action == "FED_WATCH_DOT_PLOT":
            # P1.8 FedWatch 点阵图（FOMC 委员利率预测散点）
            return await futu_service.get_fed_watch_dot_plot()
        elif action == "SEARCH_QUOTE":
            # P1.2 行情搜索（关键词→标的，补「名称→代码」盲区）
            return await futu_service.get_search_quote(
                params.get("keyword") or params.get("symbol") or params.get("query") or "",
                max_count=int(params.get("max_count", 10)),
            )
        elif action == "INSTITUTION_LIST":
            # P2.2 机构列表（13F 机构，返回 institution_id）
            return await futu_service.get_institution_list(
                market=params.get("market", "US"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
                name_part=params.get("name_part"),
            )
        elif action == "INSTITUTION_HOLDING_LIST":
            # P2.2 机构持仓明细（13F 聪明钱核心信号）
            return await futu_service.get_institution_holding_list(
                institution_id=params.get("institution_id"),
                market=params.get("market", "US"),
                change_type=params.get("change_type"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "INSTITUTION_HOLDING_CHANGE":
            # P2.2 机构增减持明细
            return await futu_service.get_institution_holding_change(
                institution_id=params.get("institution_id"),
                market=params.get("market", "US"),
                change_type=params.get("change_type"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "INSTITUTION_DISTRIBUTION":
            # P2.2 机构行业分布
            return await futu_service.get_institution_distribution(
                institution_id=params.get("institution_id"),
                market=params.get("market", "US"),
            )
        elif action == "INSTITUTION_PROFILE":
            # P2.2 机构画像
            return await futu_service.get_institution_profile(
                institution_id=params.get("institution_id"),
                market=params.get("market", "US"),
            )
        elif action == "ARK_FUND_HOLDING":
            # P2.2 ARK 基金持仓
            return await futu_service.get_ark_fund_holding(
                holding_type=params.get("holding_type", "POSITION"),
                cycle_type=params.get("cycle_type", "ONE_DAY"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "ARK_ACTIVE_TRANSACTION":
            # P2.2 ARK 活跃交易（每日买卖明细）
            return await futu_service.get_ark_active_transaction(
                holding_type=params.get("holding_type", "INCREASE"),
                cycle_type=params.get("cycle_type", "ONE_DAY"),
                count=int(params.get("count", 20)),
                page=int(params.get("page", 1)),
            )
        elif action == "REHAB":
            # G8 复权因子（回测/技术指标地基）
            return await futu_service.get_rehab(params.get("symbol") or params.get("ticker"))
        elif action == "TRADING_DAYS":
            # G8 交易日历（T-1 语义/K线对齐/是否交易日判定）
            return await futu_service.get_trading_days(
                market=params.get("market", "HK"),
                start=params.get("start"),
                end=params.get("end"),
                ticker=params.get("ticker"),
            )
        elif action == "KL_QUOTA":
            # G8 历史 K 线额度（批量拉取前查询）
            return await futu_service.get_history_kl_quota(get_detail=bool(params.get("get_detail", True)))
        elif action == "MARKET_STATE":
            # G8 市场状态（区分盘后正常空 vs 故障空）
            return await futu_service.get_market_state(params.get("codes") or params.get("symbol"))
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
        elif action == "PLACE_COMBO_ORDER":
            # P1 组合期权下单（骨架，默认 SIMULATE；REAL 需 REAL_TRADE_EXECUTE + force_real）
            return await futu_service.place_combo_order(
                combo_legs=params.get("combo_legs"),
                price=params.get("price", 0.0),
                qty=params.get("qty", 0),
                market=_as_enum(TrdMarket, params.get("market")),
                order_type=params.get("order_type", "NORMAL"),
                force_real=bool(params.get("force_real", False)),
                remark=params.get("remark", ""),
            )
        elif action == "COMBO_TRADINGINFO_QUERY":
            # P1 组合订单交易信息预检（默认 SIMULATE）
            return await futu_service.comboorder_tradinginfo_query(
                combo_legs=params.get("combo_legs"),
                price=params.get("price", 0.0),
                qty=params.get("qty", 0),
                market=_as_enum(TrdMarket, params.get("market")),
                order_type=params.get("order_type", "NORMAL"),
                order_id=params.get("order_id"),
                force_real=bool(params.get("force_real", False)),
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
