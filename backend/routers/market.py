import json
import os
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.core.logger import logger
from backend.core.metrics import WS_MESSAGES_SENT
from backend.core.redis_client import redis_client
from backend.core.ticker_format import format_ticker, format_yf_ticker

# Legacy OpenD 健康探测（仅用于 /futu/status 与 /health/services 端点）
from backend.services.adapters.legacy_market_data import market_data_gateway
from backend.services.datalake.kline_warehouse import kline_warehouse
from backend.services.datasource import ResultStatus

# BE-ARCH-06c: 新 Facade 行情领域服务（统一经 DataSourceRegistry 取数）
from backend.services.datasource.business import data_service
from backend.services.datasource.business import market_data_service as _facade_market
from backend.services.datasource.router import data_source_router

# BE-ARCH-07p: 进程内 broker/kline 实时缓存（消费 quant:broker:* / quant:kline:* 回灌）
from backend.services.datasource.subscription import subscription_service
from backend.services.fund_flow.ticker import ticker_service
from backend.services.market_engine import manager

# BE-15: JWT 鉴权配置
_SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
_ALGORITHM = "HS256"

# BE-15: WebSocket 心跳超时（秒）
_WS_HEARTBEAT_TIMEOUT = 60


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
    is_reachable = market_data_gateway.is_opend_reachable(timeout=2.0)

    # 💡 如果探测失败但状态仍显示 CONNECTED，说明连接已断开，需要更新状态
    if not is_reachable and market_data_gateway.status == "CONNECTED":
        market_data_gateway.status = "DISCONNECTED"
        market_data_gateway.error_msg = "OpenD 连接已断开"
        print("⚠️ [Market API] OpenD 实时探测失败，状态已更新为 DISCONNECTED")

    # 💡 如果探测成功但状态显示 DISCONNECTED/ERROR，尝试重新连接
    if is_reachable and market_data_gateway.status != "CONNECTED":
        print("ℹ️ [Market API] OpenD 实时探测成功，尝试重新连接...")
        market_data_gateway.connect()

    return {
        "status": market_data_gateway.status,
        "error": market_data_gateway.error_msg,
        "reachable": is_reachable,  # 💡 新增：实际探测结果
    }


@router.get("/health/services")
async def get_services_health():
    """获取所有底层数据源与交易网关的健康及熔断状态"""
    import os

    health_data = []

    # 1. Futu OpenD - 💡 实时探测而非仅依赖内存状态
    is_opend_reachable = market_data_gateway.is_opend_reachable(timeout=2.0)
    f_status = "healthy" if is_opend_reachable else "disconnected"
    f_msg = market_data_gateway.error_msg if not is_opend_reachable else "已连接"

    # 💡 同步更新内存状态
    if not is_opend_reachable and market_data_gateway.status == "CONNECTED":
        market_data_gateway.status = "DISCONNECTED"
        market_data_gateway.error_msg = "OpenD 连接已断开"
    if is_opend_reachable and market_data_gateway.status != "CONNECTED":
        market_data_gateway.connect()
        f_status = "healthy" if market_data_gateway.status == "CONNECTED" else "disconnected"
        f_msg = "已连接" if market_data_gateway.status == "CONNECTED" else market_data_gateway.error_msg

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
    health_data.append(market_data_gateway.ak_health_status())

    # 3. YFinance (雅虎财经)
    health_data.append(market_data_gateway.yf_health_status())

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
    """
    提供给前端的高频统一行情接口

    ✅ 已解耦数据源：基于 DataSourcePort Protocol + MarketDataService
    🛡️ 降级策略:
      - Futu (港美股优先)
      - AkShare (A 股兜底)
      - YFinance (加密货币/外汇兜底)

    Args:
        ticker: 标的代码

    Returns:
        dict: {"status": "success", "data": QuoteData, "source": str}

    Raises:
        HTTPException: 所有数据源均失败时抛出 400 错误
    """
    # BE-ARCH-06c: 统一走新 Facade 行情领域服务（经 DataSourceRegistry 选源 + 融合 + Stale 检测）
    try:
        facade_res = await _facade_market.get_quote(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Market API] Facade get_quote 异常: {exc}")
        raise HTTPException(status_code=500, detail=f"数据源调用异常: {exc}")

    if not facade_res.is_success:
        err_msg = facade_res.error.message if facade_res.error else "所有数据源失败"
        raise HTTPException(status_code=400, detail=err_msg)

    resp_status = "degraded" if facade_res.status == ResultStatus.DEGRADED else "success"
    return {
        "status": resp_status,
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
        "latency_ms": facade_res.latency_ms,
        "cached": facade_res.cached,
    }


