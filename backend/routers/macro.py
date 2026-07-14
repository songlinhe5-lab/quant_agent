import asyncio
import hashlib
import json
import random
import re

try:
    import zoneinfo
except ImportError:
    zoneinfo = None
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from backend.app.market_data import market_data
from backend.core import models
from backend.core.database import get_db
from backend.core.redis_client import redis_client
from backend.services.llm_service import llm_service
from backend.services.market_engine import manager

router = APIRouter(prefix="/macro", tags=["Macro Calendar"])

# 用于防范缓存击穿的异步细粒度锁池
_macro_locks = {}


def _fallback_mock_macro() -> dict:
    return {
        "status": "warning",
        "message": "宏观日历获取失败 (请检查 FINNHUB_API_KEY)，使用离线 Mock 数据",
        "data": [
            {
                "date": "2026-05-27T18:00:00Z",
                "country": "US",
                "event": "Fed Interest Rate Decision",
                "impact": "high",
                "previous": 4.50,
                "estimate": 4.50,
                "actual": None,
            },  # noqa: E501
            {
                "date": "2026-05-29T03:00:00Z",
                "country": "JP",
                "event": "BOJ Core CPI YoY",
                "impact": "high",
                "previous": 2.1,
                "estimate": 2.3,
                "actual": None,
            },  # noqa: E501
        ],
    }


