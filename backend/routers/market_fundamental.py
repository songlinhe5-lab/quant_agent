"""
Market Fundamental 路由 — 个股基本面、新闻、事件、持仓与内幕交易端点。

从 market.py 拆分，共享 /market 前缀。
"""

import asyncio
import json
import random
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from backend.core.redis_client import redis_client
from backend.services.datasource import ResultStatus
from backend.core.ticker_format import format_yf_ticker

# Legacy OpenD 健康探测（仅用于 fundamental 端点的 FRED 路由）
from backend.services.adapters.legacy_market_data import market_data_gateway
from backend.services.datasource.business import data_service

router = APIRouter(prefix="/market", tags=["Market & Portfolio"])

# 全局异步锁池，防止新闻接口缓存击穿 (Cache Stampede)
_news_locks: dict[str, asyncio.Lock] = {}


def _flat_facade_payload(facade_res, fallback_msg: str):
    """BE-13 方案 B：把 facade Result 拍平为供中间件包信封的扁平 payload。

    当 facade 成功但 data 为空/非 dict（子服务返回空 payload 的常见情况）时，
    必须返回降级扁平 payload，而非 `**None` 抛 TypeError → 500。
    """
    data = facade_res.data
    if not isinstance(data, dict):
        return {
            "data": {},
            "source": f"facade+{facade_res.source}",
            "degraded": True,
            "degraded_message": fallback_msg,
        }
    return {
        **data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
    }


# ─────────────────────────────────────────────
# Finnhub 真实数据源桥接（DataSourcePort + FinnhubAdapter）
# 统一：优先真实源，失败/未配置时返回 None 由调用方回退模拟数据
# ─────────────────────────────────────────────


async def _fetch_finnhub_news(ticker: str, limit: int, days_back: int = 3):
    """走 Finnhub company_news 拉取个股新闻，返回 [{time, headline, summary}] 或 None。"""
    try:
        from backend.services.datasource.adapters.finnhub import (
            ensure_finnhub_registered,
        )
        from backend.services.datasource.source_registry import datasource_registry

        ensure_finnhub_registered()
    except Exception:  # noqa: BLE001
        return None

    try:
        res = await datasource_registry.fetch("finnhub", "company_news", {"ticker": ticker, "days_back": days_back})
    except Exception:  # noqa: BLE001 - fetch 异常时回退模拟数据，不应中断新闻流
        return None
    if not res.is_success:
        return None

    raw = res.data or []
    # 零幻觉红线：真实源返回空数组时视为"该源对该标的无数据"(如 Finnhub 免费版
    # 不支持港股新闻，恒返回 0 条)，返回 None 让调用方降级到 Yahoo/akshare 兜底，
    # 严禁返回 success + count:0 的假成功。
    if not raw:
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts = item.get("datetime")
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, (int, float)) else str(ts or "")
        out.append(
            {
                "time": t,
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
            }
        )
    return out[:limit] if limit else out


async def _fetch_futu_news(ticker: str, limit: int, days_back: int = 3):
    """走 Futu 富途搜索资讯拉取个股新闻（港股主数据源）。

    返回 [{time, headline, summary}] 或 None。Futu 免费版对港股新闻可用，
    通过 futu adapter (COMPANY_NEWS) 转发到 data_subservice 的 get_search_news。
    """
    try:
        from backend.services.datasource.adapters.futu import ensure_futu_registered
        from backend.services.datasource.source_registry import datasource_registry

        ensure_futu_registered()
    except Exception:  # noqa: BLE001
        return None

    try:
        res = await datasource_registry.fetch("futu", "company_news", {"ticker": ticker, "days_back": days_back})
    except Exception:  # noqa: BLE001
        return None
    if not res.is_success:
        return None

    raw = res.data or []
    if not raw:
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts = item.get("datetime")
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, (int, float)) else str(ts or "")
        out.append(
            {
                "time": t,
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
            }
        )
    return out[:limit] if limit else out


