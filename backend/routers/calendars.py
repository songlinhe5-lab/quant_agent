"""全球市场日历 Calendars 路由 (FE-PROD-05)

对标 yfinance 顶部 Markets 横向滚动条布局：按类目聚合的大类资产行情快照 +
全球市场交易时段矩阵 + 分红 / IPO 日程。

设计文档：docs/01 §十六（V2.3 新增）
数据源约束：docs/14 §10 / AGENTS §10（外部源经统一接口，本路由仅消费 Redis 缓存与 Finnhub）

端点（前缀 /api/v1/calendars）：
  GET /snapshot    按类目聚合的大类资产行情（对标 yfinance 横向滚动条）
  GET /hours        全球市场交易时段世界时钟矩阵
  GET /dividends    分红日历（Finnhub 优先，未配置 API Key 优雅降级）
  GET /ipos         IPO 日历（Finnhub 优先，未配置 API Key 优雅降级）
"""

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

try:
    import zoneinfo
except ImportError:  # pragma: no cover
    zoneinfo = None

from backend.core.redis_client import redis_client

router = APIRouter(prefix="/calendars", tags=["Calendars"])

# 用于防范缓存击穿的细粒度锁池
_cal_locks: dict[str, asyncio.Lock] = {}

# ── 类目 → 标的配置 ────────────────────────────────────────────────────────
# 扩展自 macro.py 的 19 个核心宏观指标，覆盖 7 大类目 ≥ 50 标的。
# 每个 tile: {symbol 内部代码, name 中文名, yf Yahoo 代码}
CALENDAR_CATEGORIES: list[dict] = [
    {
        "key": "us_markets", "display_name": "US Markets",
        "tz": "America/New_York", "open": (9, 30), "close": (16, 0),
        "tiles": [
            {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"},
            {"symbol": "ES", "name": "S&P 500 期指", "yf": "ES=F"},
            {"symbol": "IXIC", "name": "NASDAQ 综合", "yf": "^IXIC"},
            {"symbol": "NQ", "name": "纳指期货", "yf": "NQ=F"},
            {"symbol": "DJI", "name": "道琼斯指数", "yf": "^DJI"},
            {"symbol": "RTY", "name": "罗素 2000", "yf": "^RUT"},
            {"symbol": "VIX", "name": "VIX 恐慌指数", "yf": "^VIX"},
            {"symbol": "SPY", "name": "SPDR 标普 ETF", "yf": "SPY"},
            {"symbol": "QQQ", "name": "纳指 100 ETF", "yf": "QQQ"},
        ],
    },
    {
        "key": "eu_markets", "display_name": "Europe Markets",
        "tz": "Europe/London", "open": (8, 0), "close": (16, 30),
        "tiles": [
            {"symbol": "UKX", "name": "富时 100", "yf": "^FTSE"},
            {"symbol": "PX1", "name": "CAC 40", "yf": "^FCHI"},
            {"symbol": "DAX", "name": "德国 DAX", "yf": "^GDAXI"},
            {"symbol": "SX5E", "name": "欧洲斯托克 50", "yf": "^STOXX50E"},
            {"symbol": "IBEX", "name": "西班牙 IBEX", "yf": "^IBEX"},
            {"symbol": "AEX", "name": "荷兰 AEX", "yf": "^AEX"},
        ],
    },
    {
        "key": "asia_markets", "display_name": "Asia Markets",
        "tz": "Asia/Hong_Kong", "open": (9, 30), "close": (16, 0),
        "tiles": [
            {"symbol": "HSI", "name": "恒生指数", "yf": "^HSI"},
            {"symbol": "HSTECH", "name": "恒生科技", "yf": "HSTECH.HK"},
            {"symbol": "N225", "name": "日经 225", "yf": "^N225"},
            {"symbol": "KS11", "name": "韩国 KOSPI", "yf": "^KS11"},
            {"symbol": "KWEB", "name": "中概互联", "yf": "KWEB"},
            {"symbol": "SSE", "name": "上证指数", "yf": "000001.SS"},
            {"symbol": "SENSEX", "name": "印度 SENSEX", "yf": "^BSESN"},
        ],
    },
    {
        "key": "crypto", "display_name": "Crypto",
        "tz": None, "open": None, "close": None,  # 7x24 全天候交易
        "tiles": [
            {"symbol": "BTC", "name": "比特币", "yf": "BTC-USD"},
            {"symbol": "ETH", "name": "以太坊", "yf": "ETH-USD"},
            {"symbol": "SOL", "name": "Solana", "yf": "SOL-USD"},
            {"symbol": "BNB", "name": "BNB", "yf": "BNB-USD"},
            {"symbol": "XRP", "name": "XRP", "yf": "XRP-USD"},
            {"symbol": "DOGE", "name": "狗狗币", "yf": "DOGE-USD"},
        ],
    },
    {
        "key": "rates", "display_name": "Rates & Bonds",
        "tz": "America/New_York", "open": (8, 0), "close": (17, 0),
        "tiles": [
            {"symbol": "TNX", "name": "10Y 美债收益率", "yf": "^TNX"},
            {"symbol": "TYX", "name": "30Y 美债收益率", "yf": "^TYX"},
            {"symbol": "FVX", "name": "5Y 美债收益率", "yf": "^FVX"},
            {"symbol": "IRX", "name": "13W 美债收益率", "yf": "^IRX"},
            {"symbol": "TWO", "name": "2Y 美债收益率", "yf": "^TWO"},
            {"symbol": "TLT", "name": "20Y+ 国债 ETF", "yf": "TLT"},
        ],
    },
    {
        "key": "commodities", "display_name": "Commodities",
        "tz": "America/New_York", "open": (8, 0), "close": (17, 0),
        "tiles": [
            {"symbol": "XAU", "name": "黄金", "yf": "GC=F"},
            {"symbol": "XAG", "name": "白银", "yf": "SI=F"},
            {"symbol": "WTI", "name": "WTI 原油", "yf": "CL=F"},
            {"symbol": "BZ", "name": "布伦特原油", "yf": "BZ=F"},
            {"symbol": "HG", "name": "伦铜", "yf": "HG=F"},
            {"symbol": "NG", "name": "天然气", "yf": "NG=F"},
            {"symbol": "PL", "name": "铂金", "yf": "PL=F"},
        ],
    },
    {
        "key": "currencies", "display_name": "Currencies",
        "tz": "America/New_York", "open": (8, 0), "close": (17, 0),
        "tiles": [
            {"symbol": "DXY", "name": "美元指数", "yf": "DX-Y.NYB"},
            {"symbol": "EURUSD", "name": "EUR/USD", "yf": "EURUSD=X"},
            {"symbol": "USDJPY", "name": "USD/JPY", "yf": "JPY=X"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "yf": "GBPUSD=X"},
            {"symbol": "USDCNH", "name": "USD/CNH", "yf": "USDCNH=X"},
            {"symbol": "AUDUSD", "name": "AUD/USD", "yf": "AUDUSD=X"},
            {"symbol": "USDCAD", "name": "USD/CAD", "yf": "USDCAD=X"},
        ],
    },
]

# 交易时段矩阵预置（Hours Tab）
_CALENDAR_TIMEZONES = [
    {"code": "HKT", "label": "香港", "tz": "Asia/Hong_Kong"},
    {"code": "UTC", "label": "UTC", "tz": "Etc/UTC"},
    {"code": "ET", "label": "纽约", "tz": "America/New_York"},
    {"code": "LON", "label": "伦敦", "tz": "Europe/London"},
    {"code": "TTY", "label": "东京", "tz": "Asia/Tokyo"},
]
_CALENDAR_MARKETS = [
    {"name": "US (NYSE)", "tz": "America/New_York", "open": (9, 30), "close": (16, 0)},
    {"name": "HK (HKEX)", "tz": "Asia/Hong_Kong", "open": (9, 30), "close": (16, 0)},
    {"name": "EU (LSE)", "tz": "Europe/London", "open": (8, 0), "close": (16, 30)},
    {"name": "JP (TSE)", "tz": "Asia/Tokyo", "open": (9, 0), "close": (15, 0)},
    {"name": "Crypto", "tz": None, "open": None, "close": None},
]

_STALE_TTL_SECONDS = 1800  # 30 分钟未更新即判定 STALE


# ── 工具函数 ──────────────────────────────────────────────────────────────
def _parse_updated_at(iso_like: str) -> Optional[datetime]:
    """尽力解析 yf 缓存里的 Date 字段（'2026-07-16' 或 '2026-07-16T12:00:00'）。"""
    try:
        if not iso_like:
            return None
        if "T" in iso_like:
            return datetime.fromisoformat(iso_like.replace("Z", "+00:00"))
        # 仅日期（如 '2026-07-16'）：视作 UTC 午夜，避免 naive/aware 相减报错
        return datetime.strptime(iso_like, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _market_session_state(
    tz_name: Optional[str],
    open_hm: Optional[tuple[int, int]],
    close_hm: Optional[tuple[int, int]],
) -> tuple[bool, Optional[str]]:
    """返回 (是否交易中, 下一个开盘/收盘时间 ISO)。tz 为 None 视为 7x24 开盘。"""
    if not tz_name or not open_hm or zoneinfo is None:
        return True, None
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)
        # 周末：计算下个周一开盘时间
        if now.weekday() >= 5:
            days_to_mon = (7 - now.weekday()) % 7 or 7
            nxt = (now + timedelta(days=days_to_mon)).replace(
                hour=open_hm[0], minute=open_hm[1], second=0, microsecond=0
            )
            return False, nxt.isoformat()
        now_min = now.hour * 60 + now.minute
        open_min = open_hm[0] * 60 + open_hm[1]
        close_min = close_hm[0] * 60 + close_hm[1]
        if open_min <= now_min < close_min:
            return True, None
        if now_min < open_min:
            nxt = now.replace(hour=open_hm[0], minute=open_hm[1], second=0, microsecond=0)
        else:
            nxt = (now + timedelta(days=1)).replace(
                hour=open_hm[0], minute=open_hm[1], second=0, microsecond=0
            )
        return False, nxt.isoformat()
    except Exception:
        return True, None


async def _fetch_calendar_tile(cfg: dict, category_key: str) -> dict:
    """从 yf 守护进程写入的 Redis 缓存读取单个标的，组装 CalendarTile 契约。"""
    symbol = cfg["symbol"]
    name = cfg["name"]
    yf_code = cfg["yf"]
    stale_ttl = _STALE_TTL_SECONDS
    try:
        cache_key = f"yf_macro_cache_{yf_code}"
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            records = json.loads(cached_data)
            if records and len(records) > 0:
                closes: list[float] = []
                for r in records:
                    c_val = r.get("Close")
                    if c_val is None:
                        c_val = next(
                            (v for k, v in r.items() if str(k).startswith("('Close'")),
                            None,
                        )
                    if c_val is not None:
                        closes.append(float(c_val))
                if len(closes) > 0:
                    last_close = closes[-1]
                    prev_close = closes[-2] if len(closes) > 1 else last_close
                    change_abs = round(last_close - prev_close, 4)
                    change_pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0
                    updated_raw = records[-1].get("Date") or records[-1].get("date")
                    updated_at = str(updated_raw) if updated_raw else None
                    is_stale = False
                    if updated_at:
                        dt = _parse_updated_at(updated_at)
                        if dt:
                            is_stale = (datetime.now(timezone.utc) - dt).total_seconds() > stale_ttl
                    return {
                        "symbol": symbol,
                        "display_name": name,
                        "yf_ticker": yf_code,
                        "price": round(last_close, 4),
                        "change_abs": change_abs,
                        "change_pct": round(change_pct, 2),
                        "sparkline": closes[-60:],
                        "updated_at": updated_at,
                        "is_stale": is_stale,
                        "source": "YFinance",
                        "category": category_key,
                    }
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ [Calendars] 解析 {symbol} 失败: {e}")
    return {
        "symbol": symbol,
        "display_name": name,
        "yf_ticker": yf_code,
        "price": 0.0,
        "change_abs": 0.0,
        "change_pct": 0.0,
        "sparkline": [],
        "updated_at": None,
        "is_stale": True,
        "source": "N/A",
        "category": category_key,
    }


async def _fetch_calendar_snapshot() -> dict:
    """聚合所有类目的行情快照。"""
    categories = []
    for cat in CALENDAR_CATEGORIES:
        tiles = await asyncio.gather(
            *[_fetch_calendar_tile(t, cat["key"]) for t in cat["tiles"]]
        )
        is_open, next_change = _market_session_state(cat.get("tz"), cat.get("open"), cat.get("close"))
        categories.append({
            "category": cat["key"],
            "display_name": cat["display_name"],
            "is_market_open": is_open,
            "next_session_change": next_change,
            "tiles": [t for t in tiles if t is not None],
        })
    return {
        "timezone": "Asia/Hong_Kong",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "data_sources_health": {},
    }


# ── 端点 ──────────────────────────────────────────────────────────────────
@router.get("/snapshot")
async def get_calendars_snapshot(
    force_refresh: bool = Query(False, description="强制绕过缓存拉取最新数据"),
):
    """全球市场日历快照：按类目聚合的大类资产行情（对标 yfinance Markets 横向滚动条）"""
    cache_key = "calendars_snapshot"
    try:
        if not force_refresh:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        if cache_key not in _cal_locks:
            _cal_locks[cache_key] = asyncio.Lock()
        async with _cal_locks[cache_key]:
            if not force_refresh:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)

            snapshot = await _fetch_calendar_snapshot()
            data = {
                "status": "success",
                "data": snapshot,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            ttl = 120 + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(data), ex=ttl)
            return data
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ [Calendars] 快照获取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hours")
async def get_calendars_hours():
    """全球市场交易时段矩阵（世界时钟），供 Hours Tab 渲染 24h × 时区网格。"""
    try:
        zones = []
        for z in _CALENDAR_TIMEZONES:
            now_str = None
            if zoneinfo is not None:
                try:
                    now_str = datetime.now(zoneinfo.ZoneInfo(z["tz"])).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    now_str = None
            zones.append({"code": z["code"], "label": z["label"], "tz": z["tz"], "current_time": now_str})

        markets = []
        for m in _CALENDAR_MARKETS:
            is_open, next_change = _market_session_state(m["tz"], m.get("open"), m.get("close"))
            markets.append({
                "name": m["name"],
                "tz": m["tz"],
                "open": f"{m['open'][0]:02d}:{m['open'][1]:02d}" if m.get("open") else None,
                "close": f"{m['close'][0]:02d}:{m['close'][1]:02d}" if m.get("close") else None,
                "is_open": is_open,
                "next_session_change": next_change,
            })

        data = {"timezones": zones, "markets": markets}
        return {"status": "success", "data": data, "updated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ [Calendars] 时段矩阵获取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _finnhub_key() -> str:
    return os.getenv("FINNHUB_API_KEY", "")


@router.get("/dividends")
async def get_calendars_dividends(
    symbol: Optional[str] = Query(None, description="可选：指定标的代码（如 AAPL）"),
):
    """分红日历（优先 Finnhub，未配置 API Key 时优雅降级返回 unavailable）。"""
    api_key = _finnhub_key()
    if not api_key:
        return {
            "status": "unavailable",
            "data": [],
            "message": "FINNHUB_API_KEY 未配置，分红日历暂不可用",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    cache_key = f"calendars_dividends:{symbol or 'all'}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:  # noqa: BLE001
        pass
    try:
        params = {"token": api_key, "symbol": symbol} if symbol else {"token": api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://finnhub.io/api/v1/calendar/dividend", params=params)
            payload = resp.json()
            items = payload.get("dividendCalendar", []) if isinstance(payload, dict) else []
            data = {"status": "success", "data": items, "source": "finnhub"}
            await redis_client.set(cache_key, json.dumps(data), ex=21600)
            return data
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "data": [],
            "message": f"Finnhub 分红日历拉取失败: {e}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/ipos")
async def get_calendars_ipos():
    """IPO 日历（优先 Finnhub，未配置 API Key 时优雅降级返回 unavailable）。"""
    api_key = _finnhub_key()
    if not api_key:
        return {
            "status": "unavailable",
            "data": [],
            "message": "FINNHUB_API_KEY 未配置，IPO 日历暂不可用",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    cache_key = "calendars_ipos:all"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:  # noqa: BLE001
        pass
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/ipo", params={"token": api_key}
            )
            payload = resp.json()
            items = payload.get("ipoCalendar", []) if isinstance(payload, dict) else []
            data = {"status": "success", "data": items, "source": "finnhub"}
            await redis_client.set(cache_key, json.dumps(data), ex=21600)
            return data
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "data": [],
            "message": f"Finnhub IPO 日历拉取失败: {e}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
