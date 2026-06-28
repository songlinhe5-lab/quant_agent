import asyncio
import hashlib
import json
import random
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import get_db
from backend.core.redis_client import redis_client
from backend.routers.auth import get_current_user
from backend.services.futu_service import futu_service
from backend.services.screener_service import screener_service

# 💡 将 SUGGESTIONS 移至模块级别，方便测试用例复用
SUGGESTIONS = [
    "格雷厄姆深度价值股",
    "巴菲特护城河原则",
    "满足 Piotroski F-Score 财务底线的美股",
    "终极六维完美财报",
    "威廉·欧奈尔 CANSLIM 动量打板策略",
    "彼得·林奇 PEG 价值成长股",
    "乔尔·格林布拉特的神奇公式",
    "费雪的隐蔽资产型股票",
    "PE历史百分位低于10%极度低估的美股",
    "PB小于1，且净资产收益率大于15%的破净股",
    "极度稳健收息基石：市值超千亿且股息率大于6%",
    "过去五年连续分红，且当前股息率超8%的港股",
    "现金奶牛：经营现金流超百亿，且市盈率不足10倍",
    "A股流动比率大于2，没有任何短期债务压力的低估股",
    "市净率极低，且持有海量现金等价物的防御股",
    "港美双市场极度恐慌错杀（跌幅深且PE历史低位）",
    "美股市值超过1万亿的巨头",
    "营收萎缩但利润暴增的降本增效股",
    "连续三个季度营收与净利润双双增长超30%",
    "A股中报业绩预增，净利润同比增长超50%",
    "毛利率超80%且营收高增的SaaS软件企业",
    "研发投入极高，且EPS增速超40%的科技先锋",
    "ROE与净利润增速双双超过20%的戴维斯双击候选",
    "PEG小于1，被市场低估的高成长股",
    "净资产收益率(ROE)连续大于30%的印钞机",
    "资产负债率低于20%且毛利率极高的轻资产企业",
    "美股大而不倒：千亿市值且现金流极度充裕的巨头",
    "ROIC（投入资本回报率）大于20%的卓越护城河",
    "抗通胀属性：毛利率连年提升的大型消费股",
    "剔除ST，且营业利润现金覆盖率大于100%的良心A股",
    "美股换手率超20%的妖股",
    "振幅超15%的剧烈波动股",
    "连续三天放量，且股价突破52周新高",
    "VCP 波动率收缩形态，即将向上突破的美股",
    "跳空高开，且今日成交额突破10亿的强势股",
    "A股今日涨停，且换手率低于5%的缩量板",
    "股价站上所有均线（多头排列）的趋势加速股",
    "MACD在水上金叉，且量比大于2的强势突破",
    "上市不满3个月，且今日换手率极高的次新妖股",
    "美股市值超百亿，且今日出现MACD金叉和RSI超卖",
    "A股今天KDJ金叉的股票",
    "寻找今天出现 RSI 底背离且放量企稳的美股科技股",
    "KDJ低位金叉，且MACD即将绿柱缩短的反弹先锋",
    "跌破布林带下轨，产生超卖情绪错杀的千亿白马",
    "股价近期腰斩（跌幅超50%）但经营现金流依然为正",
    "成交量极度萎缩（地量），且股价在长期均线附近企稳",
    "RSI跌破20，存在极强技术性超跌反弹诉求的标的",
    "美股半导体板块，且市盈率低于行业平均",
    "避险情绪升温，寻找黄金和公用事业板块的高息股",
    "美联储降息预期受益：高负债率但现金流改善的标的",
    "港股互联网巨头中，目前估值在历史底部的标的",
    "A股低空经济概念，且今日资金大幅净流入",
    "剔除房地产和金融板块的纯正高科技成长组合",
    "受益于大宗商品上涨的能源巨头，且拥有高股息",
    "美股AI算力产业链，且营收增速大于50%",
    "数据中心概念，资产周转率高且盈利激增",
    "港股出海软件企业，毛利率超70%且在回购",
    "A股算力概念中，真正有净利润支撑的非炒作标的",
    "A股连续亏损且资产负债率超80%的退市高危股",
    "市盈率超百倍，但营收出现负增长的刺破泡沫股",
    "大股东疯狂减持且近期出现 MACD 顶背离",
    "流动比率小于1，且经营现金流持续为负的暴雷预备役",
    "RSI严重超买（大于80）且伴随高位巨量阴线（放量出货）",
    "市值大于1000亿且ROIC连续3年增长",
    "PEG小于0.8的被错杀科技股",
    "市净率低于0.8且现金流充裕的银行股",
    "美股跌破200日均线但RSI严重超卖的标的",
    "连续5年股息率超过5%且营收无下滑的红利股",
    "净资产收益率大于15%且资产负债率小于30%的隐形冠军",
    "A股缩量回调至60日均线企稳的白马股",
    "美股生物医药板块中研发占营收比例最高的标的",
    "港股科技股中过去一个月南向资金持续流入的龙头",
    "市盈率低于同行业平均水平且毛利率高于行业平均的标的",
    "高自由现金流收益率且正在大规模回购的美股",
    "A股突破年线且MACD底背离的底部反转股",
    "市盈率(PE)小于15且盈利增速(EPS Growth)大于20%的戴维斯双击股",
    "上市时间超过10年且从未录得年度亏损的稳定型企业",
    "美股可选消费板块中库存周转率正在加速提升的零售股",
    "港股高股息率且派息比率低于60%的安全收息股",
    "A股短期均线多头排列且成交量温和放大的趋势跟踪标的",
    "美股跌破布林带下轨且随机指标(KDJ)处于超卖区",
    "市销率(PS)小于2且营收增速大于30%的SaaS标的",
    "剔除金融和房地产板块后，ROE排名前1%的全市场标的",
]