async def _fetch_finnhub_earnings(ticker: str, days_back: int = 30, days_ahead: int = 30):
    """走 Finnhub earnings 拉取财报日历，返回事件列表或 None。"""
    try:
        from backend.services.datasource.adapters.finnhub import (
            ensure_finnhub_registered,
        )
        from backend.services.datasource.source_registry import datasource_registry

        ensure_finnhub_registered()
    except Exception:  # noqa: BLE001
        return None

    res = await datasource_registry.fetch(
        "finnhub",
        "earnings",
        {"ticker": ticker, "days_back": days_back, "days_ahead": days_ahead},
    )
    if not res.is_success:
        return None

    raw = res.data or []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        quarter = item.get("quarter")
        out.append(
            {
                "date": item.get("date", ""),
                "type": "earnings",
                "label": f"Q{quarter} 财报" if quarter else "财报",
                "impact": "high",
                "data": {
                    "epsEstimate": item.get("epsEstimated"),
                    "epsActual": item.get("eps"),
                },
            }
        )
    return out


async def _fetch_finnhub_insider(ticker: str, limit: int):
    """走 Finnhub insider_trading 拉取内幕交易，返回 [{date, name, transaction_type, shares, price, value}] 或 None。"""
    try:
        from backend.services.datasource.adapters.finnhub import (
            ensure_finnhub_registered,
        )
        from backend.services.datasource.source_registry import datasource_registry

        ensure_finnhub_registered()
    except Exception:  # noqa: BLE001
        return None

    res = await datasource_registry.fetch("finnhub", "insider_trading", {"ticker": ticker, "limit": limit})
    if not res.is_success:
        return None

    raw = res.data or []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        change = item.get("change") or 0
        price = item.get("transaction_price") or 0
        value = (change * price) if (change and price) else None
        out.append(
            {
                "date": item.get("date", ""),
                "name": item.get("name", "N/A"),
                "transaction_type": item.get("action"),
                "shares": change,
                "price": price,
                "value": value,
            }
        )
    return out


def _safe_pct(value, mult: float = 100.0):
    """安全地把数值字段转成百分比字符串。

    yfinance 对缺失字段常返回字符串 "N/A" 或非数值，直接 `value * 100` 会抛
    TypeError 导致 500。此处统一转换为 float，失败/NaN 返回 None。
    """
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if fv != fv:  # NaN
        return None
    return f"{fv * mult:.2f}%"


# ─────────────────────────────────────────────
#  新闻 & 事件端点
# ─────────────────────────────────────────────


