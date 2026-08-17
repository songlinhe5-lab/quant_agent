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

from sqlalchemy.orm import Session

from backend.app.market_data import market_data
from backend.core import models
from backend.core.exceptions import AppError
from backend.core.redis_client import redis_client
from backend.services.ai_narrator.llm_service import llm_service
from backend.services.fund_flow.us_big_order import get_us_big_order_flow
from backend.services.market_engine import manager

# 用于防范缓存击穿的异步细粒度锁池
_macro_locks = {}


def _fallback_no_data() -> dict:
    """所有真实宏观数据源均不可用时的降级：如实返回空数据 + 明确告警。

    历史实现 (_fallback_mock_macro) 会注入两条写死的 Fed / BOJ 假事件，
    其日期固定在 2026-05-27 / 2026-05-29，相对当前已是过期数据，反而误导。
    改为此策略：无数据即如实告知，由前端展示告警条与空表格，绝不塞假事件。
    """
    return {
        "status": "warning",
        "message": (
            "⚠️ 所有宏观数据源 (AKShare / DBnomics / FRED / Finnhub) 当前均不可用，"
            "暂无可展示的经济日历数据。请检查各数据源 API Key 配置与网络连通性后重试。"
        ),
        "data": [],
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

        try:
            from backend.services.macro.macro_calendar_service import (
                macro_calendar_aggregator,
            )

            agg = await macro_calendar_aggregator.aggregate(days_ahead, days_back=days_back, skip_cache=force_refresh)
            events = agg.get("data", [])
            if not events:
                print("⚠️ [Macro] 多源聚合无数据，降级为空数据 + 告警（不再注入 Mock 假事件）")
                return _fallback_no_data()

            compressed_events = []

            for row in events:
                event_name = str(row.get("event", ""))
                # 💡 聚合器已输出 UTC ISO 时间，前端直接消费，无需再做 per-source 时区转换
                iso_time = str(row.get("date", "")) or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
                        # 💡 透传聚合器标注的数据来源 (_src)，供前端展示"央行事件·数据来源"
                        "source": str(row.get("_src", "")),
                    }
                )  # noqa: E501

            result = {
                "status": "success",
                "time_window": f"Next {len(compressed_events)} High-Impact Events",
                "data": compressed_events,
                "sources_contributed": agg.get("sources_contributed", []),
            }

            # 💡 多源聚合说明 (FRED 已回填 actual，新兴市场 CPI 盲区已覆盖)
            if agg.get("message"):
                result["message"] = agg["message"]

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
            # 💡 用关键字传参：生产 market_data 实际是 MarketDataGateway 适配器
            # (get_earnings_calendar(self, **kwargs))，位置参数 days_ahead 会触发 TypeError 被静默吞成空
            res = await market_data.get_earnings_calendar(
                days_ahead=days_ahead, days_back=days_back, skip_cache=force_refresh
            )  # noqa: E501
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


async def get_macro_calendar(
    days_ahead: int = 7,  # noqa: E501
    days_back: int = 0,  # noqa: E501
):
    """获取全球核心经济体的宏观日历数据 (支持过去和未来)"""
    try:
        result = await _fetch_macro_calendar_data(days_ahead=days_ahead, days_back=days_back)
        if result.get("status") == "error":
            raise AppError(status_code=500, detail=result.get("message"))
        return result
    except Exception as e:
        raise AppError(status_code=500, detail=str(e))


async def get_economic_calendar_facade(
    days_ahead: int = 7,
    days_back: int = 0,
    prefer_sources: list[str] | None = None,
):
    """宏观日历（Facade 统一聚合 fred / dbnomics / rbi，CPI actual 互补回填）。

    与 ``get_macro_calendar``（akshare 传统财经事件日历）互补，不互相替代：
    本接口走 DataServiceFacade 的多源融合路径。
    """
    from backend.services.datasource.business.macro import macro_data_service

    res = await macro_data_service.get_economic_calendar(
        days_ahead=days_ahead, days_back=days_back, prefer_sources=prefer_sources
    )
    data = res.data if hasattr(res, "data") else res
    if isinstance(data, dict) and data.get("status") == "error":
        raise AppError(status_code=502, detail=data.get("message"))
    return data