class BatchQuoteRequest(BaseModel):
    tickers: list[str]


@router.post("/quotes/batch")
async def get_batch_quotes_from_cache(req: BatchQuoteRequest):
    """💡 从 Redis 缓存批量获取自选列表行情数据（非聚焦 ticker 使用）"""
    results = {}
    for ticker in req.tickers:
        # 💡 优先从 Redis 缓存获取（yf_macro_cache 由 macro_data_daemon 定期更新）
        yf_code = format_yf_ticker(ticker)
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
    """
    提供给前端的 K 线图历史趋势接口

    ✅ 已解耦数据源：基于 DataSourcePort Protocol + MarketDataService
    🛡️ 降级策略:
      - Futu (港美股优先)
      - AkShare (A 股兜底)
      - YFinance (通用兜底)

    Args:
        ticker: 标的代码
        ktype: K 线周期类型
        num: 向后取多少根 K 线

    Returns:
        dict: {"status": "success", "data": [KLineData]}
    """
    # BE-ARCH-06c: 统一走新 Facade
    facade_res = await _facade_market.get_history(ticker, ktype=ktype, num=num)
    if not facade_res.is_success or not facade_res.data:
        err_msg = facade_res.error.message if facade_res.error else "获取历史数据失败"
        raise HTTPException(status_code=400, detail=err_msg)

    return {
        "status": "success",
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
    }


@router.get("/option-chain")
async def get_option_chain(ticker: str, expiration_date: str = ""):
    """
    期权链数据接口 (Futu → YFinance 降级)

    Args:
        ticker: 标的代码
        expiration_date: 到期日 (YYYY-MM-DD)

    Returns:
        dict: {"status": "success", "data": OptionChain}
    """
    facade_res = await _facade_market.get_option_chain(ticker, expiration_date=expiration_date)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "期权链数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    if facade_res.status == ResultStatus.DEGRADED:
        err_msg = facade_res.error.message if facade_res.error else "期权链数据暂不可用"
        return {
            "status": "degraded",
            "message": err_msg,
            "data": facade_res.data,
            "source": f"facade+{facade_res.source}",
        }
    return {
        "status": "success",
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
    }


@router.get("/fund-flow")
async def get_fund_flow(ticker: str):
    """
    主力资金流向接口

    Args:
        ticker: 标的代码

    Returns:
        dict: {"status": "success", "data": FundFlowData}
    """
    facade_res = await _facade_market.get_fund_flow(ticker)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "资金流数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    return {
        "status": "success",
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
    }


@router.get("/warrant-chain")
async def get_warrant_chain(ticker: str):
    """
    港股窝轮/牛熊证链 (市场多空情绪分析，仅 HK 标的)

    Args:
        ticker: 港股代码

    Returns:
        dict: {"status": "success", "data": WarrantData}
    """
    # BE-ARCH-06c: 经 Facade 统一选源
    facade_res = await data_service.get_warrant_chain(ticker)
    if not facade_res.is_success:
        return {
            "status": "success",
            "data": [],
            "source": "not_implemented",
            "message": f"[{ticker}] 窝轮/牛熊证链数据暂不支持（数据源未实现 warrant_chain 能力）",
        }

    return {
        "status": "success",
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
    }


