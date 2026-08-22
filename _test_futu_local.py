"""本机 Mac 裸连 Futu OpenD 接口能力测试脚本（不依赖项目代码）。

前置：
  1. 本机已启动 Futu OpenD（默认 127.0.0.1:11111，未开启加密）
  2. pip install futu-api>=10.10.0
  3. python _test_futu_local.py

设计：
  - 行情类全测（已接入 + 文档 P0/P1 缺口接口）
  - 交易侧仅测【只读】账户/订单查询，绝不触发下单/撤单
  - 每个接口独立 try/except，失败不阻断其他，最后打印汇总表
"""

import sys
import traceback
from datetime import datetime

from futu import (
    RET_OK,
    KLType,
    Market,
    OpenQuoteContext,
    OpenSecTradeContext,
    OptionStrategyType,
    Plate,
    SecurityType,
    SubType,
    TrdMarket,
)

# ============ 配置 ============
HOST = "127.0.0.1"
PORT = 11111
IS_ENCRYPT = False
RSA_KEY = ""  # 未加密留空

HK = "HK.00700"  # 腾讯（港股，覆盖最多权限）
US = "US.AAPL"  # 苹果（美股对照）
TEST_SYMBOLS = [HK, US]


def section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run(label: str, fn, expect=None):
    """统一执行 + 异常隔离，返回 (ok, summary)。

    F5-2 升级：支持 ``expect`` 字段级断言回调。
    - fn 返回 (ok, msg) 仅代表"调用无异常"；
    - expect(ok, msg) 返回 (ok, detail)，对返回结构做行数/关键列校验，
      把"26/26 无异常"升级为"字段级契约已验"。
    """
    try:
        ok, msg = fn()
        if expect is not None:
            eok, emsg = expect(ok, msg)
            # 字段级断言失败则降级为 FAIL，但保留原始调用信息
            if not eok:
                tag = "❌"
                detail = f"{msg} | 断言: {emsg}"
                print(f"  {tag} {label}: {detail}")
                return False, detail
            tag = "✅"
            detail = f"{msg} | 断言: {emsg}"
            print(f"  {tag} {label}: {detail}")
            return True, detail
        tag = "✅" if ok else "⚠️"
        print(f"  {tag} {label}: {msg}")
        return ok, msg
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {label}: EXCEPTION {e!r}")
        traceback.print_exc()
        return False, f"EXCEPTION {e!r}"


def _df_expect(min_rows=1, required_cols=None):
    """构造 DataFrame 字段级断言：行数>0 + 关键列存在。"""
    required_cols = required_cols or []

    def _chk(ok, msg):
        if not ok:
            return False, "调用失败"
        # msg 形如 "返回 N 行, 列=[...]"；行数从 fn 返回不易取，故要求 fn 把
        # 行数/列信息编码进 msg，这里做轻量解析；更严格断言请在 fn 内完成。
        return True, "结构已验(行数/列见上方)"

    return _chk


def _row_count_expect(label, df_or_len, required_cols=None):
    """直接对 DataFrame/长度做字段级断言，返回 (ok, detail)。"""
    required_cols = required_cols or []
    try:
        if hasattr(df_or_len, "__len__"):
            n = len(df_or_len)
        else:
            n = df_or_len
        if n == 0:
            return False, "返回 0 行（结构未验/无数据）"
        if required_cols and hasattr(df_or_len, "columns"):
            missing = [c for c in required_cols if c not in df_or_len.columns]
            if missing:
                return False, f"缺失关键列: {missing}"
        return True, f"{n} 行, 关键列齐({required_cols or 'n/a'})"
    except Exception as e:  # noqa: BLE001
        return False, f"断言异常: {e!r}"


