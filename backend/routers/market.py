import asyncio
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
from backend.services.datasource.business.option import option_data_service as _facade_option
from backend.services.datasource.router import data_source_router

# BE-ARCH-07p: 进程内 broker/kline 实时缓存（消费 quant:broker:* / quant:kline:* 回灌）
from backend.services.datasource.subscription import subscription_service
from backend.services.fund_flow.ticker import ticker_service
from backend.services.futu.utils import is_futu_unsupported
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

# ── PERF-01: /market/history 短 TTL 结果缓存 ─────────────────────────
# 前端行情图对同一 (ticker, ktype, num) 会高频请求（首载 + 轮询/增量核对）。
# OpenD 分页拉取网络抖动会直接拖慢前端，这里加一层 10s 短缓存打平抖动：
#   - 命中：直接返回缓存（cached=true），不穿透 OpenD
#   - miss：正常拉取并回填；下次 10s 内的重复请求直接命中
# 注意：TTL 仅 10s，不影响 K 线最终一致性；长历史对账由前端 30s 轮询兜底。
_HISTORY_CACHE_TTL_SEC = 10
_HISTORY_CACHE_PREFIX = "market:history:v1"


async def _get_history_cache(ticker: str, ktype: str, num: int):
    key = f"{_HISTORY_CACHE_PREFIX}:{ticker}:{ktype}:{num}"
    try:
        raw = await redis_client.get(key)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return payload
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[history-cache] 读取失败 {key}: {e}")
        return None


async def _put_history_cache(ticker: str, ktype: str, num: int, payload: dict) -> None:
    key = f"{_HISTORY_CACHE_PREFIX}:{ticker}:{ktype}:{num}"
    try:
        await redis_client.set(key, json.dumps(payload, ensure_ascii=False), ex=_HISTORY_CACHE_TTL_SEC)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[history-cache] 写入失败 {key}: {e}")


# PERF: /option-iv-summary 短 TTL 结果缓存（IV 指标变化慢，10min）
async def _put_iv_cache(key: str, payload: dict) -> None:
    try:
        await redis_client.set(key, json.dumps(payload, ensure_ascii=False), ex=600)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[iv-cache] 写入失败 {key}: {e}")


# PERF-02: 数仓优先读取 —— 历史 K 线不可变，优先从 L2 Parquet 极速读取。
# 命中则直接返回（避免穿透 OpenD），并异步触发 update_ticker 补齐最新 bar。
async def _try_read_kline_warehouse(ticker: str, ktype: str, num: int):
    """从 L2 Parquet 数仓按条数读取 K 线；命中返回 dict list，未命中返回 None。"""
    try:
        symbol = format_ticker(ticker)  # 统一为带市场前缀的 Futu 格式，与数仓 key 对齐
        df = await kline_warehouse.get_history(symbol, ktype=ktype, num=num)
        if df is None or df.empty:
            return None
        return df.tail(num).to_dict(orient="records")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[history-warehouse] 读取数仓失败 {ticker}/{ktype}: {e}")
        return None


# PERF-02: 后台异步落数仓。用 per-ticker 去重，避免并发请求触发重复 update_ticker
# 打爆 OpenD 频控（update_ticker 内部对增量已做智能跳过：last_date 最新时直接 return）。
_sync_scheduled: dict[tuple[str, str], bool] = {}


def _schedule_warehouse_sync(ticker: str, ktype: str) -> None:
    key = (ticker.upper(), ktype)
    if _sync_scheduled.get(key):
        return
    _sync_scheduled[key] = True

    async def _do():
        try:
            await kline_warehouse.update_ticker(format_ticker(ticker), ktype=ktype)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[history-warehouse] 后台同步失败 {ticker}/{ktype}: {e}")
        finally:
            _sync_scheduled[key] = False

    asyncio.create_task(_do())