async def get_fed_watch_panel(prefer_sources: list[str] | None = None):
    """G5：FedWatch 面板（Facade 防御式聚合，Futu FedWatch → 政策斜率）。"""
    from backend.services.datasource.business.macro import macro_data_service

    res = await macro_data_service.get_fed_watch_panel(prefer_sources=prefer_sources)
    data = res.data if hasattr(res, "data") else res
    if isinstance(data, dict) and data.get("status") == "error":
        raise AppError(status_code=502, detail=data.get("message"))
    return data


# ── 宏观经济序列 (FRED) ───────────────────────────────────────────────────


async def get_macro_series(
    series_id: str = ...,
    limit: int = 100,
    force_refresh: bool = False,
):
    """获取 FRED 宏观经济时间序列数据"""
    res = await market_data.get_series_observations(series_id, limit, force_refresh)
    if res.get("status") == "error":
        raise AppError(status_code=400, detail=res.get("message"))
    return res


# ── 情绪风向标历史趋势 ──────────────────────────────────────────────────────


def get_sentiment_history(
    limit: int = 200,
    db: Session = None,
):  # noqa: E501
    """获取情绪风向标历史趋势数据 (P/C Ratio, VIX, Credit Spread)"""
    if not hasattr(models, "SentimentRecord"):
        raise AppError(status_code=500, detail="SentimentRecord 数据表尚未初始化")

    try:
        records = db.query(models.SentimentRecord).order_by(models.SentimentRecord.timestamp.desc()).limit(limit).all()  # noqa: E501
        data = []
        # 倒序遍历，使其在图表上从左向右（从旧到新）排列
        for r in reversed(records):
            # DIST-SENT-01: 跳过全 null 脏记录 (yfinance 节点断供时期旧代码写入的
            # vix_value/pc_ratio/credit_spread 全为 None 的垃圾记录)，避免工具/图表
            # 展示无意义空序列，误导情绪研判。
            if r.vix_value is None and r.pc_ratio is None and r.credit_spread is None:
                continue
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
        raise AppError(status_code=500, detail=str(e))


# ── 板块资金流向 ────────────────────────────────────────────────────────────


async def get_sector_fund_flow():
    """获取三市场板块资金流聚合数据 (A股行业/港股南向/美股板块)"""
    from backend.services.fund_flow.service import fund_flow_service

    return await fund_flow_service.get_sector_fund_flow()


