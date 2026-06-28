"""
Futu 选股服务模块
负责条件选股、市场快照、股票基本信息等功能
"""

import asyncio
from typing import Any, Dict, List, Optional

import pandas as pd
from futu import RET_OK

from backend.core.retry_utils import with_global_retry


# ─── Futu V2 选股接口支持检测 ───────────────────────────────────
# 在模块加载时尝试导入 V2 选股相关常量，若失败则标记不支持
_FUTU_V2_SUPPORT = False
StockScreenRequest = None
SimpleField = None
SimpleProperty = None
BasicProperty = None
FinancialProperty = None
CumulativeProperty = None
FeaturedProperty = None
Indicator = None
KlineShapeProperty = None
OptionProperty = None
Pattern = None
Position = None
BrokerProperty = None
ScrMarket = None
ScrSortDir = None
Term = None

try:
    from futu import StockScreenRequest
    from futu.quote.stock_screen_const import (  # noqa: F401
        BasicProperty,
        BrokerProperty,
        CumulativeProperty,
        FeaturedProperty,
        FinancialProperty,
        Indicator,
        KlineShapeProperty,
        OptionProperty,
        Pattern,
        Position,
        ScrMarket,
        ScrSortDir,
        SimpleField,
        SimpleProperty,
        Term,
    )

    _FUTU_V2_SUPPORT = True
except ImportError:
    pass  # V2 选股接口不可用，screen_stocks 会返回错误提示