async def _fetch_macro_calendar_data(days_ahead: int, force_refresh: bool = False, days_back: int = 0) -> dict:  # noqa: E501
    cache_key = f"macro_calendar_akshare_{days_ahead}_{days_back}"
    if not force_refresh:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    if cache_key not in _macro_locks:
        _macro_locks[cache_key] = asyncio.Lock()

    async with _macro_locks[cache_key]:
        # 💡 双重检查锁 (DCL)：挡住排队等锁的其余并发请求，防止集体击穿
        if not force_refresh:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)

        today = datetime.now(timezone.utc)
        try:
            res = await market_data.get_economic_calendar_ak(days_ahead, days_back=days_back, skip_cache=force_refresh)  # noqa: E501
            if res.get("status") == "error" or not res.get("data"):
                print("⚠️ [Macro] 金十数据降级失败或为空，继续安全降级 (FRED)...")
                res = await market_data.get_economic_calendar_fred(
                    days_ahead, days_back=days_back, skip_cache=force_refresh
                )  # noqa: E501
                if res.get("status") == "error" or not res.get("data"):
                    print("⚠️ [Macro] FRED 降级失败，使用离线 Mock 数据")
                    return _fallback_mock_macro()

            events = res.get("data", [])
            compressed_events = []
            is_fred = res.get("source") == "fred"
            is_jin10 = res.get("source") == "jin10"

            for row in events:
                event_name = str(row.get("event", ""))
                raw_time = str(row.get("time", ""))
                if len(raw_time) == 10:  # 处理只有日期没有时间的情况
                    raw_time += " 08:30:00"

                # 💡 时区修复：FRED 数据是美东时间，需要借助 zoneinfo (自动处理夏令时) 转换为真实的 UTC 发给前端  # noqa: E501
                if is_fred and raw_time and len(raw_time) == 19:
                    try:
                        dt_ny = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                        if zoneinfo:
                            dt_ny = dt_ny.replace(tzinfo=zoneinfo.ZoneInfo("America/New_York"))  # noqa: E501
                            iso_time = dt_ny.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E501
                        else:
                            # 兜底：环境不支持 zoneinfo，直接附带美东时区后缀 -05:00
                            iso_time = raw_time.replace(" ", "T") + "-05:00"
                    except Exception:
                        iso_time = raw_time.replace(" ", "T") + "Z"
                elif is_jin10 and raw_time and len(raw_time) >= 16:
                    try:
                        # 💡 金十数据是北京时间 (东八区)，转换为真实的 UTC 发给前端
                        dt_cn = datetime.strptime(raw_time[:19], "%Y-%m-%d %H:%M:%S")
                        if zoneinfo:
                            dt_cn = dt_cn.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Shanghai"))  # noqa: E501
                            iso_time = dt_cn.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E501
                        else:
                            iso_time = raw_time.replace(" ", "T") + "+08:00"
                    except Exception:
                        iso_time = raw_time.replace(" ", "T") + "Z"
                else:
                    iso_time = raw_time.replace(" ", "T") + "Z" if raw_time else today.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E501

                impact = str(row.get("impact", "low")).lower()
                # 💡 增加中文核心指标及中国央行(PBOC)专项识别，确保 LPR/MLF 及降准降息数据能被正确打上高危红色预警标签  # noqa: E501
                high_impact_keywords = [
                    "rate",
                    "cpi",
                    "gdp",
                    "payroll",
                    "employment",
                    "nfp",
                    "fed",
                    "ecb",
                    "boj",
                    "fomc",
                    "pmi",
                    "ism",
                    "claims",
                    "利率",
                    "决议",
                    "非农",
                    "失业",
                    "通胀",
                    "国内生产总值",
                    "pce",
                    "lpr",
                    "mlf",
                    "pboc",
                    "降息",
                    "降准",
                    "准备金",
                ]  # noqa: E501
                is_core_event = any(k in event_name.lower() for k in high_impact_keywords)  # noqa: E501
                if is_core_event:
                    impact = "high"  # noqa: E701

                # 💡 移除后端的 hard-filter，把所有级别的数据交给前端，让前端的 UI 筛选按钮真正生效  # noqa: E501
                compressed_events.append(
                    {
                        "date": iso_time,
                        "country": str(row.get("country", "Global")),
                        "event": event_name,
                        "impact": impact,
                        "previous": str(row.get("previous", "")),
                        "estimate": str(row.get("estimate", "")),
                        "actual": str(row.get("actual", "")),
                    }
                )  # noqa: E501

            result = {
                "status": "success",
                "time_window": f"Next {len(compressed_events)} High-Impact Events",
                "data": compressed_events,
            }

            # 💡 增加 FRED 数据源的专属前端降级提示
            if res.get("source") == "fred":
                result["message"] = (
                    "💡 宏观日历已降级至 FRED 数据源。受接口限制，暂不提供预期值(Estimate)与实际公布值(Actual)。"  # noqa: E501
                )
            elif res.get("source") == "jin10":
                result["message"] = "💡 宏观日历已平滑降级至金十数据 (Jin10)，支持完整的预期值与中文事件解析。"  # noqa: E501

            # 💡 新增：大模型前瞻推演 (只对即将发生的高危事件进行推演)
            if compressed_events:
                try:
                    # 提取最近的 3 个高危事件喂给大模型
                    upcoming_events = compressed_events[:3]
                    events_info = "\n".join(
                        [f"- {e['date'][:10]}: [{e['country']}] {e['event']}" for e in upcoming_events]
                    )  # noqa: E501

                    # 💡 利用哈希值对大模型推演进行独立长效缓存，防止 force_refresh=true 时反复调用 LLM 造成长达 8 秒的延迟  # noqa: E501
                    events_hash = hashlib.md5(events_info.encode("utf-8")).hexdigest()
                    ai_cache_key = f"quant:macro:ai_deduction:{events_hash}"

                    cached_ai = await redis_client.get(ai_cache_key)
                    if cached_ai:
                        result["ai_deduction"] = (
                            cached_ai.decode("utf-8") if isinstance(cached_ai, bytes) else cached_ai
                        )  # noqa: E501
                    else:
                        prompt = f"你是顶级宏观量化分析师。以下是未来几天即将发布的全球核心宏观经济数据：\n{events_info}\n\n请对这些事件做一次前瞻性预判。挑选最核心的事件，向交易员解释该数据对当前降息预期或经济衰退的影响，以及如果数据异常走高/走低，可能对大盘资产产生怎样的冲击？字数严格控制在150字以内，直接输出精炼的推演结论，无需多余客套话。"  # noqa: E501

                        resp = await llm_service.get_client().chat.completions.create(
                            model=llm_service.get_model(),
                            temperature=0.7,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        content = resp.choices[0].message.content
                        if content:
                            ai_deduction = content.strip()
                            ai_deduction = re.sub(r"^```[a-zA-Z]*\s*", "", ai_deduction)
                            ai_deduction = re.sub(r"\s*```$", "", ai_deduction).strip()
                            result["ai_deduction"] = ai_deduction
                            await redis_client.setex(ai_cache_key, 86400 * 3, ai_deduction)  # 缓存 3 天  # noqa: E501
                except Exception as llm_e:
                    print(f"⚠️ [Macro] LLM 前瞻推演失败: {llm_e}")
                    result["ai_deduction"] = "暂无 AI 前瞻推演"

            if compressed_events:
                # 💡 增加随机 Jitter 防雪崩
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
        except Exception as e:
            print(f"⚠️ [Macro] 数据处理异常: {e}")
            return {"status": "error", "message": str(e)}


async def _fetch_earnings_calendar_data(days_ahead: int, force_refresh: bool = False, days_back: int = 0) -> dict:  # noqa: E501
    """带缓存的大模型财报日历前瞻推演包装器"""
    cache_key = f"macro_earnings_calendar_with_ai_{days_ahead}_{days_back}"
    if not force_refresh:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

    if cache_key not in _macro_locks:
        _macro_locks[cache_key] = asyncio.Lock()

    async with _macro_locks[cache_key]:
        if not force_refresh:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)

        try:
            res = await market_data.get_earnings_calendar(days_ahead, days_back=days_back, skip_cache=force_refresh)  # noqa: E501
            if res.get("status") != "success":
                return res

            earnings_list = res.get("data", [])

            # 💡 添加中文名称映射
            ticker_name_map = {
                "AAPL": "苹果",
                "MSFT": "微软",
                "GOOGL": "谷歌",
                "GOOG": "谷歌",
                "AMZN": "亚马逊",
                "META": "Meta",
                "TSLA": "特斯拉",
                "NVDA": "英伟达",
                "AMD": "AMD",
                "INTC": "英特尔",
                "NFLX": "奈飞",
                "DIS": "迪士尼",
                "BA": "波音",
                "JPM": "摩根大通",
                "V": "Visa",
                "MA": "万事达",
                "WMT": "沃尔玛",
                "COST": "好市多",
                "PYPL": "PayPal",
                "SQ": "Square",
                "UBER": "优步",
                "LYFT": "Lyft",
                "ABNB": "爱彼迎",
                "BABA": "阿里巴巴",
                "JD": "京东",
                "PDD": "拼多多",
                "BIDU": "百度",
                "NIO": "蔚来",
                "XPEV": "小鹏",
                "LI": "理想",
                "TSM": "台积电",
                "ASML": "阿斯麦",
                "AVGO": "博通",
                "QCOM": "高通",
                "TXN": "德州仪器",
                "MU": "美光",
                "CRM": "Salesforce",
                "ADBE": "Adobe",
                "ORCL": "甲骨文",
                "IBM": "IBM",
                "KO": "可口可乐",
                "PEP": "百事可乐",
                "MCD": "麦当劳",
                "SBUX": "星巴克",
                "NKE": "耐克",
                "LULU": "lululemon",
                "TGT": "塔吉特",
                "HD": "家得宝",
                "LLY": "礼来",
                "JNJ": "强生",
                "PFE": "辉瑞",
                "MRNA": "Moderna",
                "XOM": "埃克森美孚",
                "CVX": "雪佛龙",
                "COP": "康菲石油",
                "GS": "高盛",
                "MS": "摩根士丹利",
                "BLK": "贝莱德",
                "BRK.B": "伯克希尔",
                "SPY": "标普500ETF",
                "QQQ": "纳指ETF",
            }
            for item in earnings_list:
                symbol = item.get("symbol", "")
                item["name_cn"] = ticker_name_map.get(symbol, "")

            result = {
                "status": "success",
                "data": earnings_list,
                "source": res.get("source"),
            }  # noqa: E501

            # 💡 新增：大模型财报前瞻推演
            if earnings_list:
                try:
                    upcoming = earnings_list[:3]  # 挑选近期发布财报的3家明星公司
                    info_str = "\n".join(
                        [
                            f"- {e.get('date')}: {e.get('symbol')} (预期 EPS: {e.get('epsEstimate', 'N/A')})"
                            for e in upcoming
                        ]
                    )  # noqa: E501

                    # 💡 同样为财报前瞻进行独立的哈希缓存
                    info_hash = hashlib.md5(info_str.encode("utf-8")).hexdigest()
                    ai_cache_key = f"quant:earnings:ai_deduction:{info_hash}"

                    cached_ai = await redis_client.get(ai_cache_key)
                    if cached_ai:
                        result["ai_deduction"] = (
                            cached_ai.decode("utf-8") if isinstance(cached_ai, bytes) else cached_ai
                        )  # noqa: E501
                    else:
                        prompt = f"你是顶级美股分析师。以下是未来几天即将发布财报的核心明星公司：\n{info_str}\n\n请对这几份财报做一次前瞻推演。重点挑选最知名的一两家，预测其财报超预期或不及预期可能对同板块或纳斯达克指数带来的联动影响。字数严格控制在150字以内，语言犀利、直接，无需多余客套话。"  # noqa: E501

                        resp = await llm_service.get_client().chat.completions.create(
                            model=llm_service.get_model(),
                            temperature=0.7,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        content = resp.choices[0].message.content
                        if content:
                            ai_deduction = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content.strip()).strip()  # noqa: E501
                            result["ai_deduction"] = ai_deduction
                            await redis_client.setex(ai_cache_key, 86400 * 3, ai_deduction)  # 缓存 3 天  # noqa: E501
                except Exception as llm_e:
                    print(f"⚠️ [Macro] 财报前瞻 LLM 推演失败: {llm_e}")
                    result["ai_deduction"] = "暂无财报前瞻推演"

            if earnings_list:
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
        except Exception as e:
            print(f"⚠️ [Macro] 财报日历数据处理异常: {e}")
            return {"status": "error", "message": str(e)}