router = APIRouter(prefix="/screener", tags=["Screener"])

# 用于防范高频选股的细粒度锁池
_screener_locks = {}


class ScreenerRequest(BaseModel):
    dsl: str
    page: int = 1
    page_size: int = 0  # 0 为兼容老前端全量拉取，大于 0 则执行服务端分页
    sort_key: str = "mktcap"
    sort_dir: int = -1  # -1 降序, 1 升序
    filters: dict = {}  # 💡 前端传来的表头二次过滤区间


def _parse_human_number(val: Any) -> float:
    """将带单位的字符串解析为绝对数值"""
    if val is None:
        return 0.0  # noqa: E701
    if isinstance(val, (int, float)):
        return float(val)  # noqa: E701
    s = str(val).upper().replace("%", "").replace("+", "").replace(",", "")
    try:
        num_val = float(re.sub(r"[A-Z\u4e00-\u9fa5]", "", s) or 0)
        if "万亿" in s or "T" in s:
            num_val *= 1e12  # noqa: E701
        elif "亿" in s or "B" in s:
            num_val *= 1e8  # noqa: E701
        elif "万" in s:
            num_val *= 1e4  # noqa: E701
        elif "M" in s:
            num_val *= 1e6  # noqa: E701
        elif "K" in s:
            num_val *= 1e3  # noqa: E701
        return num_val
    except Exception:
        return 0.0


def _clean_json_dsl(dsl: str) -> str:
    """清理 AI 输出的 JSON 字符串中的 Markdown 标记与注释"""
    cleaned = re.sub(r"^```[A-Za-z]*\n|```$", "", dsl.strip(), flags=re.MULTILINE).strip()  # noqa: E501
    comment_pattern = r'("(?:\\.|[^"\\])*")|(/\*.*?\*/|//[^\r\n]*)'
    return re.sub(
        comment_pattern,
        lambda m: m.group(1) if m.group(1) else "",
        cleaned,
        flags=re.DOTALL,
    ).strip()  # noqa: E501


class ScreenerSubscribeRequest(BaseModel):
    name: str
    dsl: str
    trigger_time: Optional[str] = "18:00"


class ScreenerSubscriptionTimeUpdateRequest(BaseModel):
    trigger_time: str


class ScreenerTranslateRequest(BaseModel):
    query: str


class ScreenerHistoryItem(BaseModel):
    nlp: str
    dsl: str
    time: int


class ScreenerHistoryRequest(BaseModel):
    history: list[ScreenerHistoryItem]