class ScreenerHandler:
    """选股服务处理器"""

    def __init__(self, connection_manager):
        self.conn_mgr = connection_manager
        self.screen_lock = None

    @with_global_retry
    async def get_market_snapshots(self, tickers: List[str]) -> Dict[str, Any]:
        """批量获取快照，极速补充市值、价格、涨跌幅等缺失维度"""
        if self.conn_mgr.status != "CONNECTED" or not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        all_data = []
        # 富途快照每次最多支持 400 只股票并发查询
        for i in range(0, len(tickers), 400):
            batch = tickers[i : i + 400]
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_market_snapshot, batch)
            if ret == RET_OK and isinstance(data, pd.DataFrame) and not data.empty:
                all_data.append(data)
            await asyncio.sleep(0.1)

        if not all_data:
            return {"status": "error", "message": "获取快照失败"}

        df = pd.concat(all_data, ignore_index=True)
        return {"status": "success", "data": df.to_dict(orient="records")}

    @with_global_retry
    async def screen_stocks(self, market: str = "HK", filters: Optional[list] = None) -> Dict[str, Any]:
        """
        调用 Futu OpenD 的条件选股接口进行全市场在线扫盘。
        filters 示例: [{"field": "MARKET_VAL", "min": 10000000000}, ...]
        """
        print(f"👉 [ScreenerHandler] screen_stocks 被调用 -> 市场: {market}, 过滤条件: {filters}")  # noqa: E501

        # ─── V2 接口支持检测 ─────────────────────────────────────
        if not _FUTU_V2_SUPPORT:
            return {
                "status": "error",
                "message": "当前 futu-api 版本不支持 V2 选股接口 (StockScreenRequest) 相关常量，请升级 futu-api。",
            }  # noqa: E501

        if self.conn_mgr.status != "CONNECTED" or not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 💡 使用官方 V2 ScrMarket 枚举
        mkt_map = {
            "HK": ScrMarket.HK,
            "US": ScrMarket.US,
            "CN": ScrMarket.CN,
            "SH": ScrMarket.CN,
            "SZ": ScrMarket.CN,
            "JP": getattr(ScrMarket, "JP", None),
            "SG": getattr(ScrMarket, "SG", None),
        }
        mkt = mkt_map.get(market.upper(), ScrMarket.US)

        req = StockScreenRequest()

        has_plate = any(f.get("type") == "plate" and f.get("value") for f in (filters or []))  # noqa: E501

        # 1. 基础市场条件 (💡 重点：Futu 底层 Market 和 Plate 是“并集”关系，若指定了板块绝不能加 Market，否则会变回全市场)  # noqa: E501
        # if not has_plate:
        print(f"👉 [ScreenerHandler] add_simple_field: MARKET, [{mkt}]")
        req.add_simple_field(SimpleField.MARKET, [mkt])

        # 2. 必须的基础信息取回
        print("👉 [ScreenerHandler] add_retrieve_basic: CODE")
        req.add_retrieve_basic(BasicProperty.CODE)
        print("👉 [ScreenerHandler] add_retrieve_basic: NAME")
        req.add_retrieve_basic(BasicProperty.NAME)
        print("👉 [ScreenerHandler] add_retrieve_basic: INDUSTRY")
        req.add_retrieve_basic(BasicProperty.INDUSTRY)

        user_fields = set()
        exclude_plate_codes = []
        plate_name_to_id = {}

        # 💡 如果条件中包含板块筛选，提前异步拉取真实市场的全量板块映射表进行动态翻译
        if filters:
            has_plate = any(f.get("type") in ["plate", "exclude_plate"] for f in filters)  # noqa: E501
            if has_plate:
                try:
                    from futu import Market, Plate

                    get_plate_mkt = {
                        "HK": Market.HK,
                        "US": Market.US,
                        "SH": Market.SH,
                        "SZ": Market.SZ,
                        "JP": getattr(Market, "JP", Market.US),
                        "SG": getattr(Market, "SG", Market.US),
                    }.get(market.upper(), Market.US)

                    ret, plate_df = await asyncio.to_thread(
                        self.conn_mgr.quote_ctx.get_plate_list, get_plate_mkt, Plate.ALL
                    )  # noqa: E501
                    if ret == RET_OK and isinstance(plate_df, pd.DataFrame) and not plate_df.empty:  # noqa: E501
                        for _, row in plate_df.iterrows():
                            p_name = str(row.get("plate_name", ""))
                            p_code = str(row.get("code", ""))
                            if p_name and p_code:
                                plate_name_to_id[p_name] = p_code
                except Exception as e:
                    print(f"⚠️ [ScreenerHandler] 获取板块列表失败: {e}")

        if filters:
            for f in filters:
                field_name = f.get("field")
                f_type = f.get("type")
                lower = f.get("min")
                upper = f.get("max")

                def get_enum(enum_cls, name, default=None):
                    if not name:
                        return default  # noqa: E701
                    name_str = str(name).upper()
                    name_str = name_str.replace("GOLDEN_CROSS", "GOLD_CROSS")

                    # 💡 兼容处理：将 V1 版本的旧名称映射为 V2 版本的标准属性名，防止底层找不到枚举导致条件静默丢失  # noqa: E501
                    legacy_map = {
                        "RETURN_ON_EQUITY_RATE": "ROE",
                        "MARKET_VAL": "MARKET_CAP",
                        "CUR_PRICE": "PRICE",
                        "PB_RATE": "PB",
                        "CHANGE_RATE": "PRICE_CHANGE_PCT",
                        "VOLUME": "AVG_VOLUME",
                        "TURNOVER": "AVG_TURNOVER",
                        "TURNOVER_RATE": "TURNOVER_RATIO",
                        "NET_PROFIX_GROWTH": "NET_PROFIT_GROWTH",
                        "SUM_OF_BUSINESS": "REVENUE",
                        "SUM_OF_BUSINESS_GROWTH": "REVENUE_GROWTH",
                        "NET_PROFIT_RATE": "NET_PROFIT_RATIO",
                        "GROSS_PROFIT_RATE": "GROSS_PROFIT_RATIO",
                        "DEBT_ASSET_RATE": "DEBT_TO_ASSETS",
                        "CUR_PRICE_TO_HIGHEST52_WEEKS_RATIO": "PRICE_TO_52W_HIGH",
                        "CUR_PRICE_TO_LOWEST52_WEEKS_RATIO": "PRICE_TO_52W_LOW",
                        "HIGH_PRICE_TO_HIGHEST52_WEEKS_RATIO": "HIGH_TO_52W_HIGH",
                        "LOW_PRICE_TO_LOWEST52_WEEKS_RATIO": "LOW_TO_52W_LOW",
                        "CHANGE_RATE_5MIN": "CHANGE_5MIN",
                        "CHANGE_RATE_BEGIN_YEAR": "CHANGE_YTD",
                        "FLOAT_MARKET_VAL": "FLOAT_MARKET_CAP",
                        "SHAREHOLDER_NET_PROFIT_TTM": "SHAREHOLDERS_PROFIT_TTM",
                        "CASH_AND_CASH_EQUIVALENTS": "CASH_EQUIVALENTS",
                        "OPERATING_PROFIT_GROWTH_RATE": "OPERATING_PROFIT_GROWTH",
                        "TOTAL_ASSETS_GROWTH_RATE": "TOTAL_ASSETS_GROWTH",
                        "PROFIT_TO_SHAREHOLDERS_GROWTH_RATE": "SHAREHOLDER_PROFIT_GROWTH",  # noqa: E501
                        "PROFIT_BEFORE_TAX_GROWTH_RATE": "PROFIT_BEFORE_TAX_GROWTH",
                        "NOCF_PER_SHARE_GROWTH_RATE": "NOCF_PER_SHARE_GROWTH",
                        "OPERATING_PROFIT_TO_TOTAL_PROFIT": "OPERATING_PROFIT_TOTAL_RATIO",  # noqa: E501
                    }
                    if name_str in legacy_map and hasattr(enum_cls, legacy_map[name_str]):  # noqa: E501
                        name_str = legacy_map[name_str]

                    if hasattr(enum_cls, name_str):
                        return getattr(enum_cls, name_str)
                    return default

                # 💡 智能类型纠偏
                if field_name and f_type not in ["plate", "exclude_plate"]:
                    type_mapping = {
                        "simple": SimpleProperty,
                        "financial": FinancialProperty,
                        "accumulate": CumulativeProperty,
                        "featured": FeaturedProperty,
                        "indicator_pattern": Pattern,
                        "indicator_positional": Indicator,
                        "kline_shape": KlineShapeProperty,
                        "broker": BrokerProperty,
                        "option": OptionProperty,
                    }
                    expected_enum = type_mapping.get(f_type)
                    if not expected_enum or not get_enum(expected_enum, field_name):
                        for correct_type, enum_cls in type_mapping.items():
                            if get_enum(enum_cls, field_name):
                                print(
                                    f"🔧 [ScreenerHandler] 智能纠偏: 字段 {field_name} 的类型从 {f_type} 被自动纠正为 {correct_type}"
                                )  # noqa: E501
                                f_type = correct_type
                                f["type"] = correct_type
                                break

                def format_intervals(raw_intervals, l_val=None, u_val=None):
                    # 严格按照 Futu SDK 文档格式组装: [{'lower': {'value':v,'includes':b}, 'upper':...}]  # noqa: E501
                    res_list = []
                    if raw_intervals:
                        for intv in raw_intervals:
                            item = {}
                            l = intv.get("lower", intv.get("min"))  # noqa: E741
                            u = intv.get("upper", intv.get("max"))
                            if l is not None:
                                item["lower"] = {"value": float(l), "includes": True}  # noqa: E501, E701
                            if u is not None:
                                item["upper"] = {"value": float(u), "includes": True}  # noqa: E501, E701
                            if item:
                                res_list.append(item)  # noqa: E701
                    elif l_val is not None or u_val is not None:
                        item = {}
                        if l_val is not None:
                            item["lower"] = {"value": float(l_val), "includes": True}  # noqa: E501, E701
                        if u_val is not None:
                            item["upper"] = {"value": float(u_val), "includes": True}  # noqa: E501, E701
                        res_list.append(item)
                    return res_list if res_list else None

                def get_period(period_str):
                    """安全映射字符串 K 线周期到底层枚举"""
                    if not period_str:
                        return getattr(__import__("futu").Period, "DAY", 11)
                    period_str = str(period_str).upper()
                    period_map = {
                        "K_DAY": getattr(__import__("futu").Period, "DAY", 11),
                        "K_WEEK": getattr(__import__("futu").Period, "WEEK", 12),
                        "K_MON": getattr(__import__("futu").Period, "MONTH", 13),
                        "K_1M": getattr(__import__("futu").Period, "MIN1", 1),
                        "K_5M": getattr(__import__("futu").Period, "MIN5", 5),
                        "K_15M": getattr(__import__("futu").Period, "MIN15", 15),
                        "K_30M": getattr(__import__("futu").Period, "MIN30", 30),
                        "K_60M": getattr(__import__("futu").Period, "MIN60", 60),
                    }
                    return period_map.get(period_str, getattr(__import__("futu").Period, "DAY", 11))  # noqa: E501

                try:
                    # 💡 自动兜底格式化：防范 LLM 忘记输出市场前缀 (如把 US.BK2991 输出成了 BK2991)  # noqa: E501
                    def format_plate(code: str) -> str:
                        # 💡 行业名动态翻译：如果传入的是纯中文行业名，利用字典翻译为 Futu 板块代码  # noqa: E501
                        if code in plate_name_to_id:
                            code = plate_name_to_id[code]
                        else:
                            # 模糊匹配 (例如传入"半导体"，匹配到"半导体概念")
                            for name, pid in plate_name_to_id.items():
                                if code in name or name in code:
                                    code = pid
                                    break

                        code = str(code).upper()
                        return code if "." in code else f"{market.upper()}.{code}"

                    # 1. 行业板块筛选
                    if f_type == "plate" and f.get("value"):
                        plates = [format_plate(p) for p in f.get("value")]
                        print(f"👉 [ScreenerHandler] add_plate: {plates}")
                        req.add_plate(plates)
                        continue

                    # 1.5 行业板块剔除 (收集代码盘后执行二次过滤)
                    if f_type == "exclude_plate" and f.get("value"):
                        exclude_plate_codes.extend([format_plate(p) for p in f.get("value")])  # noqa: E501
                        continue

                    # 2. 简单行情属性
                    if f_type == "simple":
                        prop = get_enum(SimpleProperty, field_name)
                        if prop:
                            print(f"👉 [ScreenerHandler] add_simple_property: {prop}, lower={lower}, upper={upper}")  # noqa: E501
                            req.add_simple_property(prop, lower=lower, upper=upper)
                            print(f"👉 [ScreenerHandler] add_retrieve_simple: {prop}")
                            req.add_retrieve_simple(prop)
                            user_fields.add(field_name)

                    # 3. 财务属性
                    elif f_type == "financial":
                        prop = get_enum(FinancialProperty, field_name)
                        if prop:
                            term = get_enum(Term, f.get("term"), Term.LATEST)
                            fin_kwargs = {}
                            for arg_k in [
                                "lower_included",
                                "upper_included",
                                "duration",
                                "continuous_period",
                                "period_average",
                                "future_duration",
                                "unit",
                            ]:  # noqa: E501
                                if arg_k in f and f[arg_k] is not None:
                                    fin_kwargs[arg_k] = f[arg_k]
                            print(
                                f"👉 [ScreenerHandler] add_financial_property: {prop}, term={term}, lower={lower}, upper={upper}, kwargs={fin_kwargs}"
                            )  # noqa: E501
                            req.add_financial_property(prop, term=term, lower=lower, upper=upper, **fin_kwargs)  # noqa: E501
                            print(f"👉 [ScreenerHandler] add_retrieve_financial: {prop}, term={term}")  # noqa: E501
                            req.add_retrieve_financial(prop, term)
                            user_fields.add(field_name)

                    # 4. 累计行情属性
                    elif f_type == "accumulate":
                        prop = get_enum(CumulativeProperty, field_name)
                        if prop:
                            days = f.get("days", 1)
                            print(
                                f"👉 [ScreenerHandler] add_cumulative_property: {prop}, days={days}, lower={lower}, upper={upper}"
                            )  # noqa: E501
                            req.add_cumulative_property(prop, days=days, lower=lower, upper=upper)  # noqa: E501
                            print(f"👉 [ScreenerHandler] add_retrieve_cumulative: {prop}, days={days}")  # noqa: E501
                            req.add_retrieve_cumulative(prop, days)
                            user_fields.add(field_name)

                    # 5. 特色指标
                    elif f_type == "featured":
                        prop = get_enum(FeaturedProperty, field_name)
                        if prop:
                            fmt_intervals = format_intervals(f.get("intervals"), lower, upper)  # noqa: E501
                            print(f"👉 [ScreenerHandler] add_featured_property: {prop}, intervals={fmt_intervals}")  # noqa: E501
                            req.add_featured_property(prop, intervals=fmt_intervals)
                            print(f"👉 [ScreenerHandler] add_retrieve_featured: {prop}")
                            req.add_retrieve_featured(prop)
                            user_fields.add(field_name)

                    # 6. 技术指标形态
                    elif f_type == "indicator_pattern":
                        prop = get_enum(Pattern, field_name)
                        if prop:
                            period_type = get_period(f.get("period", "K_DAY"))
                            print(f"👉 [ScreenerHandler] add_indicator_pattern: {prop}, period_type={period_type}")  # noqa: E501
                            req.add_indicator_pattern(prop, period_type=period_type)

                            # 💡 智能附加回包展示对应的具体指标 (如 RSI_BOTTOM_DIVERGE 截取 RSI)  # noqa: E501
                            base_indicator_str = field_name.split("_")[0]
                            base_ind = get_enum(Indicator, base_indicator_str)
                            if base_ind:
                                print(
                                    f"👉 [ScreenerHandler] add_retrieve_indicator (pattern 附加): {base_ind}, period_type={period_type}"
                                )  # noqa: E501
                                req.add_retrieve_indicator(base_ind, period=period_type)

                    # 7. 技术指标位置关系
                    elif f_type == "indicator_positional":
                        prop1 = get_enum(Indicator, field_name)
                        prop2 = get_enum(Indicator, f.get("second_indicator"))
                        pos = get_enum(Position, f.get("position"))
                        if prop1 and pos:
                            period_type = get_period(f.get("period", "K_DAY"))
                            print(
                                f"👉 [ScreenerHandler] add_indicator_positional: pos={pos}, period_type={period_type}, prop1={prop1}, prop2={prop2}"
                            )  # noqa: E501
                            req.add_indicator_positional(pos, period_type, prop1, prop2)
                            print(f"👉 [ScreenerHandler] add_retrieve_indicator: {prop1}, period_type={period_type}")  # noqa: E501
                            req.add_retrieve_indicator(prop1, period=period_type)
                            user_fields.add(field_name)
                            if prop2:
                                print(
                                    f"👉 [ScreenerHandler] add_retrieve_indicator: {prop2}, period_type={period_type}"
                                )  # noqa: E501
                                req.add_retrieve_indicator(prop2, period=period_type)
                                user_fields.add(f.get("second_indicator", ""))

                    # 8. K线形态
                    elif f_type == "kline_shape":
                        from futu import KLType

                        prop = get_enum(KlineShapeProperty, field_name)
                        if prop:
                            period = get_enum(KLType, f.get("period"), KLType.K_DAY)
                            print(f"👉 [ScreenerHandler] add_kline_shape: {prop}, period={period}")  # noqa: E501
                            req.add_kline_shape(prop, period=period)
                            print(f"👉 [ScreenerHandler] add_retrieve_kline_shape: {prop}, period={period}")  # noqa: E501
                            req.add_retrieve_kline_shape(prop, period)

                    # 9. 经纪商持股
                    elif f_type == "broker":
                        prop = get_enum(BrokerProperty, field_name)
                        if prop:
                            days = f.get("days", 1)
                            print(f"👉 [ScreenerHandler] add_broker_holdings: {prop}, days={days}")  # noqa: E501
                            req.add_broker_holdings(prop, days=days)
                            print(f"👉 [ScreenerHandler] add_retrieve_broker: {prop}, days={days}")  # noqa: E501
                            req.add_retrieve_broker(prop, days)

                    # 10. 期权指标
                    elif f_type == "option":
                        prop = get_enum(OptionProperty, field_name)
                        if prop:
                            period = f.get("period")
                            fmt_intervals = format_intervals(f.get("intervals"), lower, upper)  # noqa: E501
                            print(
                                f"👉 [ScreenerHandler] add_option: {prop}, intervals={fmt_intervals}, period={period}"
                            )  # noqa: E501
                            req.add_option(prop, intervals=fmt_intervals, period=period)
                            print(f"👉 [ScreenerHandler] add_retrieve_option: {prop}, period={period}")  # noqa: E501
                            req.add_retrieve_option(prop, period)

                    else:
                        return {
                            "status": "error",
                            "message": f"大模型虚构了不支持的指标字段: '{field_name}'。",
                        }  # noqa: E501

                except Exception as inner_e:
                    print(f"⚠️ [ScreenerHandler] 添加 {f_type} 条件时异常: {inner_e}")
                    return {"status": "error", "message": f"指标解析异常: {inner_e}"}

        # 3. 强制附加常驻返回字段
        default_return_fields = [
            ("PRICE", "simple"),
            ("MARKET_CAP", "simple"),
            ("PRICE_CHANGE_PCT", "accumulate"),
            ("TURNOVER_RATIO", "accumulate"),
            ("AVG_TURNOVER", "accumulate"),
            ("PE_TTM", "simple"),
            ("PB", "simple"),
        ]

        for f_name, f_type in default_return_fields:
            if f_name not in user_fields:
                if f_type == "accumulate" and hasattr(CumulativeProperty, f_name):
                    prop = getattr(CumulativeProperty, f_name)
                    print(f"👉 [ScreenerHandler] add_retrieve_cumulative (default): {prop}, days=1")  # noqa: E501
                    req.add_retrieve_cumulative(prop, 1)
                elif f_type == "simple" and hasattr(SimpleProperty, f_name):
                    prop = getattr(SimpleProperty, f_name)
                    print(f"👉 [ScreenerHandler] add_retrieve_simple (default): {prop}")
                    req.add_retrieve_simple(prop)

                if not filters and f_name == "PRICE" and hasattr(SimpleProperty, f_name):  # noqa: E501
                    prop = getattr(SimpleProperty, f_name)
                    print(f"👉 [ScreenerHandler] add_simple_property (default): {prop}, lower=0.001, upper=None")  # noqa: E501
                    req.add_simple_property(prop, lower=0.001, upper=None)

        # 4. 默认排序：按市值降序
        if hasattr(SimpleProperty, "MARKET_CAP"):
            prop = getattr(SimpleProperty, "MARKET_CAP")
            print(
                f"👉 [ScreenerHandler] set_sort: direction=DESC, property_type='simple', property_params={{'name': {int(prop)}}}"
            )  # noqa: E501
            req.set_sort(
                direction=ScrSortDir.DESC,
                property_type="simple",
                property_params={"name": int(prop)},
            )  # noqa: E501

        if self.screen_lock is None:
            self.screen_lock = asyncio.Lock()

        all_dfs = []
        begin = 0
        num = 2000  # 💡 扩大单次拉取数量，实现“一波流”请求，避免每次 200 条导致的过度碎片化网络通信  # noqa: E501
        max_total = 10000

        try:
            async with self.screen_lock:
                try:
                    # 💡 修复超时陷阱：将 timeout 移到锁内部，只计算真实网络耗时，不计入排队等待时间  # noqa: E501
                    async with asyncio.timeout(14.0):
                        print(f"📡 [Futu] 发起 V2 条件选股扫盘 -> 市场: {market}")
                        while begin < max_total:
                            req.page_from = begin
                            req.page_count = num

                            print(
                                f"👉 [ScreenerHandler] get_stock_screen: 发起请求 (page_from={begin}, page_count={num})"
                            )  # noqa: E501
                            futu_res = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_stock_screen, req)

                            ret, raw_data = futu_res[0], futu_res[1]  # type: ignore
                            if ret != RET_OK:
                                if not all_dfs:
                                    print(f"❌ [Futu] 选股获取失败: {raw_data}")
                                    return {
                                        "status": "error",
                                        "message": f"选股失败: {raw_data}",
                                    }  # noqa: E501
                                break

                            if isinstance(raw_data, tuple):
                                if len(raw_data) >= 3:
                                    is_last_page, _all_count, items = (
                                        raw_data[0],
                                        raw_data[1],
                                        raw_data[2],
                                    )  # noqa: E501
                                elif len(raw_data) == 2:
                                    is_last_page, items = raw_data[0], raw_data[1]
                                else:
                                    is_last_page, items = True, []
                            else:
                                is_last_page, items = True, []

                            v2_rev_map = {}
                            # 💡 修复：使用模块级已导入的枚举常量构建反向映射表
                            # 避免函数内 from ... import 导致 Python 3.12 将模块级名称标记为局部变量（UnboundLocalError）
                            try:
                                for enum_class in [
                                    BasicProperty,
                                    SimpleProperty,
                                    FinancialProperty,
                                    CumulativeProperty,
                                    FeaturedProperty,
                                    Pattern,
                                    KlineShapeProperty,
                                    BrokerProperty,
                                    OptionProperty,
                                    Indicator,
                                ]:
                                    if enum_class is None:
                                        continue
                                    for member in enum_class:
                                        v2_rev_map[member.value] = member.name.lower()
                            except Exception:
                                pass

                            if isinstance(items, list) and len(items) > 0:
                                print(
                                    f"  -> 📄 [Futu] {market} 市场翻页拉取中 (begin={begin})... 拿到 {len(items)} 条数据"
                                )  # noqa: E501
                                for item in items:
                                    row_dict = {}
                                    for res in item.get("results", []):
                                        prop_val = res.get("property", {}).get("name", "")  # noqa: E501

                                        if isinstance(prop_val, int) or (
                                            isinstance(prop_val, str) and prop_val.isdigit()
                                        ):  # noqa: E501
                                            prop_name = v2_rev_map.get(int(prop_val), str(prop_val))  # noqa: E501
                                        elif hasattr(prop_val, "name"):
                                            prop_name = str(getattr(prop_val, "name")).lower()  # noqa: E501
                                        else:
                                            prop_name = str(prop_val).lower()

                                        v_type = res.get("value_type", 0)

                                        val = None
                                        if v_type == 1:
                                            val = res.get("sval")  # noqa: E701
                                        elif v_type == 2:
                                            val = res.get("ival")  # noqa: E701
                                        elif v_type == 3:
                                            val = res.get("aval")  # noqa: E701
                                        elif v_type == 4:
                                            val = res.get("dval")  # noqa: E701

                                        if prop_name and val is not None:
                                            row_dict[prop_name] = val

                                    all_dfs.append(row_dict)
                                begin += len(items)
                            else:
                                begin += num

                            if is_last_page or not items:
                                print(f"  -> ✅ [Futu] {market} 市场数据拉取完毕！(已到底或无更多数据)")  # noqa: E501
                                break

                            await asyncio.sleep(0.1)
                finally:
                    # 💡 错峰流控防封杀：在释放排队锁前强制休眠 1.5 秒
                    # 彻底防范底层网关拥堵时由于立刻丢锁引发的“级联超时雪崩”
                    await asyncio.sleep(1.5)

        except TimeoutError:
            print("⚠️ [Futu] 条件选股接口响应超时 (12s)，底层网关忙线。")
            return {
                "status": "error",
                "message": "Futu 条件选股接口响应超时，底层网关忙线。",
            }  # noqa: E501

        if not all_dfs:
            return {
                "status": "success",
                "data": [],
                "message": "未能匹配到任何符合条件的股票。",
            }  # noqa: E501

        data = pd.DataFrame(all_dfs)
        if "code" in data.columns:
            data = data.drop_duplicates(subset=["code"])

        # 💡 提取命中的技术形态中文名
        matched_patterns_zh = []
        PATTERN_ZH_MAP = {
            "macd_gold_cross": "MACD金叉",
            "macd_golden_cross": "MACD金叉",
            "rsi_oversold": "RSI超卖",
            "kdj_gold_cross": "KDJ金叉",
            "kdj_golden_cross": "KDJ金叉",
            "rsi_bottom_diverge": "RSI底背离",
            "rsi_top_diverge": "RSI顶背离",
            "macd_bottom_diverge": "MACD底背离",
            "macd_top_diverge": "MACD顶背离",
            "vcp_pattern": "VCP形态",
            "gap_up": "跳空高开",
        }
        if filters:
            for f in filters:
                if f.get("type") == "indicator_pattern":
                    p_field = str(f.get("field")).lower()
                    matched_patterns_zh.append(PATTERN_ZH_MAP.get(p_field, f.get("field")))  # noqa: E501

        results = []
        for i, row in data.head(max_total).iterrows():
            code = str(row.get("code", ""))

            # 💡 确保代码具有正确的富途市场前缀 (针对部分未带前缀的返回数据)
            if "." not in code:
                prefix = market.upper()
                # Futu A股代码细分：如果是 CN 市场，通过代码首位推断 SH/SZ
                if prefix == "CN":
                    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
                code = f"{prefix}.{code}"

            item_dict: Dict[str, Any] = {
                "symbol": code,
                "name": str(row.get("name", code)),
            }

            if matched_patterns_zh:
                item_dict["matched_patterns"] = ", ".join(matched_patterns_zh)

            key_mapping = {
                "price": "price",
                "price_change_pct": "chg",
                "market_cap": "mktcap",
                "stock_plate": "plate",
            }

            for col in data.columns:
                if col not in ["code", "name"]:
                    val = row.get(col)
                    if pd.notna(val) and val is not None:
                        final_key = key_mapping.get(col, col)
                        # 💡 强制数值化，防范 numpy scalar 对象或大数科学计数法导致的前端类型逃逸  # noqa: E501
                        try:
                            item_dict[final_key] = float(val) if not isinstance(val, bool) else val  # noqa: E501
                        except (ValueError, TypeError):
                            item_dict[final_key] = val

            results.append(item_dict)

        # 💡 执行板块剔除的二次过滤逻辑
        if exclude_plate_codes and results:
            print(f"🛡️ [ScreenerHandler] 触发板块剔除，准备拉取需排除的板块成分股: {exclude_plate_codes}")  # noqa: E501
            exclude_symbols = set()
            for p_code in exclude_plate_codes:
                try:
                    ret, p_data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_plate_stock, p_code)  # noqa: E501
                    if ret == RET_OK and isinstance(p_data, pd.DataFrame) and not p_data.empty:  # noqa: E501
                        exclude_symbols.update(p_data["code"].tolist())
                except Exception as e:
                    print(f"⚠️ [ScreenerHandler] 拉取排除板块 {p_code} 失败: {e}")

            if exclude_symbols:
                original_len = len(results)
                results = [r for r in results if r["symbol"] not in exclude_symbols]
                print(
                    f"🛡️ [ScreenerHandler] 成功剔除 {original_len - len(results)} 只属于 {exclude_plate_codes} 板块的股票"
                )  # noqa: E501

        # 💡 批量衍生格式化后的百分比字段 (保留原 Float 字段防后端运算报错)
        pct_keys = {
            "amplitude",
            "change_rate",
            "price_change_pct",
            "turnover_rate",
            "turnover_ratio",
            "roe",
            "roa",
            "roa_ttm",
            "dividend_ratio",
            "gross_profit_ratio",
            "gross_profit_rate",
            "net_profit_ratio",
            "net_profit_rate",
            "operating_margin",
            "operating_margin_ttm",
            "debt_to_assets",
            "debt_asset_rate",
        }
        for row in results:
            for k in list(row.keys()):
                v = row[k]
                if isinstance(v, (int, float)):
                    is_pct = k in pct_keys or k.endswith("_growth") or k.endswith("_growth_rate") or "percentile" in k  # noqa: E501
                    # 剔除掉绝对倍数指标 (如流动比率等)
                    if is_pct and k not in {
                        "current_ratio",
                        "quick_ratio",
                        "property_ratio",
                    }:  # noqa: E501
                        # 新增 _fmt 字段，前端表格可直接绑定 field: "roe_fmt"
                        row[f"{k}_fmt"] = f"{v * 100:.2f}%"
                    elif k in {
                        "current_ratio",
                        "quick_ratio",
                        "property_ratio",
                        "volume_ratio",
                    }:  # noqa: E501
                        row[f"{k}_fmt"] = f"{v:.2f}"

        return {"status": "success", "data": results}

    @with_global_retry
    async def get_stock_basicinfo(self, market: str, sec_type: str) -> Dict[str, Any]:
        """获取全市场股票/ETF基本信息"""
        if self.conn_mgr.status != "CONNECTED" or not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        from futu import Market, SecurityType

        mkt_map = {"HK": Market.HK, "US": Market.US, "SH": Market.SH, "SZ": Market.SZ}
        sec_map = {
            "STOCK": SecurityType.STOCK,
            "ETF": SecurityType.ETF,
            "INDEX": SecurityType.IDX,
        }  # noqa: E501

        mkt = mkt_map.get(market.upper(), Market.HK)
        sec = sec_map.get(sec_type.upper(), SecurityType.STOCK)

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_stock_basicinfo, mkt, sec)
        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            return {"status": "error", "message": f"基本信息获取失败: {data}"}

        return {"status": "success", "data": data.to_dict(orient="records")}