def _flat_facade_payload(
    facade_res,
    fallback_msg: str,
    fallback_data=None,
):
    """BE-13 方案 B：把 facade Result 拍平为供中间件包信封的扁平 payload。

    当 facade 成功但 data 为空/非 dict（子服务返回空 payload 的常见情况）时，
    必须返回降级扁平 payload，而非 `**None` 抛 TypeError → 500。
    """
    data = facade_res.data
    if not isinstance(data, dict):
        return {
            "data": fallback_data if fallback_data is not None else {},
            "source": f"facade+{facade_res.source}",
            "degraded": True,
            "degraded_message": fallback_msg,
        }
    return {
        **data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
    }


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
                        # BE-ARCH-08c⑤: 回传子服务 → OpenD 真正订阅实时推送,
                        # 否则新标的只能等 broadcast_loop 约 10s 轮询"碰巧"触发订阅。
                        # best-effort, 不阻塞 WS ack; 子服务不可用由 router 内部熔断吸收。
                        for t in new_tickers:
                            if not is_futu_unsupported(t):
                                asyncio.create_task(data_source_router.fetch_futu("subscribe", ticker=t))
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
                    # BE-ARCH-08c⑤: 回传子服务 → OpenD 退订, 释放订阅额度槽位
                    for t in req_tickers:
                        if not is_futu_unsupported(t):
                            asyncio.create_task(data_source_router.fetch_futu("unsubscribe", ticker=t))
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
    """供前端面板感知底层 OpenD 核心连接状态。

    BE-ARCH-09 远程-only: 主服务不持有本地 OpenD SDK / 不直连 127.0.0.1:11111,
    仅经 DataSourceRouter 由主节点 data_subservice (DS_CAPABILITIES=futu) 持有 OpenD
    长连接。故此处改为探活 router 的 futu_master 节点 + 子服务 HEALTH 上报的真实
    OpenD 连接状态 (status==CONNECTED), 而非依赖已废弃的本地 legacy gateway 探测
    (该探测在主容器内必然 False, 导致前端 OpenD 标识永远红色)。
    """
    if not data_source_router._enabled:
        return {
            "status": "DISCONNECTED",
            "error": "数据源路由未启用 (DATA_SOURCE_ROUTER_ENABLED=false)",
            "reachable": False,
        }

    try:
        health_res = await data_source_router.fetch_futu("HEALTH")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Futu Status] 探活 futu_master 节点失败: {exc}")
        health_res = {"status": "error", "message": str(exc)}

    if isinstance(health_res, dict) and health_res.get("status") == "success":
        # 子服务 HEALTH 返回 {"available": status==CONNECTED, ...}
        opend_connected = bool(health_res.get("available"))
        return {
            "status": "CONNECTED" if opend_connected else "DISCONNECTED",
            "error": None if opend_connected else "OpenD 行情通道未连接 (子服务探活失败)",
            "reachable": True,
        }

    msg = health_res.get("message") if isinstance(health_res, dict) else str(health_res)
    return {
        "status": "DISCONNECTED",
        "error": f"Futu 远程节点不可用: {msg}",
        "reachable": False,
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


def _is_futu_ticker(ticker: str) -> bool:
    """判定是否为富途行情标的（facade/registry 不注册 futu，需走 DataSourceRouter 单独通道）。"""
    t = (ticker or "").upper().strip()
    return (
        any(t.startswith(p) for p in ("HK.", "US.", "SH.", "SZ.", "JP.", "SG.", "UK.", "LSE."))
        or t.endswith(".HK")
        or t.endswith(".US")
        or t.endswith(".SH")
        or t.endswith(".SZ")
    )


@router.get("/quote")
async def get_quote(ticker: str):
    """
    提供给前端的高频统一行情接口

    ✅ 已解耦数据源：基于 DataSourcePort Protocol + MarketDataService
    🛡️ 降级策略:
      - Futu (港美股/A股等经 DataSourceRouter.fetch_futu 单独通道)
      - AkShare (A 股兜底)
      - YFinance (加密货币/外汇兜底)

    Args:
        ticker: 标的代码

    Returns:
        dict: {"status": "success", "data": QuoteData, "source": str}

    Raises:
        HTTPException: 所有数据源均失败时抛出 400 错误
    """
    # BE-ARCH-06c: futu 标的经 DataSourceRouter.fetch_futu 直连远程节点
    # （facade/registry 不注册 futu，单独通道；与 websocket 订阅保持一致）
    if _is_futu_ticker(ticker):
        try:
            futu_res = await data_source_router.fetch_futu("QUOTE", ticker=ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Market API] Futu fetch_futu 异常: {exc}")
            raise HTTPException(status_code=500, detail=f"Futu 数据源调用异常: {exc}")
        if isinstance(futu_res, dict) and futu_res.get("status") == "success":
            futu_data = futu_res.get("data") or {}
            return {
                **(futu_data if isinstance(futu_data, dict) else {"data": futu_data}),
                "source": "futu",
                "degraded": False,
                "latency_ms": futu_res.get("latency_ms"),
                "cached": futu_res.get("cached", False),
            }
        err_msg = futu_res.get("message", "Futu 数据源失败") if isinstance(futu_res, dict) else str(futu_res)
        # 上游 Futu 节点不可用属服务端降级，返回 200 + 结构化错误而非 HTTP 400
        return {
            "status": "error",
            "code": "FUTU_SOURCE_UNAVAILABLE",
            "message": err_msg,
            "data": None,
            "source": "futu",
            "retryable": True,
        }

    # 非 futu 标的走通用 Facade（经 DataSourceRegistry 选源 + 融合 + Stale 检测）
    try:
        facade_res = await _facade_market.get_quote(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Market API] Facade get_quote 异常: {exc}")
        raise HTTPException(status_code=500, detail=f"数据源调用异常: {exc}")

    if not facade_res.is_success:
        # 数据源不可用属服务端降级，返回 200 + 结构化错误而非 HTTP 400
        err_msg = facade_res.error.message if facade_res.error else "所有数据源失败"
        return {
            "status": "error",
            "code": facade_res.error.code if facade_res.error else "DATA_SOURCE_UNAVAILABLE",
            "message": err_msg,
            "data": None,
            "source": facade_res.source,
            "retryable": facade_res.error.retryable if facade_res.error else True,
        }

    # BE-13 方案 B：直接返回扁平 payload，由 response_envelope_middleware 统一包成 {code,msg,data,ts}
    # 前端统一读 res.data（含业务字段 + source 元数据），不再二次解包 .data
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
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
        # 💡 优先从 Redis 缓存获取（yf_macro_cache 由 YF 采集 daemon 定期更新）
        yf_code = format_yf_ticker(ticker)
        # key 必须小写：采集侧 collectors/yfinance.py 用 ticker.lower() 写缓存
        cache_key = f"yf_macro_cache_{yf_code.lower()}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                last_price = 0.0
                change_pct = "0.0%"
                volume_str = "--"
                # 兼容两种缓存结构：HISTORY K线 list（采集侧现状）与旧 QUOTE dict。
                if isinstance(data, list) and data:
                    # HISTORY list：取最后一根 K线的 close 作为最新价
                    last_bar = data[-1]
                    last_price = float(last_bar.get("close") or last_bar.get("Close") or 0)
                    prev_bar = data[-2] if len(data) > 1 else None
                    prev_close = float(prev_bar.get("close") or prev_bar.get("Close") or 0) if prev_bar else 0.0
                    if prev_close:
                        change_pct = f"{((last_price - prev_close) / prev_close) * 100:.2f}%"
                    volume_str = str(last_bar.get("volume") or last_bar.get("Volume") or "--")
                elif isinstance(data, dict):
                    last_price = float(data.get("last_price") or data.get("close") or 0)
                    change_pct = str(data.get("change_pct", "0.0%"))
                    volume_str = str(data.get("volume_str", "--"))
                results[ticker] = {
                    "ticker": ticker,
                    "last_price": last_price,
                    "change_pct": change_pct,
                    "volume_str": volume_str,
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
    # PERF-01: 短 TTL 结果缓存 —— 打平 OpenD 网络抖动，避免高频请求反复穿透
    num = min(max(num, 1), 5000)
    cached = await _get_history_cache(ticker, ktype, num)
    if cached is not None:
        cached["cached"] = True
        return cached

    # PERF-02: 数仓优先读取 —— 历史 K 线不可变，从 L2 Parquet 极速返回，不穿透 OpenD
    wh_records = await _try_read_kline_warehouse(ticker, ktype, num)
    if wh_records:
        payload = {
            "data": wh_records,
            "source": "kline_warehouse",
            "degraded": False,
            "cached": True,
        }
        await _put_history_cache(ticker, ktype, num, payload)
        return payload

    # BE-ARCH-06c: Futu 标的 (港股/美股/A股等) 经 DataSourceRouter.fetch_futu 单独通道
    # （facade/registry 不注册 futu，单独通道；与 /quote 保持一致，避免 .HK 走 yfinance 报错）
    futu_failed = False
    if _is_futu_ticker(ticker):
        try:
            futu_res = await data_source_router.fetch_futu("HISTORY", ticker=ticker, ktype=ktype, num=num)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Market API] Futu HISTORY fetch_futu 异常: {exc}")
            futu_failed = True
        else:
            if isinstance(futu_res, dict) and futu_res.get("status") == "success":
                futu_data = futu_res.get("data") or {}
                payload = {
                    **(futu_data if isinstance(futu_data, dict) else {"data": futu_data}),
                    "source": "futu",
                    "degraded": False,
                    "latency_ms": futu_res.get("latency_ms"),
                    "cached": False,
                }
                await _put_history_cache(ticker, ktype, num, payload)
                # PERF-02: 后台异步落数仓，下次请求走 L2 Parquet
                _schedule_warehouse_sync(ticker, ktype)
                return payload
            # Futu 失败: 回退 facade (yfinance/akshare 兜底)
            logger.warning(
                f"[Market API] Futu HISTORY 失败, 回退 facade: {futu_res.get('message') if isinstance(futu_res, dict) else futu_res}"
            )
            futu_failed = True

    # BE-ARCH-06c: 统一走新 Facade
    facade_res = await _facade_market.get_history(ticker, ktype=ktype, num=num)
    if not facade_res.is_success or not facade_res.data:
        err_msg = facade_res.error.message if facade_res.error else "获取历史数据失败"
        # Futu 通道异常时给出更明确的 500 语义（而非 400）
        if futu_failed:
            raise HTTPException(status_code=500, detail=f"Futu 历史数据调用异常: {err_msg}")
        raise HTTPException(status_code=400, detail=err_msg)

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封。
    # HISTORY 的 data 是 K 线 list，不能 ** 展开，统一包入 data 键（前端读 res.data.data）。
    payload = {
        "data": facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
    }
    await _put_history_cache(ticker, ktype, num, payload)
    # PERF-02: 后台异步落数仓，下次请求走 L2 Parquet
    _schedule_warehouse_sync(ticker, ktype)
    return payload


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
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封
    # degraded 信号：优先透传子服务返回的 degraded/degraded_message（如期权链快照补充失败），
    # 而非仅依赖 ResultStatus.DEGRADED（后者只在 _detect_stale 触发，会冲掉子服务的降级信号）。
    _sub_degraded = isinstance(facade_res.data, dict) and facade_res.data.get("degraded")
    _sub_msg = facade_res.data.get("degraded_message") if isinstance(facade_res.data, dict) else None
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": _sub_degraded or facade_res.status == ResultStatus.DEGRADED,
        "degraded_message": _sub_msg
        or (facade_res.error.message if (facade_res.is_degraded and facade_res.error) else None),
    }