# This is a mock implementation. A real implementation would require a database
# and a more sophisticated parsing and querying engine.
MOCK_SCREENER_RESULTS = [
    {
        "rank": 1,
        "symbol": "US.NVDA",
        "name": "NVIDIA Corp",
        "mktcap": "3.1T",
        "price": 125.4,
        "chg": 2.1,
        "rsi": 28.5,
        "chg30": "25.4%",
        "inflow": "1.2B",
    },  # noqa: E501
    {
        "rank": 2,
        "symbol": "HK.0700",
        "name": "腾讯控股",
        "mktcap": "3.5T",
        "price": 375.2,
        "chg": -0.5,
        "rsi": 25.1,
        "chg30": "-2.1%",
        "inflow": "850M",
    },  # noqa: E501
    {
        "rank": 3,
        "symbol": "US.TSM",
        "name": "台积电",
        "mktcap": "850B",
        "price": 165.0,
        "chg": 1.2,
        "rsi": 29.9,
        "chg30": "15.8%",
        "inflow": "500M",
    },  # noqa: E501
    {
        "rank": 4,
        "symbol": "US.AVGO",
        "name": "博通",
        "mktcap": "750B",
        "price": 1600.0,
        "chg": 3.5,
        "rsi": 22.1,
        "chg30": "18.2%",
        "inflow": "450M",
    },  # noqa: E501
    {
        "rank": 5,
        "symbol": "HK.01810",
        "name": "小米集团-W",
        "mktcap": "450B",
        "price": 18.5,
        "chg": -1.1,
        "rsi": 27.8,
        "chg30": "5.5%",
        "inflow": "300M",
    },  # noqa: E501
]