@router.get("/tech-indicators")
async def get_tech_indicators(ticker: str, lookback_days: int = 90):
    """
    技术指标计算接口 (MA/MACD/RSI 等)

    Args:
        ticker: 标的代码
        lookback_days: 回溯天数

    Returns:
        dict: {"status": "success", "data": TechIndicatorsData}
    """
    from backend.core.ticker_format import format_yf_ticker as format_yf_ticker

    # BE-ARCH-06c: 经 Facade 统一选源获取历史 K 线
    yf_ticker = format_yf_ticker(ticker)
    facade_res = await data_service.get_history(yf_ticker, num=lookback_days)

    if not facade_res.is_success or not facade_res.data:
        err_msg = facade_res.error.message if facade_res.error else "获取历史数据失败"
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch historical data for technical indicators: {err_msg}"
        )

    # ✅ 集成生产级技术指标计算引擎 (TechnicalIndicatorsPro)
    from backend.utils.technical_indicators_pro import calculate_technical_indicators

    indicators = calculate_technical_indicators(facade_res.data)

    return {
        "status": "success",
        "data": {
            "klines": facade_res.data[:10],  # 返回最近 10 根 K 线
            "indicators": indicators,  # 完整的计算结果
        },
        "source": f"facade+{facade_res.source}+custom_tech_indicators",
    }


@router.get("/search")
async def search_tickers(q: str):
    """
    股票代码模糊搜索 (优先本地词库，降级 YFinance)

    Args:
        q: 搜索关键词

    Returns:
        dict: {"status": "success", "data": [SearchResult]}
    """
    # 1. 优先在本地词库中极速检索
    res = await ticker_service.search_tickers(q)

    # 2. 如果本地词库为空，降级使用 YFinance 搜索
    if res.get("status") == "success" and not res.get("data"):
        print(f"⚠️ [Search] 本地词库暂无 '{q}'，降级使用 Facade 搜索...")
        facade_res = await data_service.get_quote(q, prefer_sources=["yfinance"])
        if facade_res.is_success:
            res = {"status": "success", "data": facade_res.data}

    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


# ────────────────────────────────────────────────────────────────────────────
# BE-ARCH-07p: 对外暴露 broker / kline 实时数据
# 数据来自 07h-2 的 SubscriptionService 进程内缓存（消费 quant:broker:{tk} /
# quant:kline:{tk} 频道回灌，TTL 5s）。仅作只读转发，不引入任何外部直连。
# ────────────────────────────────────────────────────────────────────────────


@router.get("/broker/{symbol}")
async def get_broker_realtime(symbol: str):
    """获取标的实时盘口（broker）快照。

    数据来自 Futu 推送经 data_subservice 桥接的 quant:broker:{symbol} 频道，
    由 SubscriptionService 回灌进程内缓存。缓存未命中（TTL 过期 / 无订阅）时
    返回 cached=false，前端应据此判断是否降级或等待下次推送。

    Args:
        symbol: 标的代码（如 00700.HK / AAPL）
    """
    tick = subscription_service.get_broker(symbol)
    cached = tick is not None
    return {
        "symbol": symbol.upper(),
        "broker": tick,
        "cached": cached,
        "updated_at": tick.get("updated_at") if tick else None,
        "source": "quant:broker:channel+poly_cache" if cached else None,
    }


@router.get("/kline/{symbol}")
async def get_kline_realtime(symbol: str):
    """获取标的实时 K 线（kline）推送快照。

    数据来自 Futu 推送经 data_subservice 桥接的 quant:kline:{symbol} 频道，
    由 SubscriptionService 回灌进程内缓存。

    Args:
        symbol: 标的代码（如 00700.HK / AAPL）
    """
    kd = subscription_service.get_kline(symbol)
    cached = kd is not None
    return {
        "symbol": symbol.upper(),
        "kline": kd,
        "cached": cached,
        "updated_at": kd.get("updated_at") if kd else None,
        "source": "quant:kline:channel+poly_cache" if cached else None,
    }
