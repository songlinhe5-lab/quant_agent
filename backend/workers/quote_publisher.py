import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as redis

# 引入编译好的 Protobuf 模块 (运行 protoc 后会生成)
from backend.core.proto.market_pb2 import Order, QuoteData  # type: ignore

# 💡 将高频依赖移至顶部，避免在每秒成百上千次的 Tick 循环中重复导入引发局部字典查找开销
from backend.services.futu_service import futu_service

logger = logging.getLogger(__name__)


class QuotePublisher:
    """
    行情生产者任务 (Publisher)
    负责后台独立轮询外部 API，清洗数据后推送到 Redis 消息总线，
    彻底与 WebSocket 前端解耦。
    """

    def __init__(self, redis_url: str | None = None):
        if not redis_url:
            host = os.getenv("REDIS_HOST", "localhost")
            port = os.getenv("REDIS_PORT", "6379")
            password = os.getenv("REDIS_PASSWORD", "quant_redis_secret_2026")
            redis_url = f"redis://:{password}@{host}:{port}"

        # 🚨【核心改造】移除 decode_responses=True，让 Redis 客户端能处理原始二进制流
        self.redis = redis.from_url(redis_url, protocol=2)
        self.is_running = False
        self._futu_tool = None
        self._consecutive_yf_429 = 0

    # ==========================================
    # 数据获取层 (此处可替换为您真实的 Tools)
    # ==========================================
    async def _fetch_futu_data(self, ticker: str) -> dict[str, Any]:
        """尝试拉取首选数据源: Futu OpenD (包含 Level 2 盘口)"""
        # 并发拉取报价与盘口，提升效率
        quote_task = futu_service.get_quote(ticker)
        order_book_task = futu_service.get_order_book(ticker)

        results = await asyncio.gather(
            quote_task, order_book_task, return_exceptions=True
        )

        quote_result, order_book_result = results

        # --- 解析报价 ---
        if isinstance(quote_result, BaseException):
            raise ConnectionError(f"Futu Service 拉取报价失败: {quote_result}")
        if isinstance(quote_result, str):
            try:
                quote_result = json.loads(quote_result)
            except json.JSONDecodeError:
                msg = f"FutuTool 返回了非法的报价 JSON: {quote_result}"
                raise ValueError(msg)

        # --- 解析盘口 (带容错) ---
        bids, asks = [], []
        if isinstance(order_book_result, BaseException):
            logger.warning(f"[{ticker}] Futu Service 拉取盘口失败: {order_book_result}")
        elif isinstance(order_book_result, dict):
            # 兼容不同券商接口可能返回的字段名
            bids = order_book_result.get("bids", order_book_result.get("bid_list", []))
            asks = order_book_result.get("asks", order_book_result.get("ask_list", []))

        # --- 组合数据 ---
        return {
            "ticker": ticker,
            "last_price": float(
                quote_result.get("last_price", quote_result.get("price", 0.0))
            ),
            "change_pct": quote_result.get("change_pct", "0.0%"),
            "volume_str": quote_result.get("volume_str", "--"),
            "bids": bids,
            "asks": asks,
            "source": "futu",
        }

    def _get_mock_data(self, ticker: str) -> dict[str, Any]:
        """终极兜底数据源: 零幻觉本地沙箱 Mock"""
        return {
            "ticker": ticker,
            "last_price": 100.00,
            "change_pct": "0.0%",
            "volume_str": "0",
            "bids": [],
            "asks": [],
            "source": "mock",
        }

    # ==========================================
    # 核心生产逻辑
    # ==========================================
    async def poll_and_publish(self, ticker: str):
        """拉取单个标的行情并推送到 Redis (带容灾机制)"""
        data = None
        try:
            # 强制仅从首选数据源拉取: Futu OpenD
            data = await asyncio.wait_for(self._fetch_futu_data(ticker), timeout=15.0)
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                err_msg = "拉取超时"
            else:
                err_msg = f"拉取异常 {type(e).__name__}: {e}"
            logger.error(
                f"[{ticker}] Futu {err_msg}.系统已关闭 YFinance 兜底，使用 Mock 兜底."
            )
            # 终极兜底：防止系统死锁或前端白屏
            data = self._get_mock_data(ticker)

        if data:
            # 1. 组装 Protobuf 对象
            quote_msg = QuoteData(
                status="success",
                ticker=data.get("ticker", ticker),
                last_price=data.get("last_price", 0.0),
                change_pct=data.get("change_pct", "0.0%"),
                volume_str=data.get("volume_str", "--"),
                source=data.get("source", "unknown"),
            )

            # 组装盘口 (Bids / Asks)
            for b in data.get("bids", []):
                quote_msg.bids.append(
                    Order(price=b.get("price", 0.0), size=b.get("size", 0.0))
                )
            for a in data.get("asks", []):
                quote_msg.asks.append(
                    Order(price=a.get("price", 0.0), size=a.get("size", 0.0))
                )

            # 2. 序列化为极其紧凑的二进制 Bytes
            payload_bytes = quote_msg.SerializeToString()

            # 【双写策略】
            # A. 写入最新快照 (HSET)，供前端刚打开页面时瞬间获取当前盘口
            await self.redis.hset("quant:quotes:latest", ticker, payload_bytes)  # type: ignore

            # B. 发布到实时总线 (PUBLISH)，供所有已建立 WebSocket 连接的用户实时跳动
            await self.redis.publish("quant:quotes:stream", payload_bytes)  # type: ignore

            log_msg = (
                f"已推送 {ticker}: {data['last_price']} ({data['source']}) [protobuf]"
            )
            if data.get("bids") or data.get("asks"):
                bid_cnt = len(data.get("bids", []))
                ask_cnt = len(data.get("asks", []))
                log_msg += f" | 盘口: {bid_cnt}/{ask_cnt}"
            logger.debug(log_msg)

    async def run_daemon(self, tickers: list[str], interval: float = 1.0):
        """启动生产者守护轮询进程"""
        self.is_running = True
        logger.info(f"🚀 启动行情生产者 Daemon，关注标的: {tickers}...")

        # 设置全局并发信号量，防止瞬间高并发打满 Futu 连接池或触发 YFinance IP 封禁
        sem = asyncio.Semaphore(2)

        async def _bounded_poll(t: str):
            async with sem:
                await self.poll_and_publish(t)
            # 💡 性能瓶颈修复：休眠必须放在释放锁 (async with sem) 之后！
            # 否则并发槽位会被死死霸占，导致更新被拉长，完全失去高频意义。
            await asyncio.sleep(0.1)  # 释放锁后微小错峰即可

        try:
            while self.is_running:
                # 采用限流并发拉取
                tasks = [_bounded_poll(ticker) for ticker in tickers]
                await asyncio.gather(*tasks, return_exceptions=True)

                # 💡 及时释放大对象：清除任务组和闭包结果，
                # 防止在接下来的 interval 休眠期内成为幽灵内存
                tasks = None

                # 严格控制拉取频率，防止被外部 API 封禁 (Rate Limit)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("🛑 行情生产者 Daemon 收到取消信号，正在安全退出...")
        finally:
            self.is_running = False
            await self.redis.aclose()  # type: ignore


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    asyncio.run(
        QuotePublisher().run_daemon(["US.AAPL", "HK.00700", "US.TSLA"], interval=1.5)
    )