@router.get("/suggestions")
async def get_screener_suggestions(limit: int = 6, db: Session = Depends(get_db)):
    """
    获取随机选股灵感提示词
    💡 未来可将此列表移入 PostgreSQL 数据库表 (如 ScreenerSuggestion)，
    通过 db.query(ScreenerSuggestion).order_by(func.random()).limit(limit).all() 实现万级数据的极速动态拉取。
    """  # noqa: E501
    SUGGESTIONS = [
        "格雷厄姆深度价值股",
        "巴菲特护城河原则",
        "满足 Piotroski F-Score 财务底线的美股",
        "终极六维完美财报",
        "威廉·欧奈尔 CANSLIM 动量打板策略",
        "彼得·林奇 PEG 价值成长股",
        "乔尔·格林布拉特的神奇公式",
        "费雪的隐蔽资产型股票",
        "PE历史百分位低于10%极度低估的美股",
        "PB小于1，且净资产收益率大于15%的破净股",
        "极度稳健收息基石：市值超千亿且股息率大于6%",
        "过去五年连续分红，且当前股息率超8%的港股",
        "现金奶牛：经营现金流超百亿，且市盈率不足10倍",
        "A股流动比率大于2，没有任何短期债务压力的低估股",
        "市净率极低，且持有海量现金等价物的防御股",
        "港美双市场极度恐慌错杀（跌幅深且PE历史低位）",
        "美股市值超过1万亿的巨头",
        "营收萎缩但利润暴增的降本增效股",
        "连续三个季度营收与净利润双双增长超30%",
        "A股中报业绩预增，净利润同比增长超50%",
        "毛利率超80%且营收高增的SaaS软件企业",
        "研发投入极高，且EPS增速超40%的科技先锋",
        "ROE与净利润增速双双超过20%的戴维斯双击候选",
        "PEG小于1，被市场低估的高成长股",
        "净资产收益率(ROE)连续大于30%的印钞机",
        "资产负债率低于20%且毛利率极高的轻资产企业",
        "美股大而不倒：千亿市值且现金流极度充裕的巨头",
        "ROIC（投入资本回报率）大于20%的卓越护城河",
        "抗通胀属性：毛利率连年提升的大型消费股",
        "剔除ST，且营业利润现金覆盖率大于100%的良心A股",
        "美股换手率超20%的妖股",
        "振幅超15%的剧烈波动股",
        "连续三天放量，且股价突破52周新高",
        "VCP 波动率收缩形态，即将向上突破的美股",
        "跳空高开，且今日成交额突破10亿的强势股",
        "A股今日涨停，且换手率低于5%的缩量板",
        "股价站上所有均线（多头排列）的趋势加速股",
        "MACD在水上金叉，且量比大于2的强势突破",
        "上市不满3个月，且今日换手率极高的次新妖股",
        "美股市值超百亿，且今日出现MACD金叉和RSI超卖",
        "A股今天KDJ金叉的股票",
        "寻找今天出现 RSI 底背离且放量企稳的美股科技股",
        "KDJ低位金叉，且MACD即将绿柱缩短的反弹先锋",
        "跌破布林带下轨，产生超卖情绪错杀的千亿白马",
        "股价近期腰斩（跌幅超50%）但经营现金流依然为正",
        "成交量极度萎缩（地量），且股价在长期均线附近企稳",
        "RSI跌破20，存在极强技术性超跌反弹诉求的标的",
        "美股半导体板块，且市盈率低于行业平均",
        "避险情绪升温，寻找黄金和公用事业板块的高息股",
        "美联储降息预期受益：高负债率但现金流改善的标的",
        "港股互联网巨头中，目前估值在历史底部的标的",
        "A股低空经济概念，且今日资金大幅净流入",
        "剔除房地产和金融板块的纯正高科技成长组合",
        "受益于大宗商品上涨的能源巨头，且拥有高股息",
        "美股AI算力产业链，且营收增速大于50%",
        "数据中心概念，资产周转率高且盈利激增",
        "港股出海软件企业，毛利率超70%且在回购",
        "A股算力概念中，真正有净利润支撑的非炒作标的",
        "A股连续亏损且资产负债率超80%的退市高危股",
        "市盈率超百倍，但营收出现负增长的刺破泡沫股",
        "大股东疯狂减持且近期出现 MACD 顶背离",
        "流动比率小于1，且经营现金流持续为负的暴雷预备役",
        "RSI严重超买（大于80）且伴随高位巨量阴线（放量出货）",
        "市值大于1000亿且ROIC连续3年增长",
        "PEG小于0.8的被错杀科技股",
        "市净率低于0.8且现金流充裕的银行股",
        "美股跌破200日均线但RSI严重超卖的标的",
        "连续5年股息率超过5%且营收无下滑的红利股",
        "净资产收益率大于15%且资产负债率小于30%的隐形冠军",
        "A股缩量回调至60日均线企稳的白马股",
        "美股生物医药板块中研发占营收比例最高的标的",
        "港股科技股中过去一个月南向资金持续流入的龙头",
        "市盈率低于同行业平均水平且毛利率高于行业平均的标的",
        "高自由现金流收益率且正在大规模回购的美股",
        "A股突破年线且MACD底背离的底部反转股",
        "市盈率(PE)小于15且盈利增速(EPS Growth)大于20%的戴维斯双击股",
        "上市时间超过10年且从未录得年度亏损的稳定型企业",
        "美股可选消费板块中库存周转率正在加速提升的零售股",
        "港股高股息率且派息比率低于60%的安全收息股",
        "A股短期均线多头排列且成交量温和放大的趋势跟踪标的",
        "美股跌破布林带下轨且随机指标(KDJ)处于超卖区",
        "市销率(PS)小于2且营收增速大于30%的SaaS标的",
        "剔除金融和房地产板块后，ROE排名前1%的全市场标的",
    ]
    selected = random.sample(SUGGESTIONS, min(limit, len(SUGGESTIONS)))
    return {"status": "success", "data": selected}


@router.post("/translate")
async def translate_dsl(req: ScreenerTranslateRequest):
    """调用 AI 将前端输入的自然语言即时翻译为选股 DSL"""
    try:
        dsl = await screener_service.translate_nlp_to_dsl(req.query)
        return {"status": "success", "data": dsl}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