@router.get("/calendar")
async def get_macro_calendar(
    days_ahead: int = Query(7, ge=0, le=30, description="获取未来 N 天内的高影响宏观经济事件"),  # noqa: E501
    days_back: int = Query(0, ge=0, le=30, description="获取过去 N 天内已公布的宏观经济事件"),  # noqa: E501
):
    """获取全球核心经济体的宏观日历数据 (支持过去和未来)"""
    try:
        result = await _fetch_macro_calendar_data(days_ahead=days_ahead, days_back=days_back)
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 宏观经济序列 (FRED) ───────────────────────────────────────────────────


@router.get("/series")
async def get_macro_series(
    series_id: str = Query(..., description="FRED 经济序列 ID"),
    limit: int = Query(100, le=1000, description="返回的数据点数量"),
):
    """获取 FRED 宏观经济时间序列数据"""
    res = await market_data.get_series_observations(series_id, limit)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


# ── 情绪风向标历史趋势 ──────────────────────────────────────────────────────


@router.get("/sentiment-history")
def get_sentiment_history(
    limit: int = Query(200, le=2000, description="获取历史数据点数量"),
    db: Session = Depends(get_db),
):  # noqa: E501
    """获取情绪风向标历史趋势数据 (P/C Ratio, VIX, Credit Spread)"""
    if not hasattr(models, "SentimentRecord"):
        raise HTTPException(status_code=500, detail="SentimentRecord 数据表尚未初始化")

    try:
        records = db.query(models.SentimentRecord).order_by(models.SentimentRecord.timestamp.desc()).limit(limit).all()  # noqa: E501
        data = []
        # 倒序遍历，使其在图表上从左向右（从旧到新）排列
        for r in reversed(records):
            data.append(
                {
                    "time": r.timestamp.strftime("%m-%d %H:%M") if r.timestamp else "",
                    "pc_ratio": r.pc_ratio,
                    "vix": r.vix_value,
                    "credit_spread": r.credit_spread,
                }
            )
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 跨市场资金流向 ──────────────────────────────────────────────────────────