async def get_capital_flow_dashboard(force_refresh: bool = False):
    """FUNDFLOW-01: 北向/南向资金实时看板聚合。

    聚合：北向资金净流入(日/周/月) + 南向资金净流入(日/周/月) + 港股通南向双通道净买额
          + 三市场行业板块资金流 + 美股主力/大单净流入(Futu 资金分布)。
    所有子任务失败均降级为 None，由前端展示空态/告警，绝不注入假数据。

    返回结构:
    {
        "status": "success" | "warning",
        "data": {
            "northbound": {"net_inflow","weekly","monthly","unit","date","sparkline","history"} | None,
            "southbound": {...} | None,
            "hk_connect": {"trade_date","total_net_buy","unit","channels":[...]} | None,
            "a_share": {"sectors":[{"name","net_inflow","change_pct"}],"unit","updated_at","source"} | None,
            "hk": {"sectors":[{"name","net_inflow"}],"unit"} | None,
            "us": {"sectors":[{"name","net_inflow"}],"unit"} | None,
            "us_big_order": {"total_net_inflow","unit","breakdown":[...],"note"} | None,
        },
        "updated_at": ...,
        "source": "akshare",
    }
    """
    cache_key = "macro_capital_flow_dashboard"
    if not force_refresh:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    if cache_key not in _macro_locks:
        _macro_locks[cache_key] = asyncio.Lock()
    async with _macro_locks[cache_key]:
        if not force_refresh:
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        def _to_float(v):
            if v is None or v == "" or v == "-":
                return None
            try:
                return float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                return None

        async def _safe(coro):
            try:
                return await coro
            except Exception as e:
                print(f"⚠️ [capital-flow-dashboard] 子任务失败: {e}")
                return None

        north, south, hk_connect, sectors = await asyncio.gather(
            _safe(market_data.get_northbound_flow()),
            _safe(market_data.get_southbound_flow()),
            _safe(market_data.get_hk_stock_connect_flow()),
            _safe(get_sector_fund_flow()),
        )

        # 美股大单(主力)净流入: 依赖三市场板块抓取后填充的 Futu flow_cache, 故串行其后
        us_big_order = await _safe(get_us_big_order_flow())

        def _clean_flow(flow):
            if not flow or flow.get("status") != "success":
                return None
            d = flow.get("data") or {}
            return {
                "net_inflow": d.get("net_inflow"),
                "weekly": d.get("weekly"),
                "monthly": d.get("monthly"),
                "unit": d.get("unit"),
                "date": d.get("date"),
                "sparkline": d.get("sparkline"),
                "history": d.get("history"),
            }

        def _sectors(payload):
            if not payload or payload.get("status") != "success":
                return None
            return payload.get("data") or {}

        north_data = _clean_flow(north)
        south_data = _clean_flow(south)
        sectors_data = _sectors(sectors)

        a_share = None
        hk = None
        us = None
        if sectors_data:
            a_share_block = sectors_data.get("a_share") or {}
            if a_share_block.get("status") != "success":
                a_share = None
            else:
                a_raw = a_share_block.get("data") or {}
                a_items = a_raw.get("inflow_top") or []
                a_share = {
                    "sectors": [
                        {
                            "name": it.get("名称"),
                            "net_inflow": _to_float(it.get("主力净流入")),
                            "change_pct": _to_float(it.get("涨跌幅")),
                        }
                        for it in a_items
                    ],
                    "unit": a_raw.get("unit"),
                    "updated_at": a_share_block.get("updated_at"),
                    "source": a_share_block.get("source"),
                }
            hk_block = sectors_data.get("hk") or {}
            if hk_block.get("status") != "success":
                hk = None
            else:
                hk_raw = hk_block.get("data") or {}
                hk = {
                    "sectors": [
                        {"name": it.get("name"), "net_inflow": _to_float(it.get("net_inflow"))}
                        for it in (hk_raw.get("sectors") or [])
                    ],
                    "unit": hk_raw.get("unit"),
                }
            us_block = sectors_data.get("us") or {}
            if us_block.get("status") != "success":
                us = None
            else:
                us_raw = us_block.get("data") or {}
                us = {
                    "sectors": [
                        {"name": it.get("name"), "net_inflow": _to_float(it.get("net_inflow"))}
                        for it in (us_raw.get("sectors") or [])
                    ],
                    "unit": us_raw.get("unit"),
                }

        def _hk_connect(payload):
            if not payload or payload.get("status") != "success":
                return None
            return payload.get("data") or {}

        def _us_big_order(payload):
            if not payload or payload.get("status") != "success":
                return None
            return payload.get("data") or {}

        hk_connect_data = _hk_connect(hk_connect)
        us_big_order_data = _us_big_order(us_big_order)

        any_ok = any(
            x is not None for x in [north_data, south_data, hk_connect_data, a_share, hk, us, us_big_order_data]
        )
        result = {
            "status": "success" if any_ok else "warning",
            "data": {
                "northbound": north_data,
                "southbound": south_data,
                "hk_connect": hk_connect_data,
                "a_share": a_share,
                "hk": hk,
                "us": us,
                "us_big_order": us_big_order_data,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "akshare",
        }
        if any_ok:
            await redis_client.set(cache_key, json.dumps(result), ex=300 + random.randint(10, 60))
        return result


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
            sd = south_res.get("data") or {}
            flows.append(
                {
                    "market": "HK",
                    "label": "港股南向",
                    "amount": sd.get("net_inflow"),
                    "unit": sd.get("unit", "亿港元"),
                    "dir": 1 if (sd.get("net_inflow") or 0) >= 0 else -1,
                    "desc": sd.get("name", "沪深港通净买入港股"),
                    "sparkDirs": sd.get("sparkline", [1, 1, -1, 1, 1, 1, -1, 1]),
                    "data_source": (sd.get("source") if sd else "N/A") or "N/A",
                    "updated_at": sd.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                }
            )

        def _parse_futu_flow(res, real_desc, unit="亿美元"):
            """解析 Futu 单标的资金流。

            仅当 Futu 返回 success 时给出真实净额；失败时不再回退到写死的
            默认假值 (旧逻辑 default_amt=2.1 等)，一律返回 None 由前端显示 N/A。
            """
            if isinstance(res, dict) and res.get("status") == "success":
                fund_data = res.get("data", res)
                val = fund_data.get("main_fund_net_inflow", 0.0) / 100_000_000.0
                amt = round(val, 2)
                updated_at = fund_data.get("updated_at") or datetime.now(timezone.utc).isoformat()
                return amt, 1 if amt >= 0 else -1, real_desc, unit, "Futu", updated_at
            return (
                None,
                0,
                real_desc,
                unit,
                "N/A",
                None,
            )

        # 💡 使用核心 ETF 的主买主卖差额代表板块的整体真实资金流
        csi_amount, csi_dir, csi_desc, csi_unit, csi_source, csi_updated = _parse_futu_flow(
            csi300_res, "沪深300ETF主力净流", "亿人民币"
        )  # noqa: E501
        spy_amount, spy_dir, spy_desc, spy_unit, spy_source, spy_updated = _parse_futu_flow(
            spy_res, "标普500ETF主力净流", "亿美元"
        )  # noqa: E501
        qqq_amount, qqq_dir, qqq_desc, qqq_unit, qqq_source, qqq_updated = _parse_futu_flow(
            qqq_res, "纳指科技ETF主力净流", "亿美元"
        )  # noqa: E501
        soxx_amount, soxx_dir, soxx_desc, soxx_unit, soxx_source, soxx_updated = _parse_futu_flow(
            soxx_res, "半导体ETF主力净流", "亿美元"
        )  # noqa: E501
        tlt_amount, tlt_dir, tlt_desc, tlt_unit, tlt_source, tlt_updated = _parse_futu_flow(
            tlt_res, "20年期美债ETF主力净流", "亿美元"
        )  # noqa: E501
        kweb_amount, kweb_dir, kweb_desc, kweb_unit, kweb_source, kweb_updated = _parse_futu_flow(
            kweb_res, "中概互联ETF主力净流", "亿美元"
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
        raise AppError(status_code=500, detail=str(e))


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


async def get_macro_news(
    category: str = "general",  # noqa: E501
    limit: int = 50,
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
        raise AppError(status_code=500, detail=str(e))


# ── 聚合大盘看板 ────────────────────────────────────────────────────────────


async def get_data_center_dashboard(
    force_refresh: bool = False,
    days_back: int = 3,  # noqa: E501
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
                margin_res,
                sector_flow_res,
                us_short_res,
            ) = await asyncio.gather(
                get_macro_assets(force_refresh=force_refresh),
                _fetch_macro_calendar_data(days_ahead=7, days_back=days_back, force_refresh=force_refresh),
                get_macro_news(category="general", limit=15),
                _fetch_earnings_calendar_data(days_ahead=7, days_back=days_back, force_refresh=force_refresh),  # noqa: E501
                _fetch_margin_trading_data(),
                _fetch_sector_fund_flow(),
                _fetch_us_short_interest(),
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
            earnings_ok = isinstance(earnings_res, dict) and earnings_res.get("status") in (
                "success",
                "warning",
            )  # noqa: E501
            earnings_calendar = earnings_res.get("data", []) if earnings_ok else []
            earnings_calendar_deduction = earnings_res.get("ai_deduction", "") if earnings_ok else ""
            # 💡 透传 Finnhub 真实状态，区分「真无数据」与「接口报错」，避免前端误报
            earnings_status = earnings_res.get("status") if isinstance(earnings_res, dict) else "unknown"
            earnings_message = (
                earnings_res.get("message", "") if isinstance(earnings_res, dict) and not earnings_ok else ""
            )  # noqa: E501

            # 融资融券数据
            margin_data = []
            margin_status = "unknown"
            if isinstance(margin_res, dict) and margin_res.get("status") in (
                "success",
                "partial",
            ):
                margin_data = margin_res.get("data", [])
                margin_status = margin_res.get("status")
            elif isinstance(margin_res, BaseException):
                margin_status = "error"

            # 美股做空指标 (CBOE/FINRA)
            us_short_interest = None
            us_short_interest_status = "unknown"
            if isinstance(us_short_res, dict) and us_short_res.get("status") == "success":
                us_short_interest = us_short_res.get("data")
                us_short_interest_status = "success"
            elif isinstance(us_short_res, BaseException):
                us_short_interest_status = "error"

            # 板块资金流数据
            sector_fund_flow = {}
            sector_flow_status = "unknown"
            if isinstance(sector_flow_res, dict) and sector_flow_res.get("status") in (
                "success",
                "partial",
            ):
                sector_fund_flow = sector_flow_res.get("data", {})
                sector_flow_status = sector_flow_res.get("status")
            elif isinstance(sector_flow_res, BaseException):
                sector_flow_status = "error"

            result = {
                "status": "success",
                "data": {
                    "macroAssets": macro_assets,
                    "radarData": radar_data,
                    "sentimentIndicators": sentiment_indicators,
                    "economicEvents": economic_events,
                    "economicEventsMessage": economic_events_msg,
                    "economicEventsDeduction": economic_events_deduction,
                    # 💡 透传多源聚合的贡献源清单，供前端图例展示
                    "economicEventsSources": (
                        events_res.get("sources_contributed", [])
                        if isinstance(events_res, dict) and events_res.get("status") in ("success", "warning")
                        else []
                    ),
                    "newsItems": news_items,
                    "earningsCalendar": earnings_calendar,
                    "earningsCalendarDeduction": earnings_calendar_deduction,
                    "earningsStatus": earnings_status,
                    "earningsMessage": earnings_message,
                    "marginTrading": margin_data,
                    "marginTradingStatus": margin_status,
                    "usShortInterest": us_short_interest,
                    "usShortInterestStatus": us_short_interest_status,
                    "sectorFundFlow": sector_fund_flow,
                    "sectorFundFlowStatus": sector_flow_status,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            ttl = 60 + random.randint(10, 30)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
    except Exception as e:
        raise AppError(status_code=500, detail=str(e))


# ── 大类资产数据 ────────────────────────────────────────────────────────────


async def _fetch_margin_trading_data():
    """获取融资融券余额数据"""
    from backend.services.margin.service import margin_service

    return await margin_service.get_all_margin_data()


async def _fetch_us_short_interest():
    """获取美股做空指标 (CBOE/FINRA 真实源)，无可用源时返回 error 由前端兜底隐藏"""
    from backend.services.margin.us_share import get_us_share_margin

    return await get_us_share_margin()


async def _fetch_sector_fund_flow():
    """获取三市场板块资金流数据"""
    from backend.services.fund_flow.service import fund_flow_service

    return await fund_flow_service.get_sector_fund_flow()


async def _fetch_macro_assets_data():
    """从 Redis 缓存极速拉取 12 个核心宏观指标（数据由后台 YF 守护进程负责离散化更新）"""  # noqa: E501
    assets_config = [
        {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"},
        {"symbol": "ES", "name": "标普500期指", "yf": "ES=F"},
        {"symbol": "IXIC", "name": "NASDAQ 综合", "yf": "^IXIC"},
        {"symbol": "NQ", "name": "纳指期货", "yf": "NQ=F"},
        {"symbol": "HSI", "name": "恒生指数", "yf": "^HSI"},
        {
            "symbol": "HSTECH",
            "name": "恒生科技",
            "yf": "HSTECH.HK",
        },  # 💡 恒生科技指数 Yahoo 代码
        {"symbol": "TNX", "name": "10Y 美债收益率", "yf": "^TNX"},
        {"symbol": "JPY=X", "name": "USD/JPY", "yf": "JPY=X"},
        {"symbol": "DX-Y", "name": "美元指数", "yf": "DX-Y.NYB"},
        {
            "symbol": "USDCNH",
            "name": "USD/CNH",
            "yf": "USDCNH=X",
        },  # 💡 修复: 正确 YFinance 代码
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
            # key 必须小写（写侧 collectors/yfinance.py 用 ticker.lower() 写缓存）
            cache_key = f"yf_macro_cache_{yf_code.lower()}"
            cached_data = await redis_client.get(cache_key)

            if cached_data:
                records = json.loads(cached_data)
                if records and len(records) > 0:
                    # 提取收盘价序列供 sparkline 使用 (兼容老版本缓存中存在的 MultiIndex 字符串键)  # noqa: E501
                    closes = []
                    open_vals = []
                    for r in records:
                        # 子服务 HISTORY 返回小写字段 (close/open/date)；兼容老版本大写
                        # Close/Open/Date 及 MultiIndex 拍平前的字符串键。
                        c_val = r.get("Close") if r.get("Close") is not None else r.get("close")
                        o_val = r.get("Open") if r.get("Open") is not None else r.get("open")
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


async def get_earnings_calendar(
    days_ahead: int = 7,
    days_back: int = 0,
    force_refresh: bool = False,
):
    """财报日历（供 Calendars Earnings Tab 复用，复用既有聚合逻辑）"""
    return await _fetch_earnings_calendar_data(days_ahead=days_ahead, days_back=days_back, force_refresh=force_refresh)


async def get_macro_assets(
    force_refresh: bool = False,
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

            cpc_val = None  # 无真实 CPC 缓存时置空，前端显示 N/A
            try:
                cpc_cache = await redis_client.get("yf_macro_cache_^CPC")
                if cpc_cache:
                    cpc_records = json.loads(cpc_cache)
                    if cpc_records and len(cpc_records) > 0:
                        c_val = cpc_records[-1].get("close")
                        if c_val is None:
                            # 兜底：旧 MultiIndex 列名形如 ("'Close'", "^CPC")
                            c_val = next(
                                (v for k, v in cpc_records[-1].items() if str(k).lower().startswith("close")),
                                None,
                            )  # noqa: E501
                        if c_val:
                            cpc_val = round(float(c_val), 2)
            except Exception:
                pass
            pc_status = "N/A" if cpc_val is None else ("偏多" if cpc_val < 1.0 else "偏空")
            credit_spread = round(2.0 + (vix_abs / 10.0), 2) if vix_abs else None
            cs_status = "N/A" if credit_spread is None else ("安全" if credit_spread < 4.5 else "高危")

            # 恐惧贪婪指数 (F&G)：用已连通的真实行情因子等权合成（0=极度恐惧, 100=极度贪婪）。
            # 因子均来自本接口既有的真实子分数（波动率/股市动能/商品/债券/汇率/中概/加密），
            # 不引入任何外部神秘源，符合零幻觉红线。
            fg_factors = [vola, equity, commodity, bond, fx, cn_strength, crypto]
            fg_score = round(sum(fg_factors) / len(fg_factors), 1) if fg_factors else 50  # noqa: E501
            fg_status = (
                "极度恐惧"
                if fg_score <= 25
                else "恐惧"
                if fg_score <= 45
                else "中性"
                if fg_score <= 55
                else "贪婪"
                if fg_score <= 75
                else "极度贪婪"
            )  # noqa: E501

            sentiment_indicators = {
                "pc_ratio": {"value": cpc_val, "status": pc_status},
                "credit_spread": {"value": credit_spread, "status": cs_status},
                "fear_greed": {"value": fg_score, "status": fg_status},
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
        raise AppError(status_code=500, detail=str(e))


# ── 融资融券余额 ────────────────────────────────────────────────────────────


async def get_margin_trading_data():
    """
    获取三个市场的融资融券余额数据

    返回 A 股、港股、美股的融资余额和融券余额。
    数据来源:
    - A 股: AKShare (上交所/深交所)
    - 港股: Futu API
    - 美股: FINRA / YFinance
    """
    from backend.services.margin.service import margin_service

    try:
        result = await margin_service.get_all_margin_data()
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"融资融券数据获取失败: {str(e)}",
            "data": [],
        }