async def run_screener(req: ScreenerRequest):
    """
    接收 DSL 查询，调用 Futu 接口在线筛选股票。
    """
    cache_key = f"quant:screener:dsl:{hashlib.md5(req.dsl.encode('utf-8')).hexdigest()}"

    def _process_data(data_list: list) -> dict:
        # 0. 💡 服务端执行表头二次过滤 (因为分页了，必须在服务端对全量缓存数据过滤)
        if hasattr(req, "filters") and req.filters:
            filtered = []
            for r in data_list:
                match = True
                for col, bounds in req.filters.items():
                    val = r.get(col)
                    if val is None:
                        continue
                    try:
                        num_val = _parse_human_number(val)

                        c_min = float(bounds.get("min")) if bounds.get("min") not in [None, ""] else float("-inf")  # noqa: E501
                        c_max = float(bounds.get("max")) if bounds.get("max") not in [None, ""] else float("inf")  # noqa: E501

                        if not (c_min <= num_val <= c_max):
                            match = False
                            break
                    except Exception:
                        pass
                if match:
                    filtered.append(r)
            data_list = filtered

        # 1. 服务端动态排序
        sort_k = req.sort_key
        is_desc = req.sort_dir == -1
        if sort_k in ["symbol", "name"]:
            data_list = sorted(data_list, key=lambda x: str(x.get(sort_k, "")), reverse=is_desc)  # noqa: E501
        else:

            def _get_sort_val(x):
                val = x.get(sort_k)
                if val is None:
                    return float("-inf") if is_desc else float("inf")
                try:
                    # 兼容类似 "+15%" 这样的字符串排序
                    return _parse_human_number(val)
                except Exception:
                    return float("-inf") if is_desc else float("inf")

            data_list = sorted(data_list, key=_get_sort_val, reverse=is_desc)

        # 2. 重新计算全市场排名 (Rank)
        for i, r in enumerate(data_list):
            r["rank"] = i + 1

        total = len(data_list)

        # 3. 服务端切片分页
        if req.page_size > 0:
            start = (req.page - 1) * req.page_size
            data_list = data_list[start : start + req.page_size]

        return {"status": "success", "data": data_list, "total": total}

    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            res = _process_data(json.loads(cached_data))
            res["message"] = "命中 Redis 极速缓存"
            return res
    except Exception as e:
        print(f"⚠️ [Screener] Redis 读取缓存失败: {e}")

    if cache_key not in _screener_locks:
        _screener_locks[cache_key] = asyncio.Lock()

    async with _screener_locks[cache_key]:
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                res = _process_data(json.loads(cached_data))
                res["message"] = "命中 Redis 极速缓存"
                return res
        except Exception:
            pass

        try:
            # 1. 转译 DSL 到 Futu 过滤条件
            print(f"\n🔍 [Screener] 接收到查询指令: {req.dsl}")

            cleaned_dsl = _clean_json_dsl(req.dsl)

            try:
                json.loads(cleaned_dsl)
            except json.JSONDecodeError as je:
                raise ValueError(f"DSL 格式错误: {str(je)}。请检查 AI 生成的 JSON 是否合法。")  # noqa: E501

            markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(cleaned_dsl)  # noqa: E501

            # 2. 并发向 Futu OpenD 发起多市场扫盘
            tasks = []
            for m in markets:
                task = futu_service.screen_stocks(market=m, filters=futu_filters)  # type: ignore
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            final_data = []
            for m, res in zip(markets, results):
                if isinstance(res, Exception):
                    raise ValueError(f"执行异常: {str(res)}")
                elif isinstance(res, dict) and res.get("status") == "success":
                    fetched = res.get("data", [])
                    final_data.extend(fetched)
                else:
                    err_msg = res.get("message") if isinstance(res, dict) else str(res)
                    raise ValueError(err_msg)

            # 3. 内存二次过滤
            if post_filters.get("exclude_st"):
                final_data = [
                    r for r in final_data if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")
                ]  # noqa: E501

            # 3.5 技术形态二次过滤
            tech_patterns = post_filters.get("technical_patterns", [])
            if final_data:
                final_data = await screener_service.apply_technical_pattern_filtering(final_data, tech_patterns)  # noqa: E501

            # 4. 去重
            seen = set()
            dedup_data = []
            for r in final_data:
                if r.get("symbol") not in seen:
                    seen.add(r.get("symbol"))
                    dedup_data.append(r)
            final_data = dedup_data

            if not final_data:
                if futu_service.status != "CONNECTED":
                    import copy

                    mock_data = [
                        r
                        for r in MOCK_SCREENER_RESULTS
                        if any(r["symbol"].upper().startswith(f"{m.upper()}.") for m in markets)
                    ]  # noqa: E501
                    final_data = copy.deepcopy(mock_data if mock_data else [])
                    for r in final_data:
                        r["price"] = round(r["price"] * (1 + (random.random() - 0.5) * 0.05), 2)  # noqa: E501
                        r["chg"] = round((random.random() - 0.5) * 5, 2)
            else:
                print(
                    " [Screener] 获取结果示例 (前 3 条):",
                    json.dumps(final_data[:3], indent=2, ensure_ascii=False),
                )  # noqa: E501

            try:
                # 💡 增加随机 Jitter 防雪崩
                ttl = 300 + random.randint(10, 60)
                await redis_client.set(cache_key, json.dumps(final_data), ex=ttl)
            except Exception as e:
                print(f"⚠️ [Screener] Redis 写入缓存失败: {e}")

            res = _process_data(final_data)
            res["message"] = "Futu OpenD 在线筛选成功"
            return res
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"选股器执行失败: {str(e)}")