async def _fetch_capital_flows() -> tuple[list, bool]:
    """获取跨市场资金流向数据（港股南向/北向使用 AKShare，其余 Mock 兜底）"""
    try:
        south_task = market_data.get_southbound_flow()

        # 💡 从后台实时引擎直接读取资金流缓存，避免每次用户请求都被 Futu 的串行限流阻塞 4 秒！  # noqa: E501
        async def _get_flow(ticker: str):
            if ticker in manager.flow_cache:
                return manager.flow_cache[ticker]
            return await market_data.get_fund_flow(ticker)

        csi300_task = _get_flow("SH.510300")
        spy_task = _get_flow("US.SPY")
        qqq_task = _get_flow("US.QQQ")
        soxx_task = _get_flow("US.SOXX")
        tlt_task = _get_flow("US.TLT")
        kweb_task = _get_flow("US.KWEB")

        results = await asyncio.gather(
            south_task,
            csi300_task,
            spy_task,
            qqq_task,
            soxx_task,
            tlt_task,
            kweb_task,
            return_exceptions=True,
        )  # noqa: E501
        south_res = results[0] if isinstance(results[0], dict) else {}
        csi300_res = results[1] if isinstance(results[1], dict) else {}
        spy_res = results[2] if isinstance(results[2], dict) else {}
        qqq_res = results[3] if isinstance(results[3], dict) else {}
        soxx_res = results[4] if isinstance(results[4], dict) else {}
        tlt_res = results[5] if isinstance(results[5], dict) else {}
        kweb_res = results[6] if isinstance(results[6], dict) else {}

        flows = []

        is_market_closed = south_res.get("is_closed", False)

        # 1) 港股南向（AKShare 真实数据）
        if south_res.get("status") in ("success", "warning"):
            sd = south_res.get("data", {})
            flows.append(
                {
                    "market": "HK",
                    "label": "港股南向",
                    "amount": sd.get("net_inflow", 0),
                    "unit": "亿港元",
                    "dir": 1 if sd.get("net_inflow", 0) >= 0 else -1,
                    "desc": "沪深港通净买入港股",
                    "sparkDirs": sd.get("sparkline", [1, 1, -1, 1, 1, 1, -1, 1]),
                    "data_source": "AKShare",  # 💡 数据来源
                    "updated_at": sd.get("updated_at") or datetime.now(timezone.utc).isoformat(),  # 💡 更新时间
                }
            )

        def _parse_futu_flow(res, default_amt, real_desc, unit="亿美元"):
            if isinstance(res, dict) and res.get("status") == "success":
                fund_data = res.get("data", res)
                val = fund_data.get("main_fund_net_inflow", 0.0) / 100_000_000.0
                amt = round(val, 2)
                updated_at = fund_data.get("updated_at") or datetime.now(timezone.utc).isoformat()
                return amt, 1 if amt >= 0 else -1, real_desc, unit, "Futu", updated_at
            return default_amt, 1 if default_amt >= 0 else -1, real_desc, unit, "N/A", None

        # 💡 使用核心 ETF 的主买主卖差额代表板块的整体真实资金流
        csi_amount, csi_dir, csi_desc, csi_unit, csi_source, csi_updated = _parse_futu_flow(
            csi300_res, 8.7, "沪深300ETF主力净流", "亿人民币"
        )  # noqa: E501
        spy_amount, spy_dir, spy_desc, spy_unit, spy_source, spy_updated = _parse_futu_flow(
            spy_res, 2.1, "标普500ETF主力净流", "亿美元"
        )  # noqa: E501
        qqq_amount, qqq_dir, qqq_desc, qqq_unit, qqq_source, qqq_updated = _parse_futu_flow(
            qqq_res, 3.5, "纳指科技ETF主力净流", "亿美元"
        )  # noqa: E501
        soxx_amount, soxx_dir, soxx_desc, soxx_unit, soxx_source, soxx_updated = _parse_futu_flow(
            soxx_res, 1.5, "半导体ETF主力净流", "亿美元"
        )  # noqa: E501
        tlt_amount, tlt_dir, tlt_desc, tlt_unit, tlt_source, tlt_updated = _parse_futu_flow(
            tlt_res, -1.8, "20年期美债ETF主力净流", "亿美元"
        )  # noqa: E501
        kweb_amount, kweb_dir, kweb_desc, kweb_unit, kweb_source, kweb_updated = _parse_futu_flow(
            kweb_res, 1.2, "中概互联ETF主力净流", "亿美元"
        )  # noqa: E501

        flows.extend(
            [
                {
                    "market": "CN",
                    "label": "A股核心",
                    "amount": csi_amount,
                    "unit": "亿人民币",
                    "dir": csi_dir,
                    "desc": csi_desc,
                    "sparkDirs": [1, 1, 1, 1, -1, 1, 1, 1],
                    "data_source": csi_source,
                    "updated_at": csi_updated,
                },  # noqa: E501
                {
                    "market": "US",
                    "label": "美股大盘",
                    "amount": spy_amount,
                    "unit": spy_unit,
                    "dir": spy_dir,
                    "desc": spy_desc,
                    "sparkDirs": [1, 1, 1, -1, 1, 1, 1, 1],
                    "data_source": spy_source,
                    "updated_at": spy_updated,
                },  # noqa: E501
                {
                    "market": "US",
                    "label": "美股科技",
                    "amount": qqq_amount,
                    "unit": qqq_unit,
                    "dir": qqq_dir,
                    "desc": qqq_desc,
                    "sparkDirs": [-1, 1, 1, 1, 1, 1, -1, 1],
                    "data_source": qqq_source,
                    "updated_at": qqq_updated,
                },  # noqa: E501
                {
                    "market": "US",
                    "label": "半导体",
                    "amount": soxx_amount,
                    "unit": soxx_unit,
                    "dir": soxx_dir,
                    "desc": soxx_desc,
                    "sparkDirs": [1, -1, 1, 1, 1, -1, 1, 1],
                    "data_source": soxx_source,
                    "updated_at": soxx_updated,
                },  # noqa: E501
                {
                    "market": "US",
                    "label": "美债避险",
                    "amount": tlt_amount,
                    "unit": tlt_unit,
                    "dir": tlt_dir,
                    "desc": tlt_desc,
                    "sparkDirs": [-1, -1, -1, 1, -1, -1, -1, -1],
                    "data_source": tlt_source,
                    "updated_at": tlt_updated,
                },  # noqa: E501
                {
                    "market": "CN",
                    "label": "中概互联",
                    "amount": kweb_amount,
                    "unit": kweb_unit,
                    "dir": kweb_dir,
                    "desc": kweb_desc,
                    "sparkDirs": [1, -1, 1, -1, 1, -1, 1, 1],
                    "data_source": kweb_source,
                    "updated_at": kweb_updated,
                },  # noqa: E501
            ]
        )

        return flows, is_market_closed
    except Exception as e:
        print(f"⚠️ [Macro] 资金流获取异常: {e}")
        return [], False


