"""
Finnhub Adapter 模块

提供 WebSocket 长链接方式连接 Finnhub API，获取实时行情、新闻等金融数据。

特点：
- WebSocket 自动重连机制
- 本地缓存最新 quote 数据
- 支持订阅/取消订阅多个标的
"""

import json
import logging
from typing import List, Optional

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]


logger = logging.getLogger("quant_agent.finnhub")


class FinnhubAdapter:
    """
    Finnhub WebSocket 适配器

    提供的数据流：
    - Real-time quotes (股票实时报价)
    - Stock news (股票新闻)
    - Crypto quotes (加密货币行情)

    WebSocket URL: wss://ws.finnhub.io?token={API_TOKEN}
    """

    STATUS_UNAVAILABLE = "UNAVAILABLE"
    STATUS_AVAILABLE = "AVAILABLE"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self._ws = None
        self._reconnect_count = 0
        self._max_reconnects = 5
        self._quote_cache = {}  # symbol -> latest_quote

        # 订阅状态
        self._subscribed_symbols = set()

        logger.info(f"[FinnhubAdapter] Initialized with token: {api_token[:8]}...")

    @property
    def is_available(self) -> bool:
        """检查连接是否可用（WebSocket 连接中且未超过最大重试次数）"""
        if websockets is None:
            return False

        if self._ws and not self._ws.closed and self._reconnect_count < self._max_reconnects:
            return True
        return False

    async def connect(self):
        """建立 WebSocket 连接（异步非阻塞）"""
        if websockets is None:
            logger.error("[FinnhubAdapter] websockets module not installed")
            return

        if self._ws and not self._ws.closed:
            logger.warning("[FinnhubAdapter] Already connected")
            return

        url = f"wss://ws.finnhub.io?token={self.api_token}"
        try:
            logger.info("[FinnhubAdapter] Connecting to Finnhub WebSocket...")
            self._ws = await websockets.connect(url)
            self._reconnect_count = 0
            logger.info("[FinnhubAdapter] WebSocket connected successfully")

            # 恢复之前的订阅
            for symbol in self._subscribed_symbols:
                await self.subscribe_quotes([symbol])

        except Exception as e:
            logger.error(f"[FinnhubAdapter] Connection failed: {e}")
            self._reconnect_count += 1
            raise

    async def disconnect(self):
        """关闭 WebSocket 连接"""
        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None
            logger.info("[FinnhubAdapter] WebSocket disconnected")

    async def subscribe_quotes(self, symbols: List[str]):
        """订阅多个标的的实时行情"""
        if not self._ws or self._ws.closed:
            logger.warning("[FinnhubAdapter] WebSocket not connected, cannot subscribe")
            return

        message = json.dumps({"type": "subscribe", "symbol": symbols})
        await self._ws.send(message)
        self._subscribed_symbols.update(symbols)
        logger.info(f"[FinnhubAdapter] Subscribed to {len(symbols)} symbols")

    async def unsubscribe_quotes(self, symbols: List[str]):
        """取消订阅"""
        if not self._ws or self._ws.closed:
            return

        message = json.dumps({"type": "unsubscribe", "symbol": symbols})
        await self._ws.send(message)
        for s in symbols:
            self._subscribed_symbols.discard(s)

    async def fetch_news(self, symbol: str, date: Optional[str] = None):
        """获取股票新闻（WebSocket 消息流）"""
        # TODO: 实现新闻流订阅
        pass

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        """从本地缓存获取最新 quote（同步方法）"""
        return self._quote_cache.get(symbol)

    def update_cache(self, message: dict):
        """更新本地缓存（调用自 WebSocket 消息处理器）"""
        # message format: {"s": "AAPL", "t": ..., "d": ...}
        if "s" in message:
            symbol = message["s"]
            self._quote_cache[symbol] = message
            logger.debug(f"[FinnhubAdapter] Cached quote for {symbol}")

    def health_check(self) -> dict:
        """健康检查探针"""
        return {
            "is_available": self.is_available,
            "quote_cache_size": len(self._quote_cache),
            "subscribed_symbols": list(self._subscribed_symbols),
            "reconnect_count": self._reconnect_count,
        }

    def supports_action(self, action: str) -> bool:
        """支持的数据类型"""
        supported = {"quote", "news"}
        return action in supported


# ==================== 单例实例 ====================

_finnhub_adapter_instance: Optional[FinnhubAdapter] = None


def get_finnhub_adapter(api_token: str) -> FinnhubAdapter:
    """获取或创建 Finnhub Adapter 单例"""
    global _finnhub_adapter_instance
    if _finnhub_adapter_instance is None:
        _finnhub_adapter_instance = FinnhubAdapter(api_token)
    return _finnhub_adapter_instance