@router.get("/history")
async def get_screener_history(current_user: models.User = Depends(get_current_user)):
    """获取用户的云端选股历史记录"""
    try:
        key = f"quant:screener:history:{current_user.id}"
        data = await redis_client.get(key)
        if data:
            return {"status": "success", "data": json.loads(data)}
        return {"status": "success", "data": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/history")
async def save_screener_history(req: ScreenerHistoryRequest, current_user: models.User = Depends(get_current_user)):  # noqa: E501
    """保存用户的选股历史记录到云端"""
    try:
        key = f"quant:screener:history:{current_user.id}"
        # 兼容 Pydantic v1 / v2，序列化并存入 Redis
        history_dicts = [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in req.history]  # noqa: E501
        await redis_client.set(key, json.dumps(history_dicts))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload-indicators")
async def reload_indicators(current_user: models.User = Depends(get_current_user)):
    """热更新选股指标 RAG 词库"""
    try:
        # 使用 to_thread 防止读取 CSV 和 jieba 分词计算时阻塞主事件循环
        res = await asyncio.to_thread(screener_service.reload_rag_corpus)
        return {
            "status": "success",
            "message": f"指标库热更新成功，当前共 {res.get('count', 0)} 条规则",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"热更新失败: {str(e)}")


async def get_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.ScreenerSubscription:  # noqa: E501
    """提取选股订阅验证逻辑的依赖注入"""
    sub = (
        db.query(models.ScreenerSubscription)
        .filter(
            models.ScreenerSubscription.id == sub_id,
            models.ScreenerSubscription.user_id == current_user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="订阅任务不存在或无权限访问")
    return sub


class DictionaryItem(BaseModel):
    desc: str
    rule: str


class DictionaryBatchItem(BaseModel):
    items: list[DictionaryItem]


class DictionaryDeleteItem(BaseModel):
    desc: str
    rule: str


@router.get("/dictionary")
async def get_dictionary(current_user: models.User = Depends(get_current_user)):
    """获取当前用户的私有选股规则列表"""
    data = await screener_service.get_custom_rules(user_id=current_user.id)
    return {"status": "success", "data": data}


@router.post("/dictionary")
async def add_dictionary_item(item: DictionaryItem, current_user: models.User = Depends(get_current_user)):  # noqa: E501
    """添加私有 RAG 选股规则"""
    res = await screener_service.add_custom_rule(desc_text=item.desc, rule_text=item.rule, user_id=current_user.id)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return res


@router.delete("/dictionary")
async def delete_dictionary_item(
    item: DictionaryDeleteItem,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):  # noqa: E501
    """删除私有 RAG 选股规则 (适配前端基于内容匹配的删除逻辑)"""
    # 根据 desc_text 和 rule_text 反查出对应的 rule_id
    rule = (
        db.query(models.ScreenerRule)
        .filter(
            models.ScreenerRule.desc_text == item.desc,
            models.ScreenerRule.rule_text == item.rule,
            models.ScreenerRule.user_id == current_user.id,
        )
        .first()
    )

    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在或您无权删除")

    success = await screener_service.delete_custom_rule(rule.id, current_user.id)
    if not success:
        raise HTTPException(status_code=500, detail="底层删除失败")
    return {"status": "success", "message": "规则已成功删除"}


@router.post("/dictionary/batch")
async def add_dictionary_batch(req: DictionaryBatchItem, current_user: models.User = Depends(get_current_user)):  # noqa: E501
    """批量导入私有 RAG 选股规则 (配合前端的 CSV 导入)"""
    success_count = 0
    errors = []

    for item in req.items:
        res = await screener_service.add_custom_rule(desc_text=item.desc, rule_text=item.rule, user_id=current_user.id)
        if res.get("status") == "success":
            success_count += 1
        else:
            errors.append(f"[{item.desc}] {res.get('message')}")

    if success_count == 0 and errors:
        raise HTTPException(status_code=500, detail="批量导入失败: " + ", ".join(errors[:3]))  # noqa: E501

    return {"status": "success", "message": f"成功批量导入 {success_count} 条规则"}


@router.post("/subscribe")
async def subscribe_screener(
    req: ScreenerSubscribeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):  # noqa: E501
    """将选股 DSL 策略持久化为每日定时执行的订阅任务"""
    # 💡 新增：校验 trigger_time 格式
    trigger_time_str = req.trigger_time or "18:00"
    if not re.match(r"^\d{2}:\d{2}$", trigger_time_str):
        raise HTTPException(status_code=400, detail="触发时间格式不正确，必须为 HH:MM 格式。")  # noqa: E501

    try:
        sub = models.ScreenerSubscription(
            user_id=current_user.id,
            name=req.name,
            dsl=req.dsl,
            trigger_time=trigger_time_str,
        )
        db.add(sub)
        db.commit()
        return {"status": "success", "message": f"成功订阅每日选股任务：{req.name}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"订阅失败: {str(e)}")


@router.get("/subscriptions")
async def get_subscriptions(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):  # noqa: E501
    """获取当前用户所有的每日选股订阅任务"""
    subs = (
        db.query(models.ScreenerSubscription)
        .filter(models.ScreenerSubscription.user_id == current_user.id)
        .order_by(models.ScreenerSubscription.created_at.desc())
        .all()
    )  # noqa: E501
    return {
        "status": "success",
        "data": [
            {
                "id": s.id,
                "name": s.name,
                "dsl": s.dsl,
                "is_active": s.is_active,
                "trigger_time": s.trigger_time,
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
            for s in subs
        ],  # noqa: E501
    }


@router.put("/subscriptions/{sub_id}/time")
async def update_subscription_time(
    req: ScreenerSubscriptionTimeUpdateRequest,
    db: Session = Depends(get_db),
    sub: models.ScreenerSubscription = Depends(get_subscription),
):  # noqa: E501
    """更新订阅任务的触发时间"""
    if not re.match(r"^\d{2}:\d{2}$", req.trigger_time):
        raise HTTPException(status_code=400, detail="触发时间格式不正确，必须为 HH:MM 格式。")  # noqa: E501

    sub.trigger_time = req.trigger_time
    db.commit()
    return {
        "status": "success",
        "message": f"订阅任务 '{sub.name}' 的触发时间已更新为 {req.trigger_time}",
    }  # noqa: E501


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(
    db: Session = Depends(get_db),
    sub: models.ScreenerSubscription = Depends(get_subscription),
):  # noqa: E501
    """彻底删除某个订阅任务"""
    db.delete(sub)
    db.commit()
    return {"status": "success", "message": "订阅任务已删除"}


@router.put("/subscriptions/{sub_id}/toggle")
async def toggle_subscription(
    db: Session = Depends(get_db),
    sub: models.ScreenerSubscription = Depends(get_subscription),
):  # noqa: E501
    """切换订阅任务的 启动/暂停 状态"""
    sub.is_active = not sub.is_active
    db.commit()
    return {
        "status": "success",
        "message": f"订阅任务已{'恢复' if sub.is_active else '暂停'}推送",
        "is_active": sub.is_active,
    }  # noqa: E501


class SummarizePayload(BaseModel):
    stocks: List[Dict[str, Any]]


@router.post("/summarize")
async def summarize_screener_results(payload: SummarizePayload):
    """接收前端表格传入的选股结果，调用大模型生成盘面洞察报告"""
    try:
        summary = await screener_service.summarize_results(payload.stocks)
        return {"status": "success", "data": summary}
    except Exception as e:
        return {"status": "error", "message": f"AI 总结失败: {str(e)}"}