@router.get("/capital-flow")
async def get_capital_flow():
    """获取跨市场资金流向数据"""
    cache_key = "macro_capital_flow"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if cache_key not in _macro_locks:
            _macro_locks[cache_key] = asyncio.Lock()

        async with _macro_locks[cache_key]:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)  # noqa: E701

            flows, is_market_closed = await _fetch_capital_flows()

            result = {
                "status": "success",
                "data": flows,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "akshare+mock",
            }
            # 💡 增加随机 Jitter 防雪崩
            ttl = (43200 if is_market_closed else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 新闻 ────────────────────────────────────────────────────────────────────


async def _fetch_macro_news_from_stream(limit: int = 50) -> list:
    """从 Redis ZSET 滑动窗口中拉取最新的新闻"""
    try:
        # 取出分数最高（最新）的 limit 条
        members = await redis_client.zrevrange("macro_news_stream", 0, limit - 1)
        if members:
            return [json.loads(m) for m in members if isinstance(m, (str, bytes, bytearray))]  # noqa: E501
    except Exception as e:
        print(f"⚠️ [Macro] 从 ZSET 读取新闻异常: {e}")
    return []


@router.get("/news")
async def get_macro_news(
    category: str = Query("general", description="新闻分类: general, forex, crypto, merger"),  # noqa: E501
    limit: int = Query(50, le=200, description="返回条数限制"),
):
    """获取全球市场前沿新闻"""
    if category != "general":
        # 其它非主流分类降级为直接拉取
        return await market_data.get_market_news(category=category)

    try:
        news_list = await _fetch_macro_news_from_stream(limit)
        # 如果 Redis 是空的（初次启动），主动拉取一次
        if not news_list:
            res = await market_data.get_market_news(category="general")
            if res.get("status") == "success":
                news_list = res.get("data", [])[:limit]
        return {"status": "success", "data": news_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/news/ws")
async def websocket_live_news(websocket: WebSocket):
    """Websocket 接口：实时推送最新的宏观新闻流"""
    await websocket.accept()
    pubsub = redis_client.pubsub()

    async def listen_redis():
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                if "type" in data:
                    await websocket.send_json(data)
                else:
                    await websocket.send_json({"type": "live_news", "data": data})

    async def listen_client():
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    try:
        await pubsub.subscribe("live_news_channel", "macro_alerts")
        listen_r_task = asyncio.create_task(listen_redis())
        listen_c_task = asyncio.create_task(listen_client())

        # 💡 并发监听：任何一方 (前端断连或Redis崩溃) 退出，立刻终止挂起的另一方
        done, pending = await asyncio.wait([listen_r_task, listen_c_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        # 💡 等待任务真正取消并归还 Redis 控制权，防止触发并发读写 RuntimeError 导致 close 被跳过  # noqa: E501
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        print("⚠️ [Websocket] 前端已断开实时新闻连接。")
    except Exception as e:
        print(f"❌ [Websocket] 实时新闻推送异常: {str(e)}")
    finally:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        await pubsub.close()


# ── 聚合大盘看板 ────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def get_data_center_dashboard(
    force_refresh: bool = Query(False, description="强制绕过缓存拉取最新数据"),
    days_back: int = Query(3, ge=0, le=30, description="获取过去 N 天内已公布的宏观经济事件"),  # noqa: E501
):  # noqa: E501
    """聚合大盘看板所需的所有核心数据"""
    cache_key = f"macro_dashboard_aggregate_{days_back}"
    try:
        if not force_refresh:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        if cache_key not in _macro_locks:
            _macro_locks[cache_key] = asyncio.Lock()

        async with _macro_locks[cache_key]:
            if not force_refresh:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)  # noqa: E701

            # 1. 发起并发请求获取各类数据 (包含最新的财报日历)
            (
                assets_radar_res,
                events_res,
                news_res,
                earnings_res,
            ) = await asyncio.gather(
                get_macro_assets(force_refresh=force_refresh),
                _fetch_macro_calendar_data(days_ahead=7, days_back=days_back, force_refresh=force_refresh),
                get_macro_news(category="general", limit=15),
                _fetch_earnings_calendar_data(days_ahead=7, days_back=days_back, force_refresh=force_refresh),  # noqa: E501
                return_exceptions=True,
            )

            # 2. 组装最终结果
            radar_data = []
            macro_assets = []
            sentiment_indicators = {}
            if isinstance(assets_radar_res, dict) and assets_radar_res.get("status") == "success":  # noqa: E501
                radar_data = assets_radar_res.get("data", {}).get("radarData", [])
                macro_assets = assets_radar_res.get("data", {}).get("macroAssets", [])
                sentiment_indicators = assets_radar_res.get("data", {}).get("sentimentIndicators", {})  # noqa: E501

            # 💡 容错修复：允许包含警告信息的兜底 Mock 数据流向前端展示
            economic_events = (
                events_res.get("data", [])
                if isinstance(events_res, dict) and events_res.get("status") in ("success", "warning")
                else []
            )  # noqa: E501
            economic_events_msg = (
                events_res.get("message", "")
                if isinstance(events_res, dict) and events_res.get("status") in ("success", "warning")
                else ""
            )  # noqa: E501
            economic_events_deduction = (
                events_res.get("ai_deduction", "")
                if isinstance(events_res, dict) and events_res.get("status") in ("success", "warning")
                else ""
            )  # noqa: E501
            news_items = (
                news_res.get("data", [])
                if isinstance(news_res, dict) and news_res.get("status") in ("success", "warning")
                else []
            )  # noqa: E501
            earnings_calendar = (
                earnings_res.get("data", [])
                if isinstance(earnings_res, dict) and earnings_res.get("status") in ("success", "warning")
                else []
            )  # noqa: E501
            earnings_calendar_deduction = (
                earnings_res.get("ai_deduction", "")
                if isinstance(earnings_res, dict) and earnings_res.get("status") in ("success", "warning")
                else ""
            )  # noqa: E501

            result = {
                "status": "success",
                "data": {
                    "macroAssets": macro_assets,
                    "radarData": radar_data,
                    "sentimentIndicators": sentiment_indicators,
                    "economicEvents": economic_events,
                    "economicEventsMessage": economic_events_msg,
                    "economicEventsDeduction": economic_events_deduction,
                    "newsItems": news_items,
                    "earningsCalendar": earnings_calendar,
                    "earningsCalendarDeduction": earnings_calendar_deduction,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            ttl = 60 + random.randint(10, 30)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 大类资产数据 ────────────────────────────────────────────────────────────


async def _fetch_macro_assets_data():
    """从 Redis 缓存极速拉取 12 个核心宏观指标（数据由后台 YF 守护进程负责离散化更新）"""  # noqa: E501
    assets_config = [
        {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"},
        {"symbol": "ES", "name": "标普500期指", "yf": "ES=F"},
        {"symbol": "IXIC", "name": "NASDAQ 综合", "yf": "^IXIC"},
        {"symbol": "NQ", "name": "纳指期货", "yf": "NQ=F"},
        {"symbol": "HSI", "name": "恒生指数", "yf": "^HSI"},
        {"symbol": "HSTECH", "name": "恒生科技", "yf": "^HSTECH"},  # 💡 修复: 正确 YFinance 代码
        {"symbol": "TNX", "name": "10Y 美债收益率", "yf": "^TNX"},
        {"symbol": "JPY=X", "name": "USD/JPY", "yf": "JPY=X"},
        {"symbol": "DX-Y", "name": "美元指数", "yf": "DX-Y.NYB"},
        {"symbol": "USDCNH", "name": "USD/CNH", "yf": "USDCNH=X"},  # 💡 修复: 正确 YFinance 代码
        {"symbol": "BTC", "name": "比特币 (BTC)", "yf": "BTC-USD"},
        {"symbol": "XAU", "name": "黄金 (XAU)", "yf": "GC=F"},
        {"symbol": "WTI", "name": "WTI 原油", "yf": "CL=F"},
        {"symbol": "HG", "name": "伦铜 (HG)", "yf": "HG=F"},
        {"symbol": "VIX", "name": "VIX 恐慌指数", "yf": "^VIX"},
        {"symbol": "N225", "name": "日经 225", "yf": "^N225"},
        {"symbol": "XLK", "name": "科技板块", "yf": "XLK"},
        {"symbol": "XLE", "name": "能源板块", "yf": "XLE"},
        {"symbol": "KWEB", "name": "中概互联", "yf": "KWEB"},
    ]

    async def fetch_single_asset(config):
        symbol = config["symbol"]
        name = config["name"]
        yf_code = config["yf"]  # noqa: E702
        try:
            # 直接读取由 yf_service 守护进程后台更新的 Redis 缓存
            cache_key = f"yf_macro_cache_{yf_code}"
            cached_data = await redis_client.get(cache_key)

            if cached_data:
                records = json.loads(cached_data)
                if records and len(records) > 0:
                    # 提取收盘价序列供 sparkline 使用 (兼容老版本缓存中存在的 MultiIndex 字符串键)  # noqa: E501
                    closes = []
                    open_vals = []
                    for r in records:
                        c_val = r.get("Close")
                        o_val = r.get("Open")
                        if c_val is None:
                            c_val = next(
                                (v for k, v in r.items() if str(k).startswith("('Close'")),
                                None,
                            )  # noqa: E501
                        if o_val is None:
                            o_val = next(
                                (v for k, v in r.items() if str(k).startswith("('Open'")),
                                None,
                            )  # noqa: E501

                        if c_val is not None:
                            closes.append(float(c_val))
                        if o_val is not None:
                            open_vals.append(float(o_val))

                    if len(closes) > 0:
                        last_close = closes[-1]
                        # 计算涨跌幅，如果只有1天数据则拿昨日开盘价兜底比对
                        prev_close = (
                            closes[-2] if len(closes) > 1 else (float(open_vals[-1]) if open_vals else last_close)
                        )  # noqa: E501
                        change_pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0  # noqa: E501
                        # 💡 获取数据更新时间
                        updated_at = records[-1].get("Date") or records[-1].get("date")
                        return {
                            "symbol": symbol,
                            "name": name,
                            "value": round(last_close, 2),
                            "change": round(change_pct, 2),
                            "sparkline": closes,
                            "data_source": "YFinance",
                            "updated_at": str(updated_at) if updated_at else None,
                        }  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Macro] 从 Redis 解析 {symbol} 失败: {e}")
        return {
            "symbol": symbol,
            "name": name,
            "value": 0.0,
            "change": 0.0,
            "sparkline": [0, 0],
            "data_source": "N/A",
            "updated_at": None,
        }  # noqa: E501

    tasks = [fetch_single_asset(cfg) for cfg in assets_config]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


# ── 大类资产与雷达 (独立高频接口) ──────────────────────────────────────────


@router.get("/assets")
async def get_macro_assets(
    force_refresh: bool = Query(False, description="强制绕过缓存拉取最新数据"),
):  # noqa: E501
    """获取大类资产与宏观风险雷达数据"""
    cache_key = "macro_assets_radar"
    try:
        if not force_refresh:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        if cache_key not in _macro_locks:
            _macro_locks[cache_key] = asyncio.Lock()

        async with _macro_locks[cache_key]:
            if not force_refresh:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)  # noqa: E701

            assets_res = await _fetch_macro_assets_data()

            with_assets = {a["symbol"]: a for a in assets_res if a.get("value", 0) > 0}

            def _chg(s):
                a = with_assets.get(s)
                return float(a["change"]) if a and a.get("change") is not None else None  # noqa: E501, E702

            def _norm_pct(pct, neutral=0.0, scale=2.0, inverse=False):
                if pct is None:
                    return 50  # noqa: E701
                adjusted = -(pct - neutral) / scale if inverse else (pct - neutral) / scale  # noqa: E501
                import math

                raw = 1.0 / (1.0 + math.exp(-adjusted))
                return round(raw * 100, 1)  # noqa: E501, E702, I001

            def _s(s):
                a = with_assets.get(s)
                return float(a["value"]) if a and a.get("value") else None  # noqa: E501, E702

            usdjpy_chg = _chg("JPY=X")
            vix_chg = _chg("VIX")  # noqa: E702
            _liq_scores = [
                s
                for s in [
                    _norm_pct(usdjpy_chg, inverse=True),
                    _norm_pct(vix_chg, inverse=True),
                ]
                if s is not None
            ]  # noqa: E501
            liq_raw = sum(_liq_scores) / len(_liq_scores) if _liq_scores else 50
            vix_abs = _s("VIX")
            vola = round(max(0, min(100, 100 - (vix_abs - 10) * 2.5)), 1) if vix_abs else 50  # noqa: E501, E702
            eq_chgs = [
                c
                for c in [
                    _chg("SPX"),
                    _chg("IXIC"),
                    _chg("HSI"),
                    _chg("HSTECH"),
                    _chg("N225"),
                ]
                if c is not None
            ]  # noqa: E501
            equity = _norm_pct(sum(eq_chgs) / len(eq_chgs)) if eq_chgs else 50
            cn_chgs = [c for c in [_chg("HSI"), _chg("KWEB")] if c is not None]
            cn_strength = _norm_pct(sum(cn_chgs) / len(cn_chgs)) if cn_chgs else 50
            crypto_chgs = [c for c in [_chg("BTC"), _chg("ETH")] if c is not None]
            crypto = _norm_pct(sum(crypto_chgs) / len(crypto_chgs), scale=4.0) if crypto_chgs else 50  # noqa: E501
            cm_chgs = [c for c in [_chg("XAU"), _chg("WTI")] if c is not None]
            commodity = _norm_pct(sum(cm_chgs) / len(cm_chgs)) if cm_chgs else 50
            tnx_chg = _chg("TNX")
            bond = _norm_pct(tnx_chg, inverse=True) if tnx_chg is not None else 50  # noqa: E501, E702
            dxy_chg = _chg("DX-Y")
            fx = _norm_pct(dxy_chg, inverse=True) if dxy_chg is not None else 50  # noqa: E501, E702

            cpc_val = 0.82
            try:
                cpc_cache = await redis_client.get("yf_macro_cache_^CPC")
                if cpc_cache:
                    cpc_records = json.loads(cpc_cache)
                    if cpc_records and len(cpc_records) > 0:
                        c_val = cpc_records[-1].get("Close")
                        if c_val is None:
                            c_val = next(
                                (v for k, v in cpc_records[-1].items() if str(k).startswith("('Close'")),
                                None,
                            )  # noqa: E501
                        if c_val:
                            cpc_val = round(float(c_val), 2)
            except Exception:
                pass
            pc_status = "偏多" if cpc_val < 1.0 else "偏空"
            credit_spread = round(2.0 + (vix_abs / 10.0), 2) if vix_abs else 3.45
            cs_status = "安全" if credit_spread < 4.5 else "高危"

            sentiment_indicators = {
                "pc_ratio": {"value": cpc_val, "status": pc_status},
                "credit_spread": {"value": credit_spread, "status": cs_status},
            }  # noqa: E501

            radar_data = [
                {
                    "axis": "流动性",
                    "current": liq_raw,
                    "benchmark": 60,
                    "desc": "反映全球资金充裕度与风险偏好。",
                },  # noqa: E501
                {
                    "axis": "波动率",
                    "current": vola,
                    "benchmark": 55,
                    "desc": "反映市场恐慌与不确定性。",
                },  # noqa: E501
                {
                    "axis": "权益",
                    "current": equity,
                    "benchmark": 60,
                    "desc": "全球核心股市多头动能。",
                },  # noqa: E501
                {
                    "axis": "商品",
                    "current": commodity,
                    "benchmark": 55,
                    "desc": "大宗商品活跃度与通胀预期。",
                },  # noqa: E501
                {
                    "axis": "债券",
                    "current": bond,
                    "benchmark": 50,
                    "desc": "无风险利率与货币政策环境。",
                },  # noqa: E501
                {
                    "axis": "汇率",
                    "current": fx,
                    "benchmark": 50,
                    "desc": "非美资产汇率压力。",
                },  # noqa: E501
                {
                    "axis": "中概强度",
                    "current": cn_strength,
                    "benchmark": 55,
                    "desc": "中国海外核心资产动量。",
                },  # noqa: E501
                {
                    "axis": "数字货币",
                    "current": crypto,
                    "benchmark": 50,
                    "desc": "加密资产投机情绪。",
                },  # noqa: E501
            ]

            data = {
                "status": "success",
                "data": {
                    "macroAssets": assets_res if assets_res else [],
                    "radarData": radar_data,
                    "sentimentIndicators": sentiment_indicators,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            ttl = 300 + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(data), ex=ttl)
            return data
    except Exception as e:
        print(f"⚠️ [Macro] 获取资产与雷达数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/calendar/ws")
async def websocket_macro_calendar(websocket: WebSocket):
    """Websocket 接口：推送当天的宏观事件报警"""
    await websocket.accept()
    pubsub = redis_client.pubsub()

    async def listen_redis():
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                data["channel"] = message["channel"]  # noqa: E702
                await websocket.send_json(data)

    async def listen_client():
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    try:
        await pubsub.subscribe("macro_alerts")
        result = await _fetch_macro_calendar_data(days_ahead=1)
        today_events = []
        if result.get("status") == "success" and "data" in result:
            current_date = datetime.now(timezone.utc).date()
            for event in result["data"]:
                if event.get("date"):
                    try:
                        d = datetime.strptime(event.get("date").split("T")[0], "%Y-%m-%d").date()  # noqa: E501
                        if d == current_date:
                            today_events.append(event)  # noqa: E701
                    except Exception:
                        pass  # noqa: E701
        await websocket.send_json(
            {
                "type": "macro_alert",
                "message": f"今日共 {len(today_events)} 个高影响事件",
                "events": today_events,
            }
        )  # noqa: E501

        listen_r_task = asyncio.create_task(listen_redis())
        listen_c_task = asyncio.create_task(listen_client())

        done, pending = await asyncio.wait([listen_r_task, listen_c_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

        # 💡 等待任务真正取消并归还 Redis 控制权，防止触发并发读写 RuntimeError 导致 close 被跳过  # noqa: E501
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        print("⚠️ [Websocket] 前端已断开宏观日历报警连接。")
    except Exception as e:
        print(f"❌ [Websocket] 宏观报警推送异常: {str(e)}")
    finally:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        await pubsub.close()
