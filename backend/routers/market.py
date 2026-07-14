import asyncio
import json
import os
import random
import re
import time

import pandas as pd
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.core.logger import logger
from backend.core.metrics import WS_MESSAGES_SENT
from backend.core.redis_client import redis_client
from backend.app.market_data import market_data
from backend.core.ticker_format import format_ticker
from backend.core.ticker_format import format_yf_ticker as _to_yf_ticker
from backend.services.data_source_router import data_source_router
from backend.services.kline_warehouse import kline_warehouse

# 引入核心市场引擎和工具实例
from backend.services.market_engine import manager
from backend.services.ticker_service import ticker_service

# BE-15: JWT 鉴权配置
_SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
_ALGORITHM = "HS256"

# BE-15: WebSocket 心跳超时（秒）
_WS_HEARTBEAT_TIMEOUT = 60

# 全局异步锁池，用于防止各个标的的行情与新闻接口发生缓存击穿 (Cache Stampede)
_news_locks = {}


class SyncKlineRequest(BaseModel):
    ticker: str
    interval: str = "1d"
    force_full: bool = False


router = APIRouter(prefix="/market", tags=["Market & Portfolio"])


@router.websocket("/quotes/ws")
async def quotes_websocket(websocket: WebSocket):
    """
    多标的行情 WebSocket 推送（BE-15 增强版）
    - 连接鉴权：Query String ?token=<jwt> 校验
    - ping/pong 心跳保活：超时 60s 无心跳自动断开
    - 订阅去重：重复 subscribe 同一 ticker 不会重复注册
    - 背压保护：慢客户端缓冲区超过阈值时自动 drop-oldest
    """
    # BE-15: 连接鉴权 — 从 QueryString 提取 token 并校验
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    try:
        from jose import jwt as _jwt

        payload = _jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        username = payload.get("sub")
        if not username:
            await websocket.close(code=4003, reason="Invalid token payload")
            return
    except Exception:
        await websocket.close(code=4002, reason="Token expired or invalid")
        return

    await manager.connect(websocket)
    logger.info(f"[WS] 用户 {username} 已连接 (认证通过)")
    last_heartbeat = time.monotonic()

    try:
        while True:
            data = await websocket.receive_text()
            last_heartbeat = time.monotonic()  # 重置心跳计时器
            try:
                msg = json.loads(data)
                if not isinstance(msg, dict):
                    await websocket.send_text(
                        json.dumps(
                            {
                                "code": 2001,
                                "msg": "Payload must be a JSON object",
                                "data": None,
                                "ts": int(time.time() * 1000),
                            }
                        )
                    )
                    continue
                action = msg.get("action")
                req_tickers = msg.get("tickers", [])
                if isinstance(req_tickers, str):
                    req_tickers = [t.strip() for t in req_tickers.split(",") if t.strip()]  # noqa: E501

                # 核心防御：自动格式化前端传来的各种混用格式为 Futu 官方强前缀格式
                req_tickers = [format_ticker(t) for t in req_tickers]

                if action == "subscribe":
                    # BE-15: 订阅去重 — 过滤已订阅的 ticker
                    current_subs = manager.subscriptions.get(websocket, set())
                    new_tickers = [t for t in req_tickers if t not in current_subs]
                    if new_tickers:
                        last_ids = msg.get("last_ids", {})
                        manager.subscribe(websocket, new_tickers, last_ids)
                    WS_MESSAGES_SENT.labels(type="system").inc()
                    await websocket.send_text(
                        json.dumps(
                            {
                                "code": 0,
                                "msg": "ok",
                                "data": {
                                    "subscribed": new_tickers,
                                    "already_subscribed": [t for t in req_tickers if t not in new_tickers],
                                },  # noqa: E501
                                "ts": int(time.time() * 1000),
                            }
                        )
                    )
                elif action == "unsubscribe":
                    manager.unsubscribe(websocket, req_tickers)
                    WS_MESSAGES_SENT.labels(type="system").inc()
                    await websocket.send_text(
                        json.dumps(
                            {
                                "code": 0,
                                "msg": "ok",
                                "data": {"unsubscribed": req_tickers},
                                "ts": int(time.time() * 1000),
                            }
                        )
                    )
                elif action == "ping":
                    # BE-15: 增强型心跳响应
                    WS_MESSAGES_SENT.labels(type="system").inc()
                    _subs = manager.subscriptions.get(websocket, set())
                    await websocket.send_text(
                        json.dumps(
                            {
                                "code": 0,
                                "type": "pong",
                                "data": {
                                    "client_ts": msg.get("ts"),
                                    "server_ts": int(time.time() * 1000),
                                    "subscriptions": len(_subs),
                                },
                                "ts": int(time.time() * 1000),
                            }
                        )
                    )
                else:
                    WS_MESSAGES_SENT.labels(type="error").inc()
                    await websocket.send_text(
                        json.dumps(
                            {
                                "code": 2001,
                                "msg": f"Unknown action: {action}",
                                "data": None,
                                "ts": int(time.time() * 1000),
                            }
                        )
                    )
            except json.JSONDecodeError:
                WS_MESSAGES_SENT.labels(type="error").inc()
                await websocket.send_text(
                    json.dumps(
                        {
                            "code": 2001,
                            "msg": "Invalid JSON",
                            "data": None,
                            "ts": int(time.time() * 1000),
                        }
                    )
                )

            # BE-15: 心跳超时检查
            if time.monotonic() - last_heartbeat > _WS_HEARTBEAT_TIMEOUT:
                logger.warning(f"[WS] 用户 {username} 心跳超时，主动断开")
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info(f"[WS] 用户 {username} 已断开")
    except Exception as e:
        manager.disconnect(websocket)
        logger.error(f"[WS] 异常断开: {e}")