@router.get("/option-iv-summary")
async def get_option_iv_summary(ticker: str):
    """
    F3：期权 IV 指标聚合（设计稿 IV 指标条：ATM IV / IV 分位 / 30日已实现 / Skew）

    Args:
        ticker: 正股/ETF/指数代码（非期权 code）

    Returns:
        dict: {"status": "success", "data": OptionIvSummary}
    """
    # PERF: IV 指标变化慢，加 10min 结果缓存，避免每次请求重拉期权链+日K 外部源
    iv_key = f"market:iv-summary:v1:{ticker.upper()}"
    try:
        cached_iv = await redis_client.get(iv_key)
        if cached_iv is not None:
            return {**json.loads(cached_iv), "cached": True}
    except Exception:  # noqa: BLE001
        pass

    facade_res = await _facade_market.get_option_iv_summary(ticker)
    if isinstance(facade_res, dict):
        # get_option_iv_summary 返回的是扁平 dict（非 Result），直接包信封
        payload = {
            "data": facade_res,
            "source": "facade+market",
            "degraded": not facade_res.get("available", False),
        }
        await _put_iv_cache(iv_key, payload)
        return payload
    if hasattr(facade_res, "is_error") and facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "期权 IV 指标数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    payload = {
        "data": facade_res.data if hasattr(facade_res, "data") else facade_res,
        "source": f"facade+{getattr(facade_res, 'source', 'market')}",
        "degraded": getattr(facade_res, "status", None) == ResultStatus.DEGRADED,
    }
    await _put_iv_cache(iv_key, payload)
    return payload