@router.get("/news")
async def get_company_news(ticker: str, limit: int = 10):
    """获取个股专属新闻 (Finnhub 直连)"""
    from datetime import datetime

    # 💡 净化输入：仅保留字母、数字与常见标点，截断超长输入，防范 Redis 脏数据 Key 注入
    safe_ticker = re.sub(r"[^A-Za-z0-9_.-]", "", str(ticker))[:20].upper()
    if not safe_ticker:
        return {"status": "error", "message": "非法的股票代码参数"}

    # 1. 构造缓存 Key 并尝试无锁读取 (First Check - 极速通道)
    cache_key = f"cache:market:news:{safe_ticker}:{limit}"
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)
    except Exception as e:
        print(f"⚠️ [Market News] Redis 缓存读取失败: {e}")

    # 2. 缓存未命中，动态为当前资源分配一把细粒度的异步锁
    if cache_key not in _news_locks:
        _news_locks[cache_key] = asyncio.Lock()

    try:
        # 💡 使用 asyncio.timeout 包裹，限制等锁与 Finnhub 网络请求的总时长为 5.0 秒
        async with asyncio.timeout(5.0):
            async with _news_locks[cache_key]:
                # 3. 拿到锁后，执行二次检查 (Double Check)
                try:
                    cached_data = await redis_client.get(cache_key)
                    if cached_data:
                        return json.loads(cached_data)
                except Exception:
                    pass

                # 4. 确认缓存确实为空，优先走真实新闻源。
                #    港股主数据源 = Futu 富途搜索资讯 (Finnhub 免费版港股 403 无权限)，
                #    美股/A股 = Finnhub company_news。
                is_hk = safe_ticker.startswith("HK.") or safe_ticker.endswith(".HK")
                if is_hk:
                    real_news = await _fetch_futu_news(safe_ticker, limit, days_back=3)
                    source_tag = "futu"
                else:
                    real_news = await _fetch_finnhub_news(safe_ticker, limit, days_back=3)
                    source_tag = "finnhub"
                if real_news is not None:
                    result = {
                        "status": "success",
                        "count": len(real_news),
                        "data": real_news,
                        "source": source_tag,
                        "message": None,
                    }
                    try:
                        await redis_client.set(cache_key, json.dumps(result), ex=300)
                    except Exception:
                        pass
                    return result

                # 真实源 (Finnhub) 不可用 → 港股/A股经 Yahoo 兜底 (BE-ARCH-07j, 联邦 yfinance 子服务)
                try:
                    from backend.core.yahoo_news import fetch_yahoo_news

                    yahoo_news_list = await fetch_yahoo_news(safe_ticker)
                except Exception as yahoo_e:  # noqa: BLE001
                    print(f"⚠️ [Market News] {safe_ticker} Yahoo 兜底异常: {yahoo_e}")
                    yahoo_news_list = []

                if yahoo_news_list:
                    yahoo_formatted = [
                        {
                            "time": datetime.fromtimestamp(item["datetime"]).strftime("%Y-%m-%d %H:%M:%S")
                            if isinstance(item.get("datetime"), (int, float))
                            else str(item.get("time", "")),
                            "headline": item.get("headline", ""),
                            "summary": item.get("summary", ""),
                        }
                        for item in yahoo_news_list[:limit]
                        if isinstance(item, dict)
                    ]
                    result = {
                        "status": "success",
                        "count": len(yahoo_formatted),
                        "data": yahoo_formatted,
                        "source": "yahoo_fallback",
                        "message": None,
                    }
                    try:
                        await redis_client.set(cache_key, json.dumps(result), ex=300)
                    except Exception:
                        pass
                    return result

                # 零幻觉红线: 真实源与兜底均失败, 严禁返回 mock 假数据
                return {
                    "status": "no_data",
                    "count": 0,
                    "data": [],
                    "source": "none",
                    "message": f"{safe_ticker} 个股新闻源暂不可用 (Finnhub 不支持该标的且 Yahoo 兜底失败)，请改用网络搜索工具获取",
                }
    except TimeoutError:
        print(f"⚠️ [Market News] 等待 {ticker} 的锁或请求 Finnhub 超时 (5秒)")
        return {
            "status": "success",
            "count": 0,
            "data": [],
            "source": "empty",
            "message": "获取新闻超时，暂无数据",
        }  # noqa: E501
    except Exception as e:
        err_msg = str(e).strip() or type(e).__name__
        print(f"⚠️ [Market News] {ticker} 的 Finnhub 数据请求异常: {err_msg}")
        return {
            "status": "success",
            "count": 0,
            "data": [],
            "source": "error",
            "message": f"个股新闻源受限: {err_msg}",
        }  # noqa: E501


@router.get("/events/{ticker}")
async def get_stock_events(ticker: str, days_back: int = 30, days_ahead: int = 30):
    """💡 获取个股相关事件（财报、分红、重大新闻）用于 K 线图事件标记

    返回格式:
    [
        {"date": "2024-01-15", "type": "earnings", "label": "Q4 财报", "impact": "high"},
        {"date": "2024-01-20", "type": "dividend", "label": "除权除息", "impact": "medium"},
        {"date": "2024-01-25", "type": "news", "label": "重大新闻标题...", "impact": "low"}
    ]
    """
    from datetime import datetime

    # 💡 净化输入
    safe_ticker = re.sub(r"[^A-Za-z0-9_.-]", "", str(ticker))[:20].upper()
    if not safe_ticker:
        return {"status": "error", "message": "非法的股票代码参数"}

    events = []

    # 1. 财报日历事件：优先 Finnhub，失败回退模拟数据
    real_earnings = await _fetch_finnhub_earnings(safe_ticker, days_back, days_ahead)
    if real_earnings:
        events.extend(real_earnings)
    else:
        mock_earnings = [
            {
                "date": (datetime.now().replace(day=15)).strftime("%Y-%m-%d"),
                "type": "earnings",
                "label": f"Q{(datetime.now().month - 1) // 3 + 1} 财报",
                "impact": "high",
                "data": {
                    "epsEstimate": round(random.uniform(1, 5), 2),
                    "epsActual": round(random.uniform(1.2, 5.5), 2),
                },
            }
        ]
        events.extend(mock_earnings)

    # 2. 个股新闻作为重大事件：优先 Finnhub，失败回退模拟数据
    real_news = await _fetch_finnhub_news(safe_ticker, limit=10, days_back=days_back)
    if real_news:
        for n in real_news:
            events.append(
                {
                    "date": (n.get("time") or "")[:10],
                    "type": "news",
                    "label": f"{safe_ticker}: {n.get('headline', '')}",
                    "impact": "medium",
                    "data": {"source": "finnhub", "url": None},
                }
            )
    else:
        from datetime import timedelta

        mock_news_events = [
            {
                "date": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                "type": "news",
                "label": f"{safe_ticker}: 获得机构增持",
                "impact": "medium",
                "data": {
                    "source": "mock_news",
                    "url": None,
                },
            }
        ]
        events.extend(mock_news_events)

    # 💡 按日期排序
    events.sort(key=lambda x: x.get("date", ""))

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（前端 lightweight-chart-canvas 读 res.data.data）
    return {
        "ticker": safe_ticker,
        "count": len(events),
        "data": events,
        "degraded": False,
    }


