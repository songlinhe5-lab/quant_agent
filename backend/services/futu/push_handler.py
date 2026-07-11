"""
Futu 推送数据回调处理器
将 Futu OpenD 的实时推送数据桥接到 Redis PubSub，供前端 WebSocket 消费。

数据流: Futu OpenD TCP 推送 → Handler 回调 (sync) → asyncio.run_coroutine_threadsafe → Redis PubSub → 前端 WebSocket

支持的数据类型:
  - StockQuoteHandlerBase:     实时报价推送 (→ quant:quotes:stream)
  - OrderBookHandlerBase:      盘口深度推送 (→ quant:quotes:stream, 合并 bids/asks)
  - TickerHandlerBase:         逐笔成交推送 (→ quant:trades:stream:{ticker})
  - BrokerHandlerBase:         经纪商队列推送 (→ futu:push:broker:{ticker})
  - CurKlineHandlerBase:       实时 K 线推送 (→ futu:push:kline:{ticker})
"""

import asyncio
import json
import threading
from typing import Any, Dict, Optional

import pandas as pd

from backend.core.logger import logger

# 延迟导入标记，避免循环导入
_update_quote_to_redis = None
_update_trade_to_redis = None
_redis_client = None
_main_loop = None
_main_loop_lock = threading.Lock()


def _get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """获取主事件循环（线程安全）"""
    global _main_loop
    with _main_loop_lock:
        if _main_loop is not None and _main_loop.is_running():
            return _main_loop
        return None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """由主进程启动时调用，注册主事件循环引用"""
    global _main_loop
    with _main_loop_lock:
        _main_loop = loop


def _schedule_coroutine(coro):
    """
    从 Futu SDK 的同步回调线程中安全地调度协程到主事件循环。
    使用 asyncio.run_coroutine_threadsafe() 实现跨线程桥接。
    """
    loop = _get_main_loop()
    if loop is None:
        logger.warning("[PushHandler] 主事件循环不可用，丢弃推送数据")
        return None
    return asyncio.run_coroutine_threadsafe(coro, loop)


async def _get_update_quote_fn():
    global _update_quote_to_redis
    if _update_quote_to_redis is None:
        from backend.services.market_engine import update_quote_to_redis

        _update_quote_to_redis = update_quote_to_redis
    return _update_quote_to_redis


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        from backend.core.redis_client import redis_client

        _redis_client = redis_client
    return _redis_client


def _compress_push_quote(row) -> Dict[str, Any]:
    """
    将 Futu 推送的报价 DataFrame 行转换为 update_quote_to_redis 期望的 dict 格式。
    复用 CacheManager.compress_quote_data 的逻辑但去除缓存副作用。
    """
    from backend.core.utils import safe_divide, safe_float

    last_price = safe_float(row.get("last_price", 0.0))
    prev_close = safe_float(row.get("prev_close_price", 0.0))
    change_pct = safe_divide(last_price - prev_close, prev_close) * 100
    volume = safe_float(row.get("volume", 0))

    vol_str = (
        f"{volume / 1e9:.2f}B"
        if volume >= 1e9
        else f"{volume / 1e6:.2f}M"
        if volume >= 1e6
        else f"{volume / 1e3:.2f}K"
        if volume >= 1e3
        else str(volume)
    )

    return {
        "status": "success",
        "ticker": str(row.get("code", "")),
        "last_price": last_price,
        "change_pct": f"{change_pct:+.2f}%",
        "volume_str": vol_str,
        "source": "futu_push",
    }


# ═══════════════════════════════════════════════════════════════
#  回调处理器定义
#  注意：Futu SDK 的 on_recv_rsp 在 SDK 内部线程执行，
#  必须保持同步，通过 _schedule_coroutine 桥接到异步世界。
# ═══════════════════════════════════════════════════════════════


