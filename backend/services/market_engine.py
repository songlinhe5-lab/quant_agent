import asyncio
import json
import logging
import os
import struct
import time
import zlib
from typing import Optional

import pandas as pd
import redis.asyncio as redis
from fastapi import WebSocket

# BE-06: 统一指标定义
from backend.core.metrics import (
    MARKET_QUOTE_LATENCY,
    MARKET_QUOTE_STALENESS,
    MARKET_QUOTE_TOTAL,
    WS_ACTIVE_CONNECTIONS,
    WS_MESSAGES_SENT,
    WS_SUBSCRIPTIONS,
)

# 引入编译好的 Protobuf 模块
from backend.core.proto.market_pb2 import Order, QuoteData  # type: ignore
from backend.core.redis_client import l1_cached_redis, redis_client
from backend.core.utils import safe_divide, safe_float

# 引入现有的 Tools (本地 futu_service 作为 ClusterManager 不可用时的兜底)
from backend.services.futu import futu_service
from backend.services.kline_warehouse import kline_warehouse
from backend.services.notification_service import notification_service
from backend.services.yfinance_service import yf_service, format_yf_ticker

logger = logging.getLogger(__name__)


async def update_quote_to_redis(ticker: str, quote_data: dict):
    """通用的写入 Redis 逻辑（Futu 和 Yahoo 都调这个，统一序列化为 Protobuf）"""
    _t0 = time.perf_counter()
    try:
        quote_msg = QuoteData(
            status="success",
            ticker=quote_data.get("ticker", ticker),
            last_price=float(quote_data.get("last_price", 0.0)),
            change_pct=str(quote_data.get("change_pct", "0.0%")),
            volume_str=str(quote_data.get("volume_str", "--")),
            source=str(quote_data.get("source", "unknown")),
        )
        for b in quote_data.get("bids", []):
            quote_msg.bids.append(Order(price=float(b.get("price", 0.0)), size=float(b.get("size", 0.0))))  # noqa: E501
        for a in quote_data.get("asks", []):
            quote_msg.asks.append(Order(price=float(a.get("price", 0.0)), size=float(a.get("size", 0.0))))  # noqa: E501

        payload_bytes = quote_msg.SerializeToString()
        await manager.raw_redis.hset("quant:quotes:latest", ticker, payload_bytes)
        await manager.raw_redis.publish("quant:quotes:stream", payload_bytes)

        # BE-06: 行情指标埋点
        source = quote_data.get("source", "unknown")
        MARKET_QUOTE_TOTAL.labels(source=source, symbol=ticker).inc()
        MARKET_QUOTE_LATENCY.labels(source=source, symbol=ticker).observe(time.perf_counter() - _t0)  # noqa: E501
        MARKET_QUOTE_STALENESS.labels(symbol=ticker).set(0)  # 刚写入，延迟为 0

        # 💡 新增：实时价格突破/跌破报警检测
        last_price = quote_msg.last_price
        change_pct_str = quote_msg.change_pct
        if last_price > 0:
            # 获取这只股票所有配置了报警规则的用户
            user_alerts = await redis_client.hgetall(f"quant:alerts:by_ticker:{ticker}")
            if user_alerts:
                for user_id_bytes, rules_str in user_alerts.items():
                    user_id = user_id_bytes.decode("utf-8") if isinstance(user_id_bytes, bytes) else user_id_bytes  # noqa: E501
                    rules = json.loads(rules_str)
                    upper = rules.get("upper")
                    lower = rules.get("lower")
                    pct_change = rules.get("pct_change")

                    triggered_msg = None
                    if upper is not None and last_price >= upper:
                        triggered_msg = f"🚀 [专属报警] {ticker} 最新价 {last_price} 已向上突破您设定的上限 {upper}！"  # noqa: E501
                    elif lower is not None and last_price <= lower:
                        triggered_msg = f"🩸 [专属报警] {ticker} 最新价 {last_price} 已向下跌破您设定的下限 {lower}！"  # noqa: E501
                    elif pct_change is not None:
                        try:
                            current_pct = float(change_pct_str.replace("%", "").replace("+", ""))  # noqa: E501
                            if abs(current_pct) >= pct_change:
                                direction = "暴涨" if current_pct > 0 else "暴跌"
                                triggered_msg = f"💥 [异动报警] {ticker} 发生 {direction}，当前涨跌幅 {change_pct_str}，已触及您设定的 ±{pct_change}% 阈值！"  # noqa: E501
                        except ValueError:
                            pass

                    if triggered_msg:
                        # 触发后仅删除该用户的一次回调报警，防止震荡轰炸
                        await redis_client.hdel(f"quant:alerts:by_ticker:{ticker}", user_id)  # noqa: E501
                        # 可进一步修改 notification_service 发送给指定 userid 绑定的飞书/钉钉  # noqa: E501
                        asyncio.create_task(notification_service.send_alert(f"[To User: {user_id}] " + triggered_msg))  # noqa: E501
    except Exception as e:
        print(f"⚠️ [Redis] 写入行情失败: {e}")