@router.get("/option-strategy-lab")
async def get_option_strategy_lab(
    ticker: str,
    strategy_type: str = "STRANGLE",
    spread: int = 5,
    underlying_price: float | None = None,
):
    """
    G4：期权损益实验室（Futu OPTION_STRATEGY → 纯代数损益曲线 + 盈亏平衡点 + 真实 Greeks）

    Args:
        ticker: 正股/ETF/指数代码（非期权 code）
        strategy_type: 策略类型（STRANGLE/CALL/PUT/...，默认 STRANGLE）
        spread: 价差档位，默认 5
        underlying_price: 情景网格中心价（可选，默认取行权价中值）
    """
    # BE-ARCH-06c: 经 Facade 统一选源（富途组合策略最准）
    facade_res = await _facade_option.get_option_strategy_lab(
        ticker, strategy_type=strategy_type, spread=spread, underlying_price=underlying_price
    )
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "期权损益实验室数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封；degraded 信号透传为布尔字段
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
        "degraded_message": facade_res.error.message if (facade_res.is_degraded and facade_res.error) else None,
    }


@router.get("/option-volatility")
async def get_option_volatility(ticker: str):
    """
    F3：期权波动率（Futu OPTION_VOLATILITY → 单合约隐含波动率/历史波动率/Greeks）

    Args:
        ticker: 期权合约代码（OCC 格式，如 US.AAPL260320C200000，非正股）
    """
    facade_res = await _facade_option.get_option_volatility(ticker)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "期权波动率数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封；degraded 信号透传为布尔字段
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
        "degraded_message": facade_res.error.message if (facade_res.is_degraded and facade_res.error) else None,
    }