@router.get("/futu/status")
async def get_futu_status():
    """供前端面板感知底层 OpenD 核心连接状态
    💡 实时探测 OpenD 端口，而非仅依赖内存中的状态标记
    """
    # 💡 实时探测 OpenD 是否可连接（2秒超时）
    is_reachable = market_data.is_opend_reachable(timeout=2.0)

    # 💡 如果探测失败但状态仍显示 CONNECTED，说明连接已断开，需要更新状态
    if not is_reachable and market_data.status == "CONNECTED":
        market_data.status = "DISCONNECTED"
        market_data.error_msg = "OpenD 连接已断开"
        print("⚠️ [Market API] OpenD 实时探测失败，状态已更新为 DISCONNECTED")

    # 💡 如果探测成功但状态显示 DISCONNECTED/ERROR，尝试重新连接
    if is_reachable and market_data.status != "CONNECTED":
        print("ℹ️ [Market API] OpenD 实时探测成功，尝试重新连接...")
        market_data.connect()

    return {
        "status": market_data.status,
        "error": market_data.error_msg,
        "reachable": is_reachable,  # 💡 新增：实际探测结果
    }


@router.get("/health/services")
async def get_services_health():
    """获取所有底层数据源与交易网关的健康及熔断状态"""
    import os

    health_data = []

    # 1. Futu OpenD - 💡 实时探测而非仅依赖内存状态
    is_opend_reachable = market_data.is_opend_reachable(timeout=2.0)
    f_status = "healthy" if is_opend_reachable else "disconnected"
    f_msg = market_data.error_msg if not is_opend_reachable else "已连接"

    # 💡 同步更新内存状态
    if not is_opend_reachable and market_data.status == "CONNECTED":
        market_data.status = "DISCONNECTED"
        market_data.error_msg = "OpenD 连接已断开"
    if is_opend_reachable and market_data.status != "CONNECTED":
        market_data.connect()
        f_status = "healthy" if market_data.status == "CONNECTED" else "disconnected"
        f_msg = "已连接" if market_data.status == "CONNECTED" else market_data.error_msg

    health_data.append(
        {
            "name": "Futu OpenD",
            "status": f_status,
            "cooldown_remaining": 0,
            "message": f_msg,
            "reachable": is_opend_reachable,  # 💡 实际探测结果
        }
    )

    # 2. AKShare (东方财富)
    health_data.append(market_data.ak_health_status())

    # 3. YFinance (雅虎财经)
    health_data.append(market_data.yf_health_status())

    # 4. 数据源路由服务 (跨节点路由)
    router_status = await data_source_router.get_health_status()
    health_data.append(
        {
            "name": "DataSourceRouter",
            "status": "healthy" if router_status.get("router_enabled") else "disabled",
            "message": f"路由状态: {'enabled' if router_status.get('router_enabled') else 'disabled'}, 节点数: {len(router_status.get('nodes', {}))}",
        }
    )

    # 5. 其他外部 API
    for name, key_env in [("Finnhub", "FINNHUB_API_KEY"), ("FRED", "FRED_API_KEY")]:
        has_key = bool(os.getenv(key_env))
        health_data.append(
            {
                "name": name,
                "status": "healthy" if has_key else "warning",
                "cooldown_remaining": 0,
                "message": "正常" if has_key else f"未配置 {key_env}",
            }
        )

    return {"status": "success", "data": health_data}