def _make_quote_handler():
    """创建实时报价推送处理器"""
    try:
        from futu import RET_OK, StockQuoteHandlerBase
    except ImportError:
        logger.error("[PushHandler] futu-api 未安装，无法创建推送处理器")
        return None

    class FutuQuotePushHandler(StockQuoteHandlerBase):
        """实时报价推送 → Redis PubSub → 前端 WebSocket"""

        def on_recv_rsp(self, rsp_pb):
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return ret_code, data

            try:
                for _, row in data.iterrows():
                    ticker = str(row.get("code", ""))
                    if not ticker:
                        continue
                    quote_dict = _compress_push_quote(row)

                    async def _publish(qd=quote_dict, tk=ticker):
                        fn = await _get_update_quote_fn()
                        await fn(tk, qd)

                    _schedule_coroutine(_publish())
            except Exception as e:
                logger.warning(f"[PushHandler] 报价推送处理异常: {e}")

            return ret_code, data

    return FutuQuotePushHandler()


def _make_order_book_handler():
    """创建盘口深度推送处理器"""
    try:
        from futu import RET_OK, OrderBookHandlerBase
    except ImportError:
        return None

    class FutuOrderBookPushHandler(OrderBookHandlerBase):
        """盘口深度推送 → 合并到主行情流 → Redis PubSub → 前端 WebSocket"""

        def on_recv_rsp(self, rsp_pb):
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or not isinstance(data, dict):
                return ret_code, data

            try:
                ticker = data.get("code", "")
                if not ticker:
                    return ret_code, data

                bids_raw = data.get("Bid", [])
                asks_raw = data.get("Ask", [])

                # 构造 bids/asks 列表供 protobuf 序列化
                bids = [{"price": float(p), "size": float(v)} for p, v, *_ in bids_raw[:10]]
                asks = [{"price": float(p), "size": float(v)} for p, v, *_ in asks_raw[:10]]

                async def _publish():
                    from backend.core.proto.market_pb2 import Order, QuoteData

                    redis = await _get_redis()

                    # 💡 关键修复：读取最新的报价数据，合并盘口深度后重新发布到主流
                    existing_data = await redis.hget("quant:quotes:latest", ticker)

                    if existing_data:
                        # 解析现有的 Protobuf 数据
                        existing_quote = QuoteData()
                        existing_quote.ParseFromString(existing_data)

                        # 合并盘口数据
                        existing_quote.ClearField("bids")
                        existing_quote.ClearField("asks")
                        for b in bids:
                            existing_quote.bids.append(Order(price=b["price"], size=b["size"]))
                        for a in asks:
                            existing_quote.asks.append(Order(price=a["price"], size=a["size"]))

                        # 重新序列化并发布到主流
                        merged_payload = existing_quote.SerializeToString()
                        await redis.publish("quant:quotes:stream", merged_payload)
                    else:
                        # 💡 如果没有现有报价数据，创建新的 QuoteData 只包含盘口数据
                        # 确保盘口数据始终发布到主流，而不是独立频道
                        new_quote = QuoteData(
                            ticker=ticker,
                            status="realtime",
                            source="futu_push_orderbook",
                        )
                        for b in bids:
                            new_quote.bids.append(Order(price=b["price"], size=b["size"]))
                        for a in asks:
                            new_quote.asks.append(Order(price=a["price"], size=a["size"]))

                        payload = new_quote.SerializeToString()
                        await redis.publish("quant:quotes:stream", payload)
                        logger.debug(f"[PushHandler] 盘口数据发布到主流: {ticker} bids={len(bids)} asks={len(asks)}")

                _schedule_coroutine(_publish())
            except Exception as e:
                logger.warning(f"[PushHandler] 盘口推送处理异常: {e}")

            return ret_code, data

    return FutuOrderBookPushHandler()


def _make_ticker_handler():
    """创建逐笔成交推送处理器"""
    try:
        from futu import RET_OK, TickerHandlerBase
    except ImportError:
        return None

    class FutuTickerPushHandler(TickerHandlerBase):
        """逐笔成交推送 → Redis Stream → 前端实时交易流"""

        def on_recv_rsp(self, rsp_pb):
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return ret_code, data

            try:
                for _, row in data.iterrows():
                    ticker = str(row.get("code", ""))
                    if not ticker:
                        continue

                    trade_data = {
                        "ticker": ticker,
                        "price": float(row.get("price", 0.0)),
                        "volume": int(row.get("volume", 0)),
                        "side": str(row.get("side", "")),
                        "time": str(row.get("time", "")),
                    }

                    async def _publish(td=trade_data, tk=ticker):
                        redis = await _get_redis()
                        await redis.publish(
                            f"futu:push:ticker:{tk}",
                            json.dumps(td),
                        )

                    _schedule_coroutine(_publish())
            except Exception as e:
                logger.warning(f"[PushHandler] 逐笔成交推送异常: {e}")

            return ret_code, data

    return FutuTickerPushHandler()