# ── P0.5 期权全维数据端点（IV/HV/Put-Call/0DTE/财报/卖方/行权概率）─────────


@router.get("/option-underlying-his-volatility")
async def get_option_underlying_his_volatility(ticker: str, begin_time: str | None = None, end_time: str | None = None):
    """P0.5.2 标的已实现波动率 HV（时间序列，正股/ETF 代码）。"""
    facade_res = await _facade_option.get_option_underlying_his_volatility(
        ticker, begin_time=begin_time, end_time=end_time
    )
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "HV 数据不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-underlying-overview")
async def get_option_underlying_overview(ticker: str):
    """P0.5.2 标的期权总览（IV/IV_RANK/HV 多周期 + Put/Call 量仓）。"""
    facade_res = await _facade_option.get_option_underlying_overview(ticker)
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "标的总览不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-underlying-put-call")
async def get_option_underlying_put_call(ticker: str):
    """B.1 个股级多空情绪（Put/Call 量比 + 归一化信号）。

    基于 Futu overview 的 call/put volume 派生（OpenD 零幻觉；yfinance 限流不可用）。
    B.2 归一化：P/C > 1.2 偏空 / < 0.8 偏多，映射 -1(极空)~+1(极多)。
    """
    facade_res = await _facade_option.get_option_underlying_put_call(ticker)
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "个股 P/C 不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-market-statistic")
async def get_option_market_statistic(
    option_market: str = "US_SECURITY",
    data_type: str = "VOLUME",
    begin_time: str | None = None,
    end_time: str | None = None,
):
    """P0.5.3 期权市场 Put/Call 比（市场级情绪指标，原始序列）。"""
    facade_res = await _facade_option.get_option_market_statistic(
        option_market=option_market, data_type=data_type, begin_time=begin_time, end_time=end_time
    )
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "市场统计不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-put-call-panel")
async def get_option_put_call_panel(option_market: str = "US_SECURITY", data_type: str = "VOLUME"):
    """P0.5.3 期权 Put/Call 情绪面板（latest/avg_5d/signal 产品级聚合）。"""
    facade_res = await _facade_option.get_option_put_call_panel(option_market=option_market, data_type=data_type)
    if facade_res.is_error:
        raise HTTPException(
            status_code=400, detail=facade_res.error.message if facade_res.error else "Put/Call 面板不可用"
        )
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-zero-dte-screener")
async def get_option_zero_dte_screener(
    market: str = "US_SECURITY",
    sort_type: str | None = None,
    is_asc: bool | None = None,
    count: int = 20,
    page: int = 1,
):
    """P0.5.4 0DTE 末日期权筛选器（市场级列表，item 含 owner+chain_info）。"""
    facade_res = await _facade_option.get_option_zero_dte_screener(
        market=market, sort_type=sort_type, is_asc=is_asc, count=count, page=page
    )
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "0DTE 筛选不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-zero-dte-contract")
async def get_option_zero_dte_contract(
    owner: str,
    strike_date_timestamp: int | None = None,
    sort_type: str | None = None,
    is_asc: bool | None = None,
):
    """P0.5.4 0DTE 合约明细（chain_info 由前端从 screener item 传入）。

    注意：chain_info 为嵌套对象，走 body 或 query 编码均可；此处默认从 query 收 owner+timestamp，
    chain_info 完整入参建议用 POST 场景（见 options.py 约定）。演示 owner 级查询。
    """
    facade_res = await _facade_option.get_option_zero_dte_contract(
        owner, None, strike_date_timestamp=strike_date_timestamp, sort_type=sort_type, is_asc=is_asc
    )
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "0DTE 合约不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-earnings-screener")
async def get_option_earnings_screener(
    market: str = "US_SECURITY",
    sort_type: str | None = None,
    is_asc: bool | None = None,
    count: int = 20,
    page: int = 1,
):
    """P0.5.5 财报期权筛选器（财报公布标的期权数据）。"""
    facade_res = await _facade_option.get_option_earnings_screener(
        market=market, sort_type=sort_type, is_asc=is_asc, count=count, page=page
    )
    if facade_res.is_error:
        raise HTTPException(
            status_code=400, detail=facade_res.error.message if facade_res.error else "财报期权筛选不可用"
        )
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-seller-screener")
async def get_option_seller_screener(
    market: str = "US_SECURITY",
    seller_type: str = "COVERED_CALL",
    sort_type: str | None = None,
    is_asc: bool | None = None,
):
    """P0.5.6 卖方策略筛选器（备兑看涨/现金担保卖沽）。"""
    facade_res = await _facade_option.get_option_seller_screener(
        market=market, seller_type=seller_type, sort_type=sort_type, is_asc=is_asc
    )
    if facade_res.is_error:
        raise HTTPException(
            status_code=400, detail=facade_res.error.message if facade_res.error else "卖方策略筛选不可用"
        )
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