@router.get("/quote")
async def get_quote(ticker: str):
    """提供给前端的高频统一行情接口（直接过服务高速缓存，不再调用 Tool）"""
    res = await market_data.get_quote(ticker=ticker)
    # 💡 如果富途获取失败（例如美股、加密货币、外汇等无权限标的），平滑降级至雅虎财经
    if res.get("status") == "error":
        msg = res.get("message", "")
        if "原生不支持" not in msg:
            print(f"⚠️ [Quote] 券商数据获取 {ticker} 失败 ({msg})，准备降级...")

        # 💡 架构增强：针对 A 股，优先使用本土高可用实时数据源 AKShare（通过路由服务）
        is_a_share = ticker.startswith("SH.") or ticker.startswith("SZ.")
        if is_a_share:
            ak_res = await data_source_router.fetch_akshare("stock_quote", ticker=ticker)
            if ak_res.get("status") == "success":
                return ak_res
            print(f"⚠️ [Quote] AKShare 获取 {ticker} 失败 ({ak_res.get('message')})，继续降级雅虎财经...")  # noqa: E501

        yf_ticker = _to_yf_ticker(ticker)
        yf_result = await data_source_router.fetch_yfinance(yf_ticker, "history", period="1d")
        success = yf_result.get("success", False)
        info = yf_result.get("data")
        msg = yf_result.get("message", "")

        if success and info and info.get("regularMarketPrice") is not None:
            change = info.get("regularMarketChange", 0.0)
            change_pct = info.get("regularMarketChangePercent", 0.0) * 100

            # yfinance 针对部分标的（如指数）不会返回 change，需要手动计算
            if change is None or change_pct is None:
                price = info.get("regularMarketPrice")
                prev_close = info.get("previousClose")
                if price is not None and prev_close is not None and prev_close != 0:
                    change = price - prev_close
                    change_pct = (change / prev_close) * 100

            volume = info.get("regularMarketVolume", 0)
            return {
                "status": "success",
                "data": {
                    "ticker": ticker,
                    "last_price": info.get("regularMarketPrice"),
                    "open": info.get("regularMarketOpen"),  # noqa: E501
                    "high": info.get("regularMarketDayHigh"),
                    "low": info.get("regularMarketDayLow"),
                    "prev_close": info.get("previousClose"),  # noqa: E501
                    "volume": volume,
                    "turnover": volume * info.get("regularMarketPrice", 0),
                    "change_val": change,
                    "change_pct": change_pct,  # noqa: E501
                    "amplitude": (
                        (info.get("regularMarketDayHigh", 0) - info.get("regularMarketDayLow", 0))
                        / info.get("previousClose", 1)
                        * 100
                        if info.get("previousClose")
                        else 0
                    ),  # noqa: E501
                    "volume_str": f"{volume / 1_000_000:.2f}M" if volume > 1_000_000 else f"{volume / 1_000:.2f}K",  # noqa: E501
                },
                "source": "yfinance_fallback",
            }
        else:
            raise HTTPException(status_code=400, detail=f"Futu: {res.get('message')}, YFinance: {msg}")  # noqa: E501
    return res