# ─────────────────────────────────────────────
#  基本面 & 持仓 & 内幕端点
# ─────────────────────────────────────────────


@router.get("/fundamental/{ticker}")
async def get_fundamental(ticker: str):
    yf_ticker = format_yf_ticker(ticker)
    upper_ticker = yf_ticker

    # 💡 建立大类资产到 FRED 宏观经济序列的智能映射表
    fred_macro_map = {
        "SPX": "SP500",
        "^GSPC": "SP500",
        "IXIC": "NASDAQCOM",
        "^IXIC": "NASDAQCOM",
        "TNX": "DGS10",
        "^TNX": "DGS10",
        "VIX": "VIXCLS",
        "^VIX": "VIXCLS",
        "DX-Y": "DTWEXBGS",
        "DX-Y.NYB": "DTWEXBGS",
        "WTI": "DCOILWTICO",
        "CL=F": "DCOILWTICO",  # noqa: E501
        "XAU": "GOLDAMGBD228NLBM",
        "GC=F": "GOLDAMGBD228NLBM",
        "BTC": "CBBTCUSD",
        "BTC-USD": "CBBTCUSD",  # noqa: E501
        "N225": "NIKKEI225",
        "^N225": "NIKKEI225",
        "EURUSD=X": "DEXUSEU",
        "GBPUSD=X": "DEXUSUK",  # noqa: E501
        "JPY=X": "DEXJPUS",
        "CNH=X": "DEXCHUS",
    }

    # 1. 智能拦截：如果是宏观资产/指数，自动无缝路由给 fred_service 获取其特有的"基本面" (宏观序列)  # noqa: E501
    for key, fred_id in fred_macro_map.items():
        if key == upper_ticker or key in upper_ticker:
            res = await market_data_gateway.get_series_observations(fred_id, limit=5)
            if res.get("status") == "success":
                return {
                    "status": "success",
                    "message": f"[{ticker}] 属于宏观大类资产，已自动为您路由至 FRED 数据库获取其最新指标序列。",
                    "data": {
                        "fred_series_id": fred_id,
                        "recent_observations": res.get("data"),
                    },
                }  # noqa: E501

    index_indicators = ["HSI", "DJI", "800000", "800700", "SSEC", "CSI300"]
    if (
        any(idx == upper_ticker or f".{idx}" in upper_ticker or f"{idx}." in upper_ticker for idx in index_indicators)
        or "BK" in upper_ticker
    ):  # noqa: E501
        return {
            "status": "warning",
            "message": f"[{ticker}] 属于大盘或板块指数。指数没有个股基本面。请改用 get_broker_market_data 工具获取成交额与行情。",
        }  # noqa: E501

    # BE-ARCH-06c: 经 Facade 统一选源获取基本面数据
    final_data = {}

    # Step 1: 尝试 Facade 基本面（Futu 优先 by weight）
    fund_res = await data_service.get_fundamental(ticker)
    if fund_res.is_success and fund_res.data:
        final_data.update(fund_res.data if isinstance(fund_res.data, dict) else {})
    else:
        # Step 2: Facade fundamental 失败，降级到 YFinance info
        info_res = await data_service.get_fundamental_info(ticker, prefer_sources=["yfinance"])
        yf_info = info_res.data if isinstance(info_res.data, dict) else {}
        yf_msg = info_res.error.message if info_res.error else ""
        if not info_res.is_success or not yf_info:
            # Futu 与 YFinance 均未取得可用基本面数据：返回 warning (200) 而非 500
            warning_msg = f"Futu 与 YFinance 均未能获取标的 {ticker} 的基本面数据。"
            if yf_msg:
                warning_msg += f" YFinance: {yf_msg}"
            return {
                "status": "warning",
                "message": warning_msg,
                "data": {},
            }

        # 💡 ETF 无个股维度估值指标，返回 ETF 专属提示与数据
        if yf_info.get("quoteType") == "ETF":
            return {
                "status": "success",
                "message": f"[{ticker}] 属于 ETF 基金，没有个股维度的 PE/PB/ROE 等估值指标。",  # noqa: E501
                "data": {
                    "ticker": ticker,
                    "company_name": yf_info.get("shortName", yf_info.get("longName")),  # noqa: E501
                    "fund_family": yf_info.get("fundFamily"),
                    "total_assets": yf_info.get("totalAssets"),  # noqa: E501
                    "nav_price": yf_info.get("navPrice"),
                    "yield": _safe_pct(yf_info.get("yield")),  # noqa: E501
                    "beta": yf_info.get("beta"),
                },
            }

        yf_results = {
            "ticker": ticker,
            "company_name": yf_info.get("shortName", ""),
            "trailing_PE": yf_info.get("trailingPe"),  # noqa: E501
            "forward_PE": yf_info.get("forwardPE"),
            "PEG_ratio": yf_info.get("pegRatio"),
            "price_to_book": yf_info.get("priceToBook"),  # noqa: E501
            "ROE": _safe_pct(yf_info.get("returnOnEquity")),  # noqa: E501
            "short_ratio": yf_info.get("shortRatio"),
            "beta": yf_info.get("beta"),
        }
        final_data.update({k: v for k, v in yf_results.items() if v is not None})

    return {"status": "success", "data": final_data}