def _make_broker_handler():
    """创建经纪商队列推送处理器（仅港股）"""
    try:
        from futu import RET_OK, BrokerHandlerBase
    except ImportError:
        return None

    class FutuBrokerPushHandler(BrokerHandlerBase):
        """经纪商队列推送 → Redis PubSub (仅港股有数据)"""

        def on_recv_rsp(self, rsp_pb):
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or not isinstance(data, dict):
                return ret_code, data

            try:
                ticker = data.get("code", "")
                if not ticker:
                    return ret_code, data

                bid_brokers = data.get("bid_broker_queue", [])
                ask_brokers = data.get("ask_broker_queue", [])

                async def _publish():
                    redis = await _get_redis()
                    payload = json.dumps(
                        {
                            "ticker": ticker,
                            "bid_brokers": [str(b) for b in bid_brokers[:10]],
                            "ask_brokers": [str(b) for b in ask_brokers[:10]],
                            "source": "futu_push",
                        }
                    )
                    await redis.publish(f"futu:push:broker:{ticker}", payload)

                _schedule_coroutine(_publish())
            except Exception as e:
                logger.warning(f"[PushHandler] 经纪商队列推送异常: {e}")

            return ret_code, data

    return FutuBrokerPushHandler()


def _make_kline_handler():
    """创建实时 K 线推送处理器"""
    try:
        from futu import RET_OK, CurKlineHandlerBase
    except ImportError:
        return None

    class FutuKlinePushHandler(CurKlineHandlerBase):
        """实时 K 线推送 → Redis PubSub"""

        def on_recv_rsp(self, rsp_pb):
            ret_code, data = super().on_recv_rsp(rsp_pb)
            if ret_code != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return ret_code, data

            try:
                for _, row in data.iterrows():
                    ticker = str(row.get("code", ""))
                    if not ticker:
                        continue

                    kline_data = {
                        "ticker": ticker,
                        "time": str(row.get("time_key", "")),
                        "open": float(row.get("open", 0.0)),
                        "high": float(row.get("high", 0.0)),
                        "low": float(row.get("low", 0.0)),
                        "close": float(row.get("close", 0.0)),
                        "volume": float(row.get("volume", 0.0)),
                    }

                    async def _publish(kd=kline_data, tk=ticker):
                        redis = await _get_redis()
                        await redis.publish(f"futu:push:kline:{tk}", json.dumps(kd))

                    _schedule_coroutine(_publish())
            except Exception as e:
                logger.warning(f"[PushHandler] K线推送异常: {e}")

            return ret_code, data

    return FutuKlinePushHandler()


# ═══════════════════════════════════════════════════════════════
#  统一注册入口
# ═══════════════════════════════════════════════════════════════


def register_all_handlers(quote_ctx) -> Dict[str, bool]:
    """
    向 OpenQuoteContext 注册所有推送回调处理器。
    应在 ConnectionManager.connect() 成功后立即调用。

    Args:
        quote_ctx: futu.OpenQuoteContext 实例

    Returns:
        注册结果 dict，key 为处理器名称，value 为是否成功注册
    """
    results = {}

    handlers = {
        "quote": _make_quote_handler,
        "order_book": _make_order_book_handler,
        "ticker": _make_ticker_handler,
        "broker": _make_broker_handler,
        "kline": _make_kline_handler,
    }

    for name, factory in handlers.items():
        try:
            handler = factory()
            if handler is None:
                results[name] = False
                logger.warning(f"[PushHandler] {name} 处理器创建失败 (futu SDK 类不可用)")
                continue
            quote_ctx.set_handler(handler)
            results[name] = True
            logger.info(f"[PushHandler] ✅ {name} 推送处理器已注册")
        except Exception as e:
            results[name] = False
            logger.warning(f"[PushHandler] {name} 处理器注册失败: {e}")

    success_count = sum(1 for v in results.values() if v)
    print(f"📡 [PushHandler] 推送回调注册完成: {success_count}/{len(handlers)} 成功")
    return results