class BatchQuoteRequest(BaseModel):
    tickers: list[str]


@router.post("/quotes/batch")
async def get_batch_quotes_from_cache(req: BatchQuoteRequest):
    """💡 从 Redis 缓存批量获取自选列表行情数据（非聚焦 ticker 使用）"""
    results = {}
    for ticker in req.tickers:
        # 💡 优先从 Redis 缓存获取（yf_macro_cache 由 macro_data_daemon 定期更新）
        yf_code = _to_yf_ticker(ticker)
        cache_key = f"yf_macro_cache_{yf_code}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                results[ticker] = {
                    "ticker": ticker,
                    "last_price": data.get("last_price") or data.get("close", 0),
                    "change_pct": data.get("change_pct", "0.0%"),
                    "volume_str": data.get("volume_str", "--"),
                    "source": "redis_cache",
                    "status": "CACHED",
                }
                continue
        except Exception:
            pass

        # 💡 缓存未命中，标记为需要实时获取
        results[ticker] = {
            "ticker": ticker,
            "last_price": 0,
            "change_pct": "0.0%",
            "volume_str": "--",
            "source": "none",
            "status": "NO_DATA",
        }

    return {"status": "success", "data": results}


@router.post("/kline/sync")
async def sync_kline_warehouse(req: SyncKlineRequest):
    """前端手动触发：强制拉取/补全本地 K 线数仓数据"""
    # 将前端的通用周期转换为富途底层的 ktype
    interval_map = {
        "1d": "K_DAY",
        "1m": "K_1M",
        "5m": "K_5M",
        "15m": "K_15M",
        "1h": "K_60M",
    }  # noqa: E501
    ktype = interval_map.get(req.interval, "K_DAY")

    try:
        print(f"📦 [Market API] 收到前端手动数据同步请求: {req.ticker} ({req.interval})")  # noqa: E501
        # 调用本地数仓的更新方法 (自动执行增量追加或全量降级拉取)
        success = await kline_warehouse.update_ticker(req.ticker, ktype=ktype, force_full=req.force_full)  # noqa: E501

        if success:
            return {
                "status": "success",
                "message": f"{req.ticker} ({req.interval}) 历史数据已成功同步并安全落库！可以继续回测。",
            }  # noqa: E501
        else:
            raise HTTPException(status_code=500, detail="数据同步失败，API额度可能已耗尽或标的退市。")  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(ticker: str, ktype: str = "K_DAY", num: int = 60):
    """提供给前端的 K 线图历史趋势接口（优先 Futu，平滑降级 YFinance）"""
    res = await market_data.get_history(ticker=ticker, ktype=ktype, num=num)

    if res.get("status") == "error":
        msg = res.get("message", "")
        if "原生不支持" not in msg:
            print(f"⚠️ [History] 券商数据获取 {ticker} 失败 ({msg})，准备降级...")

        # 💡 架构增强：针对 A 股日 K 线，优先使用 AKShare (规避 YFinance A股前复权异常问题)  # noqa: E501
        is_a_share = ticker.startswith("SH.") or ticker.startswith("SZ.")
        if is_a_share and ktype == "K_DAY":
            ak_res = await data_source_router.fetch_akshare("stock_history", ticker=ticker, num=num)
            if ak_res.get("status") == "success":
                return ak_res
            print(f"⚠️ [History] AKShare 获取 {ticker} K线受阻，继续降级雅虎财经...")

        yf_ticker = _to_yf_ticker(ticker)

        # 将内部周期映射至 YFinance 支持的粒度
        ktype_mapping = {
            "K_1M": "1m",
            "K_5M": "5m",
            "K_15M": "15m",
            "K_30M": "30m",
            "K_60M": "60m",
            "K_DAY": "1d",
            "K_WEEK": "1wk",
        }
        yf_interval = ktype_mapping.get(ktype, "1d")
        period = "7d" if yf_interval in ["1m", "5m"] else "1mo" if yf_interval in ["15m", "30m", "60m"] else "1y"  # noqa: E501

        yf_result = await data_source_router.fetch_yfinance(yf_ticker, "history", period=period, interval=yf_interval)
        success = yf_result.get("success", False)
        df_data = yf_result.get("data")
        msg = yf_result.get("message", "")

        if success and df_data is not None and not df_data.empty:
            # 💡 兼容 yfinance >= 0.2.40 返回的多级列索引 (MultiIndex) 结构
            if isinstance(df_data.columns, pd.MultiIndex):
                df_data.columns = df_data.columns.get_level_values(0)

            df_data = df_data.tail(num)

            # 💡 性能修复：彻底抛弃巨慢的 iterrows()，使用 Pandas 高效向量化转换推入线程池  # noqa: E501
            def _format_history(df):
                df_formatted = pd.DataFrame(
                    {
                        "time": pd.Series(df.index).astype(str).str.split("+").str[0].str.replace("T", " ").values,  # noqa: E501
                        "open": df["Open"].astype(float).values,
                        "high": df["High"].astype(float).values,
                        "low": df["Low"].astype(float).values,
                        "close": df["Close"].astype(float).values,
                        "volume": df["Volume"].astype(float).values,
                    }
                )
                return df_formatted.to_dict(orient="records")

            data_list = await asyncio.to_thread(_format_history, df_data)
            return {"status": "success", "data": data_list}
        else:
            raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.get("/option-chain")