@router.get("/option-exercise-probability")
async def get_option_exercise_probability(ticker: str):
    """P0.5.7 行权概率（入参须为期权合约代码）。"""
    facade_res = await _facade_option.get_option_exercise_probability(ticker)
    if facade_res.is_error:
        raise HTTPException(status_code=400, detail=facade_res.error.message if facade_res.error else "行权概率不可用")
    return {**facade_res.data, "source": f"facade+{facade_res.source}"}


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
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
    }


@router.get("/capital-distribution/{ticker}")
async def get_capital_distribution(ticker: str):
    """
    G3：主力筹码分层 + 背离信号

    Args:
        ticker: 标的代码

    Returns:
        dict: {"status": "success", "data": CapitalDistributionData}
    """
    # BE-ARCH-06c: 经 Facade 统一选源（富途 9 档分层最准，与资金流同源）
    facade_res = await _facade_market.get_capital_distribution(ticker)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "主力筹码分布数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（前端 capital-distribution-panel 读 res.data）
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
    }


@router.get("/top-brokers/{ticker}")
async def get_top_brokers(ticker: str):
    """
    F5：十大买卖经纪商（经纪版面，盘口 tab）。

    HK: 实时经纪商净买/净卖明细；US: 同一接口 days_before=0 走实时，
    无 broker_queue 但有十大净买卖数据，作兜底（符合 US 用十大经纪商决策）。
    """
    # BE-ARCH-06c: 经 DataSourceRouter.fetch_futu 单独通道（facade/registry 不注册 futu）
    try:
        futu_res = await data_source_router.fetch_futu("TOP_BROKERS", ticker=ticker, days_before=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Market API] Futu TOP_BROKERS 异常: {exc}")
        raise HTTPException(status_code=500, detail=f"Futu 经纪商数据调用异常: {exc}")
    if isinstance(futu_res, dict) and futu_res.get("status") == "success":
        futu_data = futu_res.get("data") or {}
        return {
            **(futu_data if isinstance(futu_data, dict) else {"data": futu_data}),
            "source": "futu",
            "degraded": False,
            "latency_ms": futu_res.get("latency_ms"),
            "cached": futu_res.get("cached", False),
        }
    err_msg = futu_res.get("message", "Futu 经纪商数据失败") if isinstance(futu_res, dict) else str(futu_res)
    raise HTTPException(status_code=400, detail=err_msg)


@router.get("/capital-flow/{ticker}")
async def get_capital_flow(ticker: str, period_type: str = "INTRADAY"):
    """
    F6：个股资金流向时间序列（资金流向曲线，微观 tab）。

    period_type: INTRADAY(当日分时) / 历史周期。返回 data_time_str / capital_in_flow / capital_out_flow。
    """
    # BE-ARCH-06c: 经 DataSourceRouter.fetch_futu 单独通道
    try:
        futu_res = await data_source_router.fetch_futu("CAPITAL_FLOW", ticker=ticker, period_type=period_type)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Market API] Futu CAPITAL_FLOW 异常: {exc}")
        raise HTTPException(status_code=500, detail=f"Futu 资金流向数据调用异常: {exc}")
    if isinstance(futu_res, dict) and futu_res.get("status") == "success":
        futu_data = futu_res.get("data") or {}
        return {
            **(futu_data if isinstance(futu_data, dict) else {"data": futu_data}),
            "source": "futu",
            "degraded": False,
            "latency_ms": futu_res.get("latency_ms"),
            "cached": futu_res.get("cached", False),
        }
    err_msg = futu_res.get("message", "Futu 资金流向数据失败") if isinstance(futu_res, dict) else str(futu_res)
    raise HTTPException(status_code=400, detail=err_msg)