@router.get("/fundamental/merged/{ticker}")
async def get_fundamental_merged(ticker: str):
    """G1 · 真基本面三源合并端点。

    并发聚合 Futu(财报+估值) + FMP(基本面) + YFinance(info) 三大真实源，
    戳破旧版单源假基本面。单源失败不影响其他源（graceful degradation）。
    返回结构含各源状态与合并时间戳，前端可据此标注数据完整度。
    """
    res = await data_service.get_fundamental_merged(ticker)
    if not res.is_success or not res.data:
        err_msg = res.error.message if res.error else "未知错误"
        return {
            "status": "warning",
            "message": f"[{ticker}] 基本面三源合并均失败: {err_msg}",
            "data": {},
        }

    return {"status": "success", "data": res.data}


@router.get("/short-selling/{ticker}")
@router.get("/short-selling/{ticker}/{mode}")
async def get_short_selling(ticker: str, mode: str = "rank"):
    """G2 · 港股卖空拥挤度监控端点。

    聚合 Futu 真卖空源（卖空榜 / 每日卖空量）+ HKEX/SFC 监管交叉验证，
    派生卖空成交占比、拥挤度分位、挤空/崩塌告警信号。
    T-1 红线：daily 模式当日盘后 0 行如实返回 no_data，不输出"卖空为 0"。
    """
    res = await data_service.get_short_selling(ticker, mode=mode)
    if not res.is_success or not res.data:
        err_msg = res.error.message if res.error else "未知错误"
        # BE-13 方案 B：扁平 payload 交由中间件统一包信封
        return {
            "message": f"[{ticker}] 卖空拥挤度数据不可用: {err_msg}",
            "data": {},
            "source": f"facade+{res.source}",
            "degraded": True,
        }

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（前端 short-selling-panel 读 res.data 兼容）
    return {
        **res.data,
        "source": f"facade+{res.source}",
        "degraded": res.status == ResultStatus.DEGRADED,
    }