async def get_option_chain(ticker: str, expiration_date: str = ""):
    """期权链：经 MarketDataGateway（Futu → YFinance 降级）。"""
    res = await market_data.get_option_chain(ticker, expiration_date)
    if isinstance(res, dict) and res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res



@router.get("/fund-flow")
async def get_fund_flow(ticker: str):
    res = await market_data.get_fund_flow(ticker)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.get("/tech-indicators")
async def get_tech_indicators(ticker: str, lookback_days: int = 1):
    # 1. 优先尝试从券商 (Futu) 获取历史数据计算指标
    futu_res = await market_data.get_history(ticker=ticker, ktype="K_DAY", num=120)
    if futu_res.get("status") == "success" and futu_res.get("data"):
        try:
            df = pd.DataFrame(futu_res["data"])
            if len(df) >= 30:  # 确保有足够天数计算中长期均线等
                df.rename(
                    columns={
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume",
                    },
                    inplace=True,
                )  # noqa: E501
                df["time"] = pd.to_datetime(df["time"])
                df.set_index("time", inplace=True)

                # 将券商数据喂给底层运算引擎
                res = await market_data.get_tech_indicators(
                    ticker=ticker, lookback_days=lookback_days, pre_fetched_df=df
                )
                if res.get("status") == "success":
                    return res
                print(f"⚠️ [Tech Indicators] 券商数据指标计算返回异常: {res.get('message')}，尝试降级...")  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Tech Indicators] 券商数据计算异常: {e}，尝试降级雅虎财经...")
    else:
        msg = futu_res.get("message", "")
        if "原生不支持" not in msg:
            print(f"⚠️ [Tech Indicators] 券商历史数据获取受阻 ({msg})，尝试降级雅虎财经...")  # noqa: E501

    # 2. 降级走雅虎财经（通过路由服务）
    yf_ticker = _to_yf_ticker(ticker)
    res = await data_source_router.fetch_yfinance(yf_ticker, "tech", lookback_days=lookback_days)  # noqa: E501
    if res.get("status") == "error" or not res.get("success", True):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.get("/search")