@router.get("/heat-map/{market}")
async def get_heat_map(market: str = "HK"):
    """
    G6：板块热力图（产品级聚合，供 ECharts treemap 渲染）

    Args:
        market: 市场代码（HK/US/SG，默认 HK）

    Returns:
        dict: {"status": "success", "data": HeatMapData}
    """
    # BE-ARCH-06c: 经 Facade 统一选源（富途热力图最准，与资金流同源）
    facade_res = await _facade_market.get_heat_map(market)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "板块热力图数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（data 非 dict 时降级而非 500）
    return _flat_facade_payload(facade_res, f"板块热力图数据不可用（{market}）")


@router.get("/order-book")
async def get_order_book(ticker: str):
    """
    实时 L2 盘口深度（Futu ORDER_BOOK）。

    Args:
        ticker: 标的代码（如 HK.00700 / US.AAPL）

    Returns:
        dict: {"status": "success", "data": {ticker, bids, asks, spread, imbalance, ...}}
    """
    facade_res = await _facade_market.get_order_book(ticker)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "盘口数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（data 非 dict 时降级而非 500）
    return _flat_facade_payload(facade_res, f"盘口数据不可用（{ticker}）")


@router.get("/snapshot")
async def get_market_snapshot(tickers: str):
    """
    批量实时快照（Futu SNAPSHOT，最多 400 只/批）。

    Args:
        tickers: 逗号分隔的标的列表（如 HK.00700,US.AAPL,HK.09988）

    Returns:
        dict: {"status": "success", "data": {data:[...], panel:{count, avg_change, ups, downs, flats}}}
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers 不能为空")
    facade_res = await _facade_market.get_market_snapshot(ticker_list)
    if facade_res.is_error:
        # 上游数据源不可用属于服务端降级(非客户端请求错误)，返回 200 + 结构化错误，
        # 让前端以「该项数据暂不可用」优雅展示，而非把 HTTP 400 当成接口报错抛给用户。
        err_msg = facade_res.error.message if facade_res.error else "快照数据不可用"
        return {
            "status": "error",
            "code": facade_res.error.code if facade_res.error else "DATA_SOURCE_UNAVAILABLE",
            "message": err_msg,
            "data": None,
            "source": facade_res.source,
            "retryable": facade_res.error.retryable if facade_res.error else True,
        }
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（data 非 dict 时降级而非 500）
    return _flat_facade_payload(facade_res, "快照数据不可用")


@router.get("/stock-basicinfo")
async def get_stock_basicinfo(market: str, sec_type: str = "STOCK"):
    """
    全市场股票/ETF/指数基本信息（Futu STOCK_BASICINFO）。

    Args:
        market: 市场代码（HK/US/SG）
        sec_type: 证券类型（STOCK/ETF/IDX/WARRANT，默认 STOCK）

    Returns:
        dict: {"status": "success", "data": {data:[...], panel:{count, market, sec_type}}}
    """
    facade_res = await _facade_market.get_stock_basicinfo(market, sec_type)
    if facade_res.is_error:
        err_msg = facade_res.error.message if facade_res.error else "基本信息数据不可用"
        raise HTTPException(status_code=400, detail=err_msg)
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（data 非 dict 时降级而非 500）
    return _flat_facade_payload(facade_res, f"基本信息数据不可用（{market}）")


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
        # BE-13 方案 B：扁平 payload 交由中间件统一包信封
        return {
            "data": [],
            "source": "not_implemented",
            "degraded": True,
            "degraded_message": f"[{ticker}] 窝轮/牛熊证链数据暂不支持（数据源未实现 warrant_chain 能力）",
        }

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封
    return {
        **facade_res.data,
        "source": f"facade+{facade_res.source}",
        "degraded": facade_res.status == ResultStatus.DEGRADED,
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

    # BE-ARCH-06c: Futu 标的 (港股/美股/A股等) 经 fetch_futu('HISTORY') 单独通道
    # (facade/registry 不注册 futu)。与 /history、/quote 保持一致，避免 .HK 走 yfinance 报错。
    klines = None
    source = None
    if _is_futu_ticker(ticker):
        try:
            futu_res = await data_source_router.fetch_futu("HISTORY", ticker=ticker, ktype="K_DAY", num=lookback_days)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Tech Indicators] Futu HISTORY 异常: {exc}")
            futu_res = {"status": "error", "message": str(exc)}
        if isinstance(futu_res, dict) and futu_res.get("status") == "success" and futu_res.get("data"):
            klines = futu_res["data"]
            source = "futu"
        else:
            logger.warning(
                f"[Tech Indicators] Futu HISTORY 失败, 回退 facade: {futu_res.get('message') if isinstance(futu_res, dict) else futu_res}"
            )

    # Futu 未命中时, 经 Facade 统一选源获取历史 K 线
    if klines is None:
        yf_ticker = format_yf_ticker(ticker)
        facade_res = await data_service.get_history(yf_ticker, num=lookback_days)
        if not facade_res.is_success or not facade_res.data:
            err_msg = facade_res.error.message if facade_res.error else "获取历史数据失败"
            raise HTTPException(
                status_code=400, detail=f"Failed to fetch historical data for technical indicators: {err_msg}"
            )
        klines = facade_res.data
        source = f"facade+{facade_res.source}"

    # ✅ 集成生产级技术指标计算引擎 (TechnicalIndicatorsPro)
    from backend.utils.technical_indicators_pro import calculate_technical_indicators

    # 防御：若上游返回仍是子服务信封 (dict 而非 list)，尝试解包一层
    if isinstance(klines, dict):
        if "data" in klines and isinstance(klines["data"], list):
            klines = klines["data"]
        else:
            raise HTTPException(
                status_code=400,
                detail=f"历史 K 线返回格式异常 (预期 list，实际 {type(klines).__name__})，无法计算技术指标",
            )

    indicators = calculate_technical_indicators(klines)

    # BE-13 方案 B：扁平 payload 交由中间件统一包信封（前端无 HTTP 调用方，保持后端一致性）
    return {
        "klines": klines[:10],  # 返回最近 10 根 K 线
        "indicators": indicators,  # 完整的计算结果
        "source": f"{source}+custom_tech_indicators",
        "degraded": False,
    }


@router.get("/search")
async def search_tickers(q: str):
    """
    统一模糊匹配底层接口：股票代码/名称模糊搜索（三级降级）
      1. 本地词库（Futu get_security_list/STOCK_BASICINFO 同步，pg_trgm 相似度，毫秒级）
      2. Futu get_search_quote（实时联想，补新上市/中文名盲区，自带 10min L1 缓存）
      3. YFinance（最后兜底）

    前端 OmniSearch 与投研会 ticker 解析均复用此接口。

    Args:
        q: 搜索关键词

    Returns:
        dict: {"status": "success", "data": [SearchResult]}
    """
    # 1. 本地词库极速检索
    res = await ticker_service.search_tickers(q)

    # 2. 本地 miss → Futu 实时联想（补名称→代码盲区，支持中文名）
    #    注意: search_quote 在 DataServiceFacade(data_service) 上，不在 MarketDataService(_facade_market)
    #    关键: Futu 远端节点(OpenD)可能波动/挂起，必须加超时保护，避免联想搜索卡死/不稳定。
    if res.get("status") == "success" and not res.get("data"):
        try:
            import asyncio

            futu_res = await asyncio.wait_for(
                data_service.search_quote(keyword=q, max_count=10),
                timeout=2.5,
            )
            if futu_res.is_success and futu_res.data:
                return {
                    "data": futu_res.data,
                    "source": f"futu_search_quote+{futu_res.source}",
                    "degraded": futu_res.status == ResultStatus.DEGRADED,
                }
        except asyncio.TimeoutError:
            print(f"⚠️ [Search] Futu get_search_quote 超时(2.5s)跳过, 降级本地结果: {q}")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ [Search] Futu get_search_quote 降级失败: {e}")

    # 3. Futu 也 miss → YFinance 兜底
    if res.get("status") == "success" and not res.get("data"):
        print(f"⚠️ [Search] 本地词库+富途均无 '{q}'，降级 YFinance...")
        facade_res = await data_service.get_quote(q, prefer_sources=["yfinance"])
        if facade_res.is_success:
            # BE-13 方案 B：扁平 payload（data 为 SearchResult 列表，包入 data 键）
            return {
                "data": facade_res.data,
                "source": f"facade+{facade_res.source}",
                "degraded": facade_res.status == ResultStatus.DEGRADED,
            }

    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    # BE-13 方案 B：扁平 payload 交由中间件统一包信封；data 为列表包入 data 键
    return {
        "data": res.get("data") or [],
        "source": res.get("source", "local_dict"),
        "degraded": res.get("status") == "degraded",
    }


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