@router.get("/holders/{ticker}")
async def get_top_holders(ticker: str):
    """
    获取沪深港通个股的 Top 机构持仓明细 (南下/北向资金代理追踪)

    Args:
        ticker: 标的代码

    Returns:
        dict: {"status": "success", "data": List[HolderData]}
    """
    # 美股暂不支持沪深港通机构持仓明细查询
    if ticker.startswith("US."):
        return {"status": "warning", "message": "美股暂不支持沪深港通机构持仓明细查询"}

    # 格式化 ticker 给 AKShare 使用 (例如 HK.00700 -> 00700, US 标的直接拦截)
    symbol = ticker.split(".")[-1] if "." in ticker else ticker

    # BE-ARCH-06c: 经 Facade 统一选源
    facade_res = await data_service.get_hsgt_holders(symbol)

    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "持仓数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)

    return {
        "status": "success",
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
    }


@router.get("/insider-marquee")
async def get_insider_marquee(limit: int = 10):
    """
    获取全市场显著高管内幕交易流水 (供 Dashboard 跑马灯展示)。
    数据由后台守护进程异步汇总并筛选出大额交易。
    """
    MARQUEE_KEY = "quant:insider_marquee"
    try:
        # 从 Redis ZSET 中取出分数最高（最新）的 limit 条
        # withscores=True 可以获取时间戳，但这里只需要内容
        raw_transactions = await redis_client.zrevrange(MARQUEE_KEY, 0, limit - 1)

        transactions = []
        for t in raw_transactions:
            if isinstance(t, (str, bytes, bytearray)):
                transactions.append(json.loads(t))

        return {"status": "success", "data": transactions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取内幕交易跑马灯数据失败: {str(e)}")  # noqa: E501


@router.get("/insider-transactions")
async def get_insider_transactions(ticker: str, limit: int = 50):
    """
    获取个股高管内幕交易记录，供前端气泡图渲染

    Args:
        ticker: 标的代码
        limit: 返回数量限制

    Returns:
        dict: {"status": "success", "data": List[InsiderTransactionData]}
    """
    # 优先走 DataSourcePort + FinnhubAdapter (insider_trading)，失败回退模拟数据
    real = await _fetch_finnhub_insider(ticker, limit)
    if real is not None:
        return {"status": "success", "data": real[:limit], "source": "finnhub"}

    # 真实源不可用时的本地模拟数据（供前端联调）
    from datetime import datetime, timedelta

    mock_transactions = [
        {
            "date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            "name": f"CEO {random.choice(['Smith', 'Johnson', 'Williams'])}",
            "transaction_type": "Sale",
            "shares": random.randint(10000, 100000),
            "price": round(random.uniform(100, 300), 2),
            "value": round(random.uniform(1000000, 30000000), 2),
        },
        {
            "date": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
            "name": f"CFO {random.choice(['Brown', 'Davis', 'Miller'])}",
            "transaction_type": "Purchase",
            "shares": random.randint(1000, 10000),
            "price": round(random.uniform(90, 250), 2),
            "value": round(random.uniform(100000, 2500000), 2),
        },
    ]

    return {
        "status": "success",
        "data": mock_transactions[:limit],
        "source": "mock_insider_data",
    }


@router.get("/analyst-vs-fundamental/{ticker}")
async def get_analyst_vs_fundamental(ticker: str):
    """G7 · 卖方分析师共识 vs 实际基本面（交叉验证面板）。

    并发聚合 Futu 分析师共识（F4-4，卖方观点）与 G1 真基本面三源合并，
    派生分析师目标价上行空间并给出交叉验证结论。
    注意：分析师共识是卖方观点而非事实，响应显式标注 consensus_is_third_party_expectation。
    """
    res = await data_service.get_analyst_vs_actual(ticker)
    if not res.is_success or not res.data:
        err_msg = res.error.message if res.error else "未知错误"
        # BE-13 方案 B：扁平 payload 交由中间件统一包信封
        return {
            "message": f"[{ticker}] 卖方共识vs基本面交叉验证不可用: {err_msg}",
            "data": {},
            "source": f"facade+{res.source}",
            "degraded": True,
        }

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封
    # facade 返回的 res.data = {panel, analyst_consensus, fundamental_merged}，
    # 业务字段在 panel 子键，前端 analyst-vs-fundamental-panel 读 res.data.panel
    return {
        **res.data,
        "source": f"facade+{res.source}",
        "degraded": res.status == ResultStatus.DEGRADED,
    }