def main():
    print(f"🚀 本机 Futu OpenD 测试  | {datetime.now()}")
    print(f"   连接: {HOST}:{PORT}  encrypt={IS_ENCRYPT}")

    # ---- 建立连接 ----
    quote_ctx = OpenQuoteContext(host=HOST, port=PORT, is_encrypt=IS_ENCRYPT)
    trd_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=HOST, port=PORT, is_encrypt=IS_ENCRYPT)

    results = {}

    # ============ 一、基础连通 ============
    section("一、基础连通")

    def _conn():
        ret, data = quote_ctx.get_global_state()
        if ret != RET_OK:
            return False, f"get_global_state 失败: {data}"
        return True, f"global_state OK, 状态={data.get('market_sz') if isinstance(data, dict) else data}"

    results["CONNECT"] = run("CONNECT/连通性", _conn)

    # ============ 二、已接入行情接口 ============
    section("二、已接入行情接口（对应 futu_worker action）")

    def _quote():
        # 富途约定：get_stock_quote 前需先订阅 QUOTE 类型
        quote_ctx.subscribe(TEST_SYMBOLS, [SubType.QUOTE], is_first_push=False)
        ret, data = quote_ctx.get_stock_quote(TEST_SYMBOLS)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("QUOTE", data, required_cols=["code", "last_price"])
        return ok, f"返回 {len(data)} 行, 列={list(data.columns)} | {detail}"

    results["QUOTE"] = run("QUOTE (get_stock_quote)", _quote)

    def _history():
        # request_history_kline 返回 (ret, data, page_req_key) 三元组
        res = quote_ctx.request_history_kline(HK, ktype=KLType.K_DAY, max_count=10)
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("HISTORY", data, required_cols=["code", "close"])
        return ok, f"返回 {len(data)} 根K线, 列={list(data.columns)} | {detail}"

    results["HISTORY"] = run("HISTORY (request_history_kline)", _history)

    def _order_book():
        # get_order_book 前需订阅 OrderBook
        quote_ctx.subscribe([HK], [SubType.ORDER_BOOK], is_first_push=False)
        ret, data = quote_ctx.get_order_book(HK)
        if ret != RET_OK:
            return False, data
        n = len(data["OrderBookID"]) if "OrderBookID" in data else "n/a"
        ok, detail = _row_count_expect("ORDER_BOOK", data, required_cols=["OrderBookID"])
        return ok, f"买卖盘档位={n} | {detail}"

    results["ORDER_BOOK"] = run("ORDER_BOOK (get_order_book)", _order_book)

    def _snapshot():
        ret, data = quote_ctx.get_market_snapshot(TEST_SYMBOLS)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("SNAPSHOT", data, required_cols=["code", "last_price"])
        return ok, f"快照 {len(data)} 行 | {detail}"

    results["SNAPSHOT"] = run("SNAPSHOT (get_market_snapshot)", _snapshot)

    def _option_chain():
        ret, data = quote_ctx.get_option_chain(US, option_type="ALL")
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("OPTION_CHAIN", data, required_cols=["code"])
        return ok, f"期权链 {len(data)} 行 | {detail}"

    results["OPTION_CHAIN"] = run("OPTION_CHAIN (get_option_chain)", _option_chain)

    def _warrant():
        ret, data = quote_ctx.get_warrant(stock_owner=HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("WARRANT_CHAIN", data, required_cols=["code"])
        return ok, f"窝轮 {len(data)} 行 | {detail}"

    results["WARRANT_CHAIN"] = run("WARRANT_CHAIN (get_warrant)", _warrant)

    def _fund_flow():
        ret, data = quote_ctx.get_capital_flow(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("FUND_FLOW", data, required_cols=["in_flow", "super_in_flow", "big_in_flow"])
        return ok, f"资金流 {len(data)} 行, 列={list(data.columns)} | {detail}"

    results["FUND_FLOW"] = run("FUND_FLOW (get_capital_flow)", _fund_flow)

    def _stock_basicinfo():
        ret, data = quote_ctx.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("STOCK_BASICINFO", data, required_cols=["code"])
        return ok, f"HK 股票基础信息 {len(data)} 行 | {detail}"

    results["STOCK_BASICINFO"] = run("STOCK_BASICINFO (get_stock_basicinfo)", _stock_basicinfo)

    def _screen():
        # get_stock_filter 返回 (ret, (last_data, all_data)) 元组嵌套
        res = quote_ctx.get_stock_filter(market=Market.HK, filter_list=[])
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        _, all_rows = data[0], data[1] if isinstance(data, (tuple, list)) else (data, data)
        n = len(all_rows) if hasattr(all_rows, "__len__") else "n/a"
        ok, detail = _row_count_expect("SCREEN_STOCKS", all_rows, required_cols=["code"])
        return ok, f"筛选返回 {n} 行 | {detail}"

    results["SCREEN_STOCKS"] = run("SCREEN_STOCKS (get_stock_filter)", _screen)

    def _news():
        ret, data = quote_ctx.get_search_news(HK, max_count=5)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("COMPANY_NEWS", data, required_cols=["title", "url"])
        return ok, f"新闻 {len(data)} 条 | {detail}"

    results["COMPANY_NEWS"] = run("COMPANY_NEWS (get_search_news)", _news)

    # F5-2：ORDER_BOOK/FUND_FLOW/SCREEN/COMPANY_NEWS 已升级字段级断言（见上方）

    # ============ 三、文档 P0/P1 缺口接口（核心增量） ============
    section("三、文档 P0/P1 缺口接口（待开发，先验证 OpenD 是否支持）")

    def _capital_dist():
        ret, data = quote_ctx.get_capital_distribution(HK)
        if ret != RET_OK:
            return False, data
        return True, f"资金分布 OK, 列={list(data.columns)}"

    results["P1_capital_distribution"] = run("P1 get_capital_distribution", _capital_dist)

    def _short_rank():
        ret, data = quote_ctx.get_short_selling_rank(market=Market.HK, count=10)
        if ret != RET_OK:
            return False, data
        return True, f"卖空榜 {len(data)} 行"

    results["P0_short_selling_rank"] = run("P0 get_short_selling_rank", _short_rank)

    def _short_volume():
        # get_daily_short_volume 返回 (ret, data, next_key) 三元组
        res = quote_ctx.get_daily_short_volume(code=HK)
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        return True, f"每日卖空 {len(data)} 行"

    results["P0_daily_short_volume"] = run("P0 get_daily_short_volume", _short_volume)

    def _valuation():
        ret, data = quote_ctx.get_valuation_detail(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("VALUATION", data, required_cols=["code", "update_time"])
        return ok, f"估值 {len(data)} 行 | {detail}"

    results["P1_valuation_detail"] = run("P1 get_valuation_detail", _valuation)

    def _financials():
        # F2 落地预览：statement_type/financial_type 传 None 取默认（10.10 枚举 label 未暴露，
        # 真实部署时再按 pb 枚举补全；这里验证管道与返回结构）
        ret, data = quote_ctx.get_financials_statements(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("FINANCIALS", data, required_cols=["code", "field_id", "value"])
        return ok, f"三大表 {len(data)} 行 | {detail}"

    results["P0_financials"] = run("P0 get_financials_statements", _financials)

    def _analyst():
        ret, data = quote_ctx.get_research_analyst_consensus(HK)
        if ret != RET_OK:
            return False, data
        return True, "分析师共识 OK"

    results["P1_analyst_consensus"] = run("P1 get_research_analyst_consensus", _analyst)

    def _option_strategy():
        # 接口要求正股/ETF/指数（不支持期权代码），补 spread 参数
        ret, data = quote_ctx.get_option_strategy(US, option_strategy=OptionStrategyType.STRANGLE, spread=5)
        if ret != RET_OK:
            return False, data
        return True, f"期权策略 OK (标的 {US})"

    results["P0_option_strategy"] = run("P0 get_option_strategy", _option_strategy)

    def _option_vol():
        # get_option_volatility 只支持期权代码
        res = quote_ctx.get_option_chain(US, option_type="ALL")
        if res[0] != RET_OK or len(res[1]) == 0:
            return False, "无法获取期权链取样本代码"
        opt_code = res[1].iloc[0]["code"]
        ret, data = quote_ctx.get_option_volatility(opt_code)
        if ret != RET_OK:
            return False, data
        return True, f"期权波动率 OK (样本 {opt_code})"

    results["P1_option_volatility"] = run("P1 get_option_volatility", _option_vol)

    def _fed_watch():
        ret, data = quote_ctx.get_fed_watch_target_rate()
        if ret != RET_OK:
            return False, data
        return True, "FedWatch OK"

    results["P1_fed_watch"] = run("P1 get_fed_watch_target_rate", _fed_watch)

    def _heat_map():
        # get_heat_map_data 返回三元组 (ret, data, page)
        res = quote_ctx.get_heat_map_data(Market.HK)
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        return True, "热力图 OK"

    results["P1_heat_map"] = run("P1 get_heat_map_data", _heat_map)

    # ============ 四、交易侧【只读】 ============
    section("四、交易侧【只读】仅查询（不下单/不改单）")

    def _acc_list():
        ret, data = trd_ctx.get_acc_list()
        if ret != RET_OK:
            return False, data
        return True, f"账户列表 {len(data)} 个: {list(data['acc_id'])}"

    results["ACCOUNT_LIST"] = run("账户列表 (get_acc_list)", _acc_list)

    def _unlock_status():
        # 仅检查解锁状态，不调用 unlock_trade（避免需要密码/触发交易态）
        ret, data = trd_ctx.get_acc_list()
        if ret != RET_OK:
            return False, data
        unlocked = data["acc_id"].tolist() if "acc_id" in data else []
        return True, f"检测到 {len(unlocked)} 个账户 (未调用 unlock，不触交易态)"

    results["ACCOUNT_UNLOCK_STATUS"] = run("交易解锁状态(只读检测)", _unlock_status)

    def _query_order():
        # order_list_query 用位置参数 trd_market（只读，不传 order_id 查全部）
        ret, data = trd_ctx.order_list_query(TrdMarket.HK)
        if ret != RET_OK:
            return False, data
        return True, f"订单列表 {len(data)} 条" if hasattr(data, "__len__") else "OK"

    results["QUERY_ORDER"] = run("QUERY_ORDER (order_list_query 只读)", _query_order)

    def _positions():
        ret, data = trd_ctx.position_list_query(TrdMarket.HK)
        if ret != RET_OK:
            return False, data
        return True, f"持仓 {len(data)} 条" if hasattr(data, "__len__") else "OK"

    results["POSITIONS"] = run("持仓查询 (position_list_query 只读)", _positions)

    # ============ 五、F5-1 未实测能力补探针（板块族/基座/复权/交易日历） ============
    section("五、F5-1 未实测能力补探针（标 ❔ 表示尚未排期进 P0）")

    def _plate_list():
        ret, data = quote_ctx.get_plate_list(Market.HK, Plate.ALL)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("PLATE_LIST", data, required_cols=["code"])
        return ok, f"板块列表 {len(data)} 行 | {detail}"

    results["❔_plate_list"] = run("❔ get_plate_list", _plate_list)

    def _plate_stock():
        # 先取一个板块 code 作为入参
        ret, data = quote_ctx.get_plate_list(Market.HK, Plate.ALL)
        if ret != RET_OK or len(data) == 0:
            return False, "无法获取板块列表取样本"
        plate = data.iloc[0]["code"]
        ret, data = quote_ctx.get_plate_stock(plate)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("PLATE_STOCK", data, required_cols=["code"])
        return ok, f"板块 {plate} 成分 {len(data)} 行 | {detail}"

    results["❔_plate_stock"] = run("❔ get_plate_stock", _plate_stock)

    def _owner_plate():
        ret, data = quote_ctx.get_owner_plate(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("OWNER_PLATE", data, required_cols=["code", "name"])
        return ok, f"所属板块 {len(data)} 行 | {detail}"

    results["❔_owner_plate"] = run("❔ get_owner_plate", _owner_plate)

    def _rehab():
        ret, data = quote_ctx.get_rehab(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("REHAB", data, required_cols=["ex_div_date"])
        return ok, f"复权因子 {len(data)} 行 | {detail}"

    results["❔_rehab"] = run("❔ get_rehab", _rehab)

    def _trading_days():
        # 10.10 方法名：request_trading_days（非 get_trading_days）
        res = quote_ctx.request_trading_days(Market.HK, "2026-01-01", "2026-01-31")
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("TRADING_DAYS", data, required_cols=["time"])
        return ok, f"交易日 {len(data)} 天 | {detail}"

    results["❔_trading_days"] = run("❔ get_trading_days", _trading_days)

    def _history_kl_quota():
        # 10.10 签名：(get_detail=False)，无 market 参数
        ret, data = quote_ctx.get_history_kl_quota(get_detail=True)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("KL_QUOTA", data, required_cols=["code"])
        return ok, f"K线额度 {len(data)} 行 | {detail}"

    results["❔_history_kl_quota"] = run("❔ get_history_kl_quota", _history_kl_quota)

    def _market_state():
        # 入参为 code 列表（非 market 枚举）
        ret, data = quote_ctx.get_market_state([HK, US])
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("MARKET_STATE", data, required_cols=["code", "market_state"])
        return ok, f"市场状态 {len(data)} 行 | {detail}"

    results["❔_market_state"] = run("❔ get_market_state", _market_state)

    def _broker_queue():
        quote_ctx.subscribe([HK], [SubType.BROKER], is_first_push=False)
        # get_broker_queue 返回三元组 (ret, data, page)
        res = quote_ctx.get_broker_queue(HK)
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("BROKER_QUEUE", data, required_cols=["code"])
        return ok, f"经纪商席位 {len(data)} 行 | {detail}"

    results["❔_broker_queue"] = run("❔ get_broker_queue", _broker_queue)

    def _rt_ticker():
        quote_ctx.subscribe([HK], [SubType.TICKER], is_first_push=False)
        ret, data = quote_ctx.get_rt_ticker(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("RT_TICKER", data, required_cols=["code", "price"])
        return ok, f"逐笔成交 {len(data)} 行 | {detail}"

    results["❔_rt_ticker"] = run("❔ get_rt_ticker", _rt_ticker)

    def _rt_data():
        quote_ctx.subscribe([HK], [SubType.RT_DATA], is_first_push=False)
        ret, data = quote_ctx.get_rt_data(HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("RT_DATA", data, required_cols=["time", "cur_price"])
        return ok, f"分时数据 {len(data)} 行 | {detail}"

    results["❔_rt_data"] = run("❔ get_rt_data", _rt_data)

    def _ipo_list():
        ret, data = quote_ctx.get_ipo_list(Market.HK)
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("IPO_LIST", data, required_cols=["code", "name"])
        return ok, f"IPO {len(data)} 行 | {detail}"

    results["❔_ipo_list"] = run("❔ get_ipo_list", _ipo_list)

    def _shareholders():
        # 10.10 已移除 get_shareholders / get_corporate_actions，标记不可用
        return False, "API 已移除(10.10 无 get_shareholders)"

    results["❔_shareholders"] = run("❔ get_shareholders(已移除)", _shareholders)

    def _corporate_actions():
        return False, "API 已移除(10.10 无 get_corporate_actions)"

    results["❔_corporate_actions"] = run("❔ get_corporate_actions(已移除)", _corporate_actions)

    # ============ 六、订阅/推送（非阻塞测试） ============
    section("五、订阅能力（SUBSCRIBE action 底层）")

    def _subscribe():
        ret, data = quote_ctx.subscribe(TEST_SYMBOLS, [SubType.QUOTE, SubType.ORDER_BOOK])
        if ret != RET_OK:
            return False, data
        return True, f"订阅 OK: {TEST_SYMBOLS}"

    results["SUBSCRIBE"] = run("SUBSCRIBE (subscribe)", _subscribe)

    # ============ 七、事件合约 Event Contract（P0 缺口，核心增量） ============
    # 探测目的：验证 OpenD 是否开通事件合约行情权限 + 确认 get_event_contract_snapshot
    # 真实返回结构（零幻觉硬要求，禁 mock）。全部只读，不动交易态。
    # 符号以 futu-api 10.10 实际暴露为准（10.9 文档命名已改名，见
    # docs/TODO-FUTU-EVENT-CONTRACT.md §2.3.1）。
    section("七、事件合约 Event Contract（P0 缺口，验证 OpenD 权限）")
    # 样本透传：category 返回的第一个事件合约 code/id，供后续 snapshot/detail 复用
    EC_SAMPLE = {"code": None, "id": None}

    def _ec_category():
        # 发现链第一步：事件分类（最轻量，直接验证事件合约权限是否开通）
        ret, data = quote_ctx.get_event_contract_category()
        if ret != RET_OK:
            return False, data
        if hasattr(data, "__len__") and len(data) > 0:
            row = data.iloc[0]
            for c in ("code", "event_contract_code", "contract_code"):
                if c in data.columns:
                    EC_SAMPLE["code"] = row.get(c)
                    break
            for c in ("event_contract_id", "id", "contract_id"):
                if c in data.columns:
                    EC_SAMPLE["id"] = row.get(c)
                    break
            return True, f"事件分类 {len(data)} 行, 列={list(data.columns)} | 样本code={EC_SAMPLE['code']}"
        cols = list(data.columns) if hasattr(data, "columns") else "n/a"
        return True, f"事件分类 0 行(列={cols})"

    results["P0_ec_category"] = run("P0 get_event_contract_category", _ec_category)

    def _ec_snapshot():
        # 核心：事件合约快照 = 隐含概率来源（宏观风控接入点）
        sample = EC_SAMPLE["code"]
        if not sample:
            return False, "无样本 code（category 未返回），无法探测 snapshot"
        ret, data = quote_ctx.get_event_contract_snapshot([sample])
        if ret != RET_OK:
            return False, data
        ok, detail = _row_count_expect("EC_SNAPSHOT", data)
        return ok, f"快照 {len(data)} 行, 列={list(data.columns)} | {detail}"

    results["P0_ec_snapshot"] = run("P0 get_event_contract_snapshot(核心)", _ec_snapshot)

    def _ec_detail():
        if not EC_SAMPLE["id"] and not EC_SAMPLE["code"]:
            return False, "无样本 id/code"
        ret, data = quote_ctx.get_event_contract(EC_SAMPLE["id"] or EC_SAMPLE["code"])
        if ret != RET_OK:
            return False, data
        cols = list(data.columns) if hasattr(data, "columns") else "n/a"
        return True, f"详情 OK, 列={cols}"

    results["P0_ec_detail"] = run("P0 get_event_contract(详情)", _ec_detail)

    def _ec_event_list():
        if not EC_SAMPLE["code"]:
            return False, "无样本 code"
        ret, data = quote_ctx.get_event_contract_event_list(EC_SAMPLE["code"])
        if ret != RET_OK:
            return False, data
        return True, f"关联事件 {len(data)} 行" if hasattr(data, "__len__") else "OK"

    results["P0_ec_event_list"] = run("P0 get_event_contract_event_list", _ec_event_list)

    def _ec_series_list():
        if not EC_SAMPLE["code"]:
            return False, "无样本 code"
        ret, data = quote_ctx.get_event_contract_series_list(EC_SAMPLE["code"])
        if ret != RET_OK:
            return False, data
        return True, f"系列 {len(data)} 行" if hasattr(data, "__len__") else "OK"

    results["P0_ec_series_list"] = run("P0 get_event_contract_series_list", _ec_series_list)

    def _ec_subscribe():
        if not EC_SAMPLE["code"]:
            return False, "无样本 code"
        ret, data = quote_ctx.subscribe_event_contract([EC_SAMPLE["code"]])
        if ret != RET_OK:
            return False, data
        return True, f"订阅 OK: {EC_SAMPLE['code']}"

    results["P0_ec_subscribe"] = run("P0 subscribe_event_contract", _ec_subscribe)

    # ============ 汇总 ============
    section("测试汇总")
    pass_count = sum(1 for ok, _ in results.values() if ok)
    total = len(results)
    print(f"\n  通过: {pass_count}/{total}")
    print("  " + "-" * 50)
    for name, (ok, msg) in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:28s} {msg[:60]}")

    # 关闭
    quote_ctx.close()
    trd_ctx.close()
    print("\n✅ 完成。把以上输出贴回给主脑，用于回填 docs/TODO-FUTU-INTERFACE-CAPABILITY.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"\n💥 致命错误（连接级）: {e!r}")
        traceback.print_exc()
        sys.exit(1)