async def search_tickers(q: str):
    """本地离线极速股票代码模糊搜索 (双级缓存防熔断)"""
    # 1. 优先在本地词库中极速检索
    res = await ticker_service.search_tickers(q)

    # 2. 如果本地词库为空 (如初次启动还在后台拉取中)，则平滑降级给 YFinance（通过路由服务）
    if res.get("status") == "success" and not res.get("data"):
        print(f"⚠️ [Search] 本地词库暂无 '{q}'，降级使用 YFinance 搜索...")
        yf_result = await data_source_router.fetch_yfinance(q, "quote")
        res = yf_result if yf_result.get("success") else res

    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


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

                # 4. 确认缓存确实为空，执行真实的高耗时网络请求
                res = await market_data.get_company_news_fh(ticker, days_back=14)
                if res.get("status") == "success" and res.get("data"):
                    data = res.get("data", [])
                    data = sorted(data, key=lambda x: x.get("datetime", 0), reverse=True)[:limit]  # noqa: E501

                    formatted_news = []
                    for item in data:
                        dt = datetime.fromtimestamp(item.get("datetime", 0)).strftime("%Y-%m-%d %H:%M:%S")  # noqa: E501
                        formatted_news.append(
                            {
                                "time": dt,
                                "headline": item.get("headline", ""),
                                "summary": item.get("summary", ""),
                            }
                        )

                    result = {
                        "status": "success",
                        "count": len(formatted_news),
                        "data": formatted_news,
                        "source": "finnhub",
                    }  # noqa: E501
                    ttl = 900 + random.randint(10, 60)
                    await redis_client.setex(cache_key, ttl, json.dumps(result))
                    return result

                # 如果没有数据，返回空数组
                return {
                    "status": "success",
                    "count": 0,
                    "data": [],
                    "source": "empty",
                    "message": "暂无个股新闻数据",
                }  # noqa: E501
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
    from datetime import datetime, timezone

    # 💡 净化输入
    safe_ticker = re.sub(r"[^A-Za-z0-9_.-]", "", str(ticker))[:20].upper()
    if not safe_ticker:
        return {"status": "error", "message": "非法的股票代码参数"}

    events = []

    # 1. 获取财报日历事件
    try:
        yf_ticker = _to_yf_ticker(safe_ticker)
        # 💡 从 Finnhub 获取财报日历
        res = await market_data.get_earnings_calendar(days_ahead=days_ahead, days_back=days_back)
        if res.get("status") == "success":
            earnings_list = res.get("data", [])
            for item in earnings_list:
                if item.get("symbol") == yf_ticker or item.get("symbol") == safe_ticker:
                    events.append(
                        {
                            "date": item.get("date"),
                            "type": "earnings",
                            "label": f"Q{item.get('quarter', '?')} 财报",
                            "impact": "high",
                            "data": {
                                "epsEstimate": item.get("epsEstimate"),
                                "epsActual": item.get("epsActual"),
                            },
                        }
                    )
    except Exception as e:
        print(f"⚠️ [Events] 获取 {safe_ticker} 财报日历失败: {e}")

    # 2. 获取个股新闻（作为重大事件）
    try:
        news_res = await market_data.get_company_news_fh(safe_ticker, days_back=days_back)
        if news_res.get("status") == "success":
            news_list = news_res.get("data", [])
            # 💡 只取影响较大的新闻（根据关键词判断）
            high_impact_keywords = [
                "earnings",
                "revenue",
                "profit",
                "loss",
                "dividend",
                "split",
                "acquisition",
                "merger",
                "lawsuit",
                "sec",
                "fda",
                "approval",
            ]
            for item in news_list[:5]:  # 最多取 5 条
                headline = item.get("headline", "")
                # 💡 判断是否为高影响新闻
                is_high_impact = any(kw in headline.lower() for kw in high_impact_keywords)
                dt = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
                events.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "type": "news",
                        "label": headline[:50] + "..." if len(headline) > 50 else headline,
                        "impact": "high" if is_high_impact else "medium",
                        "data": {
                            "source": item.get("source"),
                            "url": item.get("url"),
                        },
                    }
                )
    except Exception as e:
        print(f"⚠️ [Events] 获取 {safe_ticker} 新闻失败: {e}")

    # 💡 按日期排序
    events.sort(key=lambda x: x.get("date", ""))

    return {
        "status": "success",
        "ticker": safe_ticker,
        "count": len(events),
        "data": events,
    }