async def update_trade_to_redis(ticker: str, trade_data: bytes):
    """处理必须不丢包的事件类数据 (如逐笔成交、K线增量) 的双写逻辑"""
    try:
        stream_key = f"quant:trades:stream:{ticker}"
        # 1. 写入 Redis Stream，maxlen=5000 保证内存不会无限膨胀，保留最近 5000 条用于断线追补  # noqa: E501
        await manager.raw_redis.xadd(stream_key, {b"payload": trade_data}, maxlen=5000)
        # 2. 依然通过 PubSub 极速广播给当前在线的用户
        await manager.raw_redis.publish("quant:trades:stream", trade_data)
    except Exception as e:
        print(f"⚠️ [Redis] 写入逐笔成交流失败: {e}")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.subscriptions: dict[WebSocket, set[str]] = {}
        self.push_task = None
        self.loop = None
        self.tech_cache = {}
        self.flow_cache = {}  # 💡 资金流向与经纪商席位缓存池
        self.pubsub_task = None
        self.last_futu_update = {}
        self._futu_alert_sent = False
        self._outflow_alert_records = {}  # {ticker: timestamp} 防抖缓冲，防止连环报警
        self.last_account_summary = "总资产: 未知 | 浮动盈亏: 未知"
        self.last_acc_update = 0
        self._futu_active_subs = set()  # 💡 追踪当前富途占用的订阅槽位，用于自动释放

        # 💡 新增：单独的原始二进制 Redis 客户端，用于处理 Protobuf
        host = os.getenv("REDIS_HOST", "localhost")
        port = os.getenv("REDIS_PORT", "6379")
        password = os.getenv("REDIS_PASSWORD", "")
        redis_url = f"redis://:{password}@{host}:{port}"
        self.raw_redis = redis.from_url(redis_url, protocol=2)

    async def start_background_tasks(self):
        """启动 Redis 总线监听与底层兜底轮询守护协程"""
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        if self.push_task is None or self.push_task.done():
            self.push_task = asyncio.create_task(self.broadcast_loop())
        if self.pubsub_task is None or self.pubsub_task.done():
            self.pubsub_task = asyncio.create_task(self.redis_pubsub_listener())

        # 💡 防御：kline_warehouse daemon 只需启动一次，防止 WebSocket 重连导致重复创建
        if not getattr(self, "_kline_daemon_started", False):
            asyncio.create_task(kline_warehouse.daemon_sync_task())
            self._kline_daemon_started = True

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        WS_ACTIVE_CONNECTIONS.inc()  # 💡 监控：连接数 +1

        await self.start_background_tasks()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            WS_ACTIVE_CONNECTIONS.dec()  # 💡 监控：连接数 -1
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    def subscribe(self, websocket: WebSocket, tickers: list[str], last_ids: Optional[dict] = None):  # noqa: E501
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(tickers)
            WS_SUBSCRIPTIONS.set(sum(len(s) for s in self.subscriptions.values()))

        # 异步追补断层数据或拉取最新快照
        asyncio.create_task(self._catch_up_or_snapshot(websocket, tickers, last_ids or {}))  # noqa: E501

    async def _catch_up_or_snapshot(self, websocket: WebSocket, tickers: list[str], last_ids: dict):  # noqa: E501
        try:
            for t in tickers:
                last_id = last_ids.get(t)
                if last_id:
                    # 💡 核心操作：通过 XRANGE 获取 (last_id, +无穷大] 区间错过的所有包
                    missed_messages = await self.raw_redis.xrange(
                        f"quant:trades:stream:{t}", min=f"({last_id}", max="+"
                    )  # noqa: E501
                    if missed_messages:
                        # 💡 增加类型约束和严谨的 isinstance 防御，消除 Pylance 类型报错
                        payloads: list[bytes] = []
                        for _, fields in missed_messages:
                            if isinstance(fields, dict):
                                val = fields.get(b"payload")
                                if isinstance(val, bytes):
                                    payloads.append(val)

                        if not payloads or websocket not in self.active_connections:
                            continue

                        if len(payloads) > 100:
                            # 💡 高频优化：超过 100 条消息，组合成单一的二进制 Batch 帧一次性发送  # noqa: E501
                            # 格式: [0x01(表示zlib压缩模式)] + zlib_compressed([4字节包数量] + 循环([4字节单包长度] + [单包二进制数据]))  # noqa: E501
                            raw_buffer = bytearray()
                            raw_buffer.extend(
                                struct.pack("<I", len(payloads))
                            )  # Little-endian Unsigned Int  # noqa: E501
                            for p in payloads:
                                raw_buffer.extend(struct.pack("<I", len(p)))
                                raw_buffer.extend(p)
                            compressed_data = zlib.compress(raw_buffer)
                            final_buffer = bytearray([0x01]) + compressed_data
                            await websocket.send_bytes(bytes(final_buffer))
                        else:
                            for p in payloads:
                                await websocket.send_bytes(p)
                else:
                    cached_bytes = await self.raw_redis.hget("quant:quotes:latest", t)
                    if isinstance(cached_bytes, bytes) and websocket in self.active_connections:  # noqa: E501
                        await websocket.send_bytes(cached_bytes)
        except Exception as e:
            print(f"⚠️ [Redis] 追补或发送缓存快照失败: {e}")

    def unsubscribe(self, websocket: WebSocket, tickers: list[str]):
        if websocket in self.subscriptions:
            for t in tickers:
                self.subscriptions[websocket].discard(t)
            WS_SUBSCRIPTIONS.set(sum(len(s) for s in self.subscriptions.values()))

    def get_all_subscribed_tickers(self) -> set[str]:
        # 基础宏观数据，确保后台始终将其拉取至 Redis，供 LLM 或前端秒开使用
        # 💡 将宏观指数替换为富途格式 (如 US.VIX, US.SPX) 以优先利用富途快速获取，并保留比特币与日元汇率  # noqa: E501
        # 💡 加入 6 大核心资本板块代理 ETF，确保后台守护进程高频拉取其资金流，解耦耗时的外部 API 轮询  # noqa: E501
        all_tickers = {
            "GC=F",
            "CL=F",
            "^TNX",
            "ES=F",
            "US.VIX",
            "US.SPX",
            "US.IXIC",
            "^FVX",
            "DX-Y.NYB",
            "JPY=X",
            "BTC-USD",
            "US.SPY",
            "US.QQQ",
            "US.SOXX",
            "US.TLT",
            "US.KWEB",
            "SH.510300",
        }  # noqa: E501
        for tickers in self.subscriptions.values():
            all_tickers.update(tickers)
        return all_tickers

    async def redis_pubsub_listener(self) -> None:
        """[Consumer 职责]：持续监听 Redis 的 Pub/Sub 并定向推送给本机连接的前端客户端"""  # noqa: E501
        pubsub = self.raw_redis.pubsub()
        try:
            await pubsub.subscribe("quant:quotes:stream")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        payload_bytes = message["data"]
                        if not isinstance(payload_bytes, bytes):
                            continue

                        # 解析 protobuf 以获取 ticker 进行过滤
                        quote_msg = QuoteData()
                        quote_msg.ParseFromString(payload_bytes)
                        ticker = quote_msg.ticker

                        # 仅将数据派发给本节点上关注了该 ticker 的活跃 WebSocket 连接
                        for ws, ws_tickers in list(self.subscriptions.items()):
                            if ticker in ws_tickers:
                                try:
                                    await ws.send_bytes(payload_bytes)
                                    WS_MESSAGES_SENT.labels(type="quote").inc()
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except asyncio.CancelledError:
            # 💡 接收到网关关闭的 Cancelled 信号，安全退出并归还连接
            pass
        except Exception as e:
            print(f"⚠️ [Redis] PubSub 监听异常: {e}")
        finally:
            await pubsub.close()

    def _get_yf_fast_info(self, ticker: str):
        import yfinance as yf

        # 💡 统一走 format_yf_ticker 通用转换（不再手写 HK/US 指数映射，避免重复）
        yf_ticker = format_yf_ticker(ticker)

        info = yf.Ticker(yf_ticker).fast_info

        last_price = safe_float(info.last_price)
        prev_close = safe_float(info.previous_close)
        change_pct = safe_divide(last_price - prev_close, prev_close) * 100

        return {
            "status": "success",
            "ticker": ticker,
            "requested_ticker": ticker,
            "last_price": last_price,
            "change_pct": f"{change_pct:+.2f}%",
            "volume": getattr(info, "last_volume", 0),
            "source": "yfinance",
            "data_timestamp": "Realtime(Delayed)",
        }

    async def _fetch_fallback_quote(self, ticker: str):
        """通过异步线程隔离调用雅虎财经，作为富途熔断时的降级通道"""
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._get_yf_fast_info, ticker), timeout=4.0)
        except Exception as e:
            print(f"[YFinance Fallback Error] {ticker}: {e}")
            return {"status": "error"}

    async def broadcast_loop(self) -> None:
        """背景任务持续拉取技术指标缓存与 YFinance 轮询兜底 (即使没有前端连接也保持更新 Redis)"""  # noqa: E501
        while True:
            try:
                all_tickers = list(self.get_all_subscribed_tickers())
                if all_tickers:
                    # 💡 动态读取全局 YFinance 开关状态
                    yf_enabled_val = await l1_cached_redis.get("quant:settings:yfinance_enabled")  # noqa: E501
                    is_yf_enabled = yf_enabled_val != "0"

                    # 💡 Futu 断连防御：检测连接状态，断连时跳过所有 Futu 调用防止 CPU 空转
                    futu_connected = futu_service.status == "CONNECTED"

                    # 💡 [额度释放 GC 机制]：对比当前真实需要的标的与已订阅的标的，自动剔除无人观看的废弃订阅  # noqa: E501
                    current_futu_needs = {t for t in all_tickers if not futu_service.is_futu_unsupported(t)}  # noqa: E501
                    stale_subs = self._futu_active_subs - current_futu_needs

                    if stale_subs:
                        print(
                            f"🧹 [Futu GC] 检测到 {len(stale_subs)} 只标的已无活跃监听，正在向富途发起退订以释放额度..."
                        )  # noqa: E501
                        for stale_t in stale_subs:
                            try:
                                # 调用 futu_service 的退订方法释放底层占用
                                if hasattr(futu_service, "unsubscribe_quote"):
                                    await futu_service.unsubscribe_quote(stale_t)
                                # 从系统的已订阅记录中移除
                                self._futu_active_subs.discard(stale_t)
                            except Exception as e:
                                print(f"⚠️ [Futu GC] 退订 {stale_t} 失败: {e}")

                    # 更新当前活跃的富途订阅池
                    self._futu_active_subs.update(current_futu_needs)

                    # 💡 内存安全防御：清理已不在监控列表中的缓存条目
                    stale_tech = [t for t in self.tech_cache if t not in all_tickers]
                    for t in stale_tech:
                        del self.tech_cache[t]
                    stale_flow = [t for t in self.flow_cache if t not in all_tickers]
                    for t in stale_flow:
                        del self.flow_cache[t]

                    # 💡 内存安全防御：清理 Futu 缓存过期条目
                    if hasattr(futu_service, "cache_mgr"):
                        futu_service.cache_mgr.evict_stale_cache()

                    # 💡 优化 1: 定时刷新技术面指标缓存 (仅在 Futu 连接时执行)
                    # 技术指标(日线级)无需每 3 秒全量并发刷新。设定为 1 小时更新一次，或发现新标的时触发  # noqa: E501
                    current_time = time.time()
                    need_global_tech_update = current_time - getattr(self, "last_tech_update", 0) > 3600  # noqa: E501
                    tickers_to_update = [t for t in all_tickers if t not in self.tech_cache or need_global_tech_update]  # noqa: E501

                    if tickers_to_update and futu_connected:
                        for t in tickers_to_update:
                            try:
                                # 优先尝试利用 Futu 获取 120 日历史，完全免除外部网络请求  # noqa: E501
                                futu_res = await futu_service.get_history(t, ktype="K_DAY", num=120)  # noqa: E501
                                if futu_res.get("status") == "success" and futu_res.get("data"):  # noqa: E501
                                    df = pd.DataFrame(futu_res["data"])
                                    if len(df) >= 30:
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
                                        res = await yf_service.get_tech_indicators(
                                            ticker=t, lookback_days=6, pre_fetched_df=df
                                        )  # noqa: E501
                                        if res.get("status") == "success":
                                            self.tech_cache[t] = res.get("data", {}).get("trend", [])  # noqa: E501
                                            continue

                                # 如果 Futu 失败（加密货币/外汇等），且开启了 YF 兜底，则串行请求 YF  # noqa: E501
                                if is_yf_enabled:
                                    res = await yf_service.get_tech_indicators(ticker=t, lookback_days=6)  # noqa: E501
                                    if res.get("status") == "success":
                                        self.tech_cache[t] = res.get("data", {}).get("trend", [])  # noqa: E501
                            except Exception as e:
                                print(f"⚠️ [Tech Cache] 更新 {t} 指标异常: {e}")

                            # 🚨 核心防封控：必须错峰串行！杜绝高并发导致触发雅虎 429 封IP  # noqa: E501
                            await asyncio.sleep(1.0)

                        if need_global_tech_update:
                            self.last_tech_update = current_time

                    # 💡 定时拉取资金流与席位 (仅在 Futu 连接时执行，断连时跳过防止 CPU 空转)  # noqa: E501
                    if futu_connected:
                        flow_tasks = [futu_service.get_fund_flow(t) for t in all_tickers]  # noqa: E501
                        flow_results = await asyncio.gather(*flow_tasks, return_exceptions=True)  # noqa: E501

                        for ticker, f_res in zip(all_tickers, flow_results):
                            if isinstance(f_res, dict) and f_res.get("status") == "success":
                                self.flow_cache[ticker] = f_res

                    yf_candidates = []
                    futu_check_tickers = []
                    current_time = time.time()
                    for t in all_tickers:
                        if futu_service.is_futu_unsupported(t):
                            yf_candidates.append(t)
                        elif current_time - self.last_futu_update.get(t, 0) > 10:
                            futu_check_tickers.append(t)

                        # 🚨 实时大盘资金流出预警风控
                        # 监控 SPY(标普500), QQQ(纳指100), HK.800000(恒指)
                        monitor_targets = ["US.SPY", "US.QQQ", "HK.800000"]
                        if t in monitor_targets:
                            flow_data = self.flow_cache.get(t) or {}
                            if flow_data and isinstance(flow_data, dict):
                                fund_data = flow_data.get("data") or flow_data
                                if not isinstance(fund_data, dict):
                                    fund_data = {}
                                net_inflow = fund_data.get("main_fund_net_inflow") or 0
                                OUTFLOW_THRESHOLD = -500_000_000  # 阈值：主力净流出超过 5 亿  # noqa: E501
                                if net_inflow < OUTFLOW_THRESHOLD:
                                    # 💡 升级为分布式防抖锁，防止集群多台服务器同时发出报警轰炸  # noqa: E501
                                    lock_key = f"quant:lock:outflow_alert:{t}:{int(current_time / 3600)}"  # noqa: E501
                                    if await redis_client.set(lock_key, "1", nx=True, ex=3600):  # noqa: E501
                                        net_inflow_str = fund_data.get("main_fund_net_inflow_str", str(net_inflow))
                                        alert_msg = (
                                            f"🚨 [宏观风控预警] 宽基指数主力资金疯狂出逃！\n\n"  # noqa: E501
                                            f"标的: {t}\n今日主力净流出: {net_inflow_str}\n\n"  # noqa: E501
                                            f"请警惕系统性流动性抽离风险，并考虑收紧多头敞口！"
                                        )  # noqa: E501
                                        asyncio.create_task(notification_service.send_alert(alert_msg))

                    # 💡 每 10 秒异步拉取一次账户真实资产快照 (仅在 Futu 连接时执行)
                    if futu_connected and current_time - getattr(self, "last_acc_update", 0) > 10:
                        self.last_acc_update = current_time
                        try:
                            acc_res = await futu_service.get_account_info()
                            if acc_res.get("status") == "success":
                                total_assets = acc_res.get("total_assets", 0)
                                positions = acc_res.get("positions", [])
                                total_pnl = sum(p.get("pl_val", 0) for p in positions)
                                self.last_account_summary = f"总资产: {total_assets:,.2f} | 浮动盈亏: {total_pnl:+,.2f}"  # noqa: E501
                        except Exception:
                            pass

                    # 1. 优先执行富途快照补漏 (仅在 Futu 连接时执行)
                    if futu_connected and futu_check_tickers:
                        batch_success = False
                        last_futu_error = None

                        for t in futu_check_tickers:
                            try:
                                res = await futu_service.get_quote(t)
                                if res.get("status") == "success":
                                    batch_success = True

                                    res["requested_ticker"] = t
                                    res["tech_trend"] = self.tech_cache.get(t, [])

                                    flow_data = self.flow_cache.get(t, {})
                                    if flow_data:
                                        # 💡 修复资金流数据可能为 None 导致的致命挂起
                                        fund_data = flow_data.get("data") or flow_data
                                        if isinstance(fund_data, dict):
                                            bq = fund_data.get("broker_queue") or {}
                                            if isinstance(bq, dict):
                                                if bq.get("bid_brokers_queue_str"):
                                                    res["bid_brokers_queue_str"] = bq.get("bid_brokers_queue_str")  # noqa: E501
                                                if bq.get("ask_brokers_queue_str"):
                                                    res["ask_brokers_queue_str"] = bq.get("ask_brokers_queue_str")  # noqa: E501
                                            if fund_data.get("main_fund_net_inflow_str"):  # noqa: E501
                                                res["main_fund_net_inflow_str"] = fund_data.get(
                                                    "main_fund_net_inflow_str"
                                                )  # noqa: E501

                                    self.last_futu_update[t] = time.time()
                                    await update_quote_to_redis(t, res)
                                else:
                                    last_futu_error = res.get("message", "API 返回错误状态")  # noqa: E501
                                    yf_candidates.append(t)
                                    # 💡 失败时也更新其访问时间，防止下个循环立刻重试引发连环报错  # noqa: E501
                                    self.last_futu_update[t] = time.time()
                            except Exception as e:
                                last_futu_error = str(e)
                                print(f"⚠️ [Futu Snapshot] 主动拉取快照异常: {e}")
                                yf_candidates.append(t)
                                self.last_futu_update[t] = time.time()

                        # 🚨 运行时富途断连报警 (在批处理循环外执行，真正解决防抖失效引发的连环轰炸)  # noqa: E501
                        if batch_success:
                            if self._futu_alert_sent:
                                self._futu_alert_sent = False
                        elif last_futu_error and not self._futu_alert_sent:
                            # 💡 futu_service 内部已集成多源路由，所有源均失败时才报警
                            self._futu_alert_sent = True
                            account_snapshot = getattr(self, "last_account_summary", "未知")
                            alert_msg = (
                                f"🚨 [风控报警] 富途行情接口全面断连（本地 + 集群均失败）！\n"
                                f"系统已自动平滑降级至 YFinance 轮询兜底。\n\n"
                                f"【断线前账户快照】\n{account_snapshot}\n\n"
                                f"错误详情: {last_futu_error}"
                            )  # noqa: E501
                            asyncio.create_task(notification_service.send_alert(alert_msg))

                    # 2. 启用真实的 YFinance 兜底轮询！（仅在开关打开时执行）
                    if yf_candidates and is_yf_enabled:
                        # 💡 无论从哪进来的获取请求，统统汇入微批队列，1 秒后打包为 1 个请求发车  # noqa: E501
                        quote_tasks = [yf_service.get_batched_quote(t) for t in yf_candidates]  # noqa: E501
                        quote_results = await asyncio.gather(*quote_tasks, return_exceptions=True)  # noqa: E501

                        for ticker, q in zip(yf_candidates, quote_results):
                            if isinstance(q, dict) and q.get("status") == "success":
                                q["ticker"] = (
                                    ticker  # 覆盖被 YF 格式化去掉了前缀的 Ticker，恢复为内部标准  # noqa: E501
                                )
                                q["tech_trend"] = self.tech_cache.get(ticker, [])
                                q["requested_ticker"] = ticker
                                # [Producer 职责]：将轮询兜底数据写入 Redis 数据总线
                                await update_quote_to_redis(ticker, q)

                await asyncio.sleep(3)
            except Exception as e:
                print(f"行情与指标背景任务异常: {e}")
                await asyncio.sleep(3)


manager = ConnectionManager()