@router.get("/fundamental/{ticker}")
async def get_fundamental(ticker: str):
    yf_ticker = _to_yf_ticker(ticker)
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

    # 1. 智能拦截：如果是宏观资产/指数，自动无缝路由给 fred_service 获取其特有的“基本面” (宏观序列)  # noqa: E501
    for key, fred_id in fred_macro_map.items():
        if key == upper_ticker or key in upper_ticker:
            res = await market_data.get_series_observations(fred_id, limit=5)
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

    # 💡 优先获取 Futu 的高质量数据，失败时再使用 YFinance 兜底，避免同时请求双数据源浪费资源  # noqa: E501
    # 组装最终结果
    final_data = {}
    futu_res = await market_data.get_fundamental(ticker)

    if futu_res.get("status") == "success" and futu_res.get("data"):
        final_data.update(futu_res["data"])
    else:
        # Futu 获取失败，才发起 YFinance 兜底请求（通过路由服务）
        yf_result = await data_source_router.fetch_yfinance(yf_ticker, "history", period="1d")
        yf_success = yf_result.get("success", False)
        yf_info = yf_result.get("data")
        yf_msg = yf_result.get("message", "")
        if not yf_success:
            raise HTTPException(
                status_code=400,
                detail=f"Futu: {futu_res.get('message')}, YFinance: {yf_msg}",
            )  # noqa: E501

        if yf_info:
            # 💡 新增：针对 ETF 类型返回专属提示与数据
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
                        "yield": f"{yf_info.get('yield', 0) * 100:.2f}%" if yf_info.get("yield") else None,  # noqa: E501
                        "beta": yf_info.get("beta"),
                    },
                }

            yf_results = {
                "ticker": ticker,
                "company_name": yf_info.get("shortName", ""),
                "trailing_PE": yf_info.get("trailingPE"),  # noqa: E501
                "forward_PE": yf_info.get("forwardPE"),
                "PEG_ratio": yf_info.get("pegRatio"),
                "price_to_book": yf_info.get("priceToBook"),  # noqa: E501
                "ROE": f"{yf_info.get('returnOnEquity', 0) * 100:.2f}%" if yf_info.get("returnOnEquity") else None,  # noqa: E501
                "short_ratio": yf_info.get("shortRatio"),
                "beta": yf_info.get("beta"),
            }
            final_data.update({k: v for k, v in yf_results.items() if v is not None})

    return {"status": "success", "data": final_data}


@router.get("/holders/{ticker}")
async def get_top_holders(ticker: str):
    """获取沪深港通个股的 Top 机构持仓明细 (南下/北向资金代理追踪)"""
    # 格式化 ticker 给 AKShare 使用 (例如 HK.00700 -> 00700, US 标的直接拦截)
    if ticker.startswith("US."):
        return {"status": "warning", "message": "美股暂不支持沪深港通机构持仓明细查询"}

    symbol = ticker.split(".")[-1] if "." in ticker else ticker
    res = await data_source_router.fetch_akshare("hsgt_holders", symbol=symbol)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


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
    """获取个股高管内幕交易记录，供前端气泡图渲染"""
    # 格式化 ticker (如 US.AAPL -> AAPL, 内部 service 已处理)
    res = await market_data.get_insider_transactions(ticker, limit)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res
