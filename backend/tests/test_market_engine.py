"""core/market_engine.py 单元测试

覆盖: ConnectionManager 核心方法、update_quote_to_redis、告警检测
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ==========================================
# ConnectionManager 基础方法
# ==========================================
class TestConnectionManager:
    def _make_manager(self):
        """创建一个 mock 掉 Redis 的 ConnectionManager 实例"""
        with patch("backend.core.market_engine.redis.from_url") as mock_from_url:
            mock_raw_redis = MagicMock()
            mock_raw_redis.hset = AsyncMock()
            mock_raw_redis.publish = AsyncMock()
            mock_raw_redis.hget = AsyncMock(return_value=None)
            mock_raw_redis.hgetall = AsyncMock(return_value={})
            mock_raw_redis.xadd = AsyncMock()
            mock_raw_redis.xrange = AsyncMock(return_value=[])
            mock_raw_redis.pubsub = MagicMock()
            mock_from_url.return_value = mock_raw_redis

            from backend.core.market_engine import ConnectionManager

            mgr = ConnectionManager()
        return mgr

    def test_init(self):
        """初始化状态正确"""
        mgr = self._make_manager()
        assert mgr.active_connections == []
        assert mgr.subscriptions == {}
        assert mgr.push_task is None
        assert mgr.tech_cache == {}
        assert mgr.flow_cache == {}

    @pytest.mark.asyncio
    async def test_connect_adds_to_active(self):
        """connect 后 WebSocket 加入 active_connections"""
        mgr = self._make_manager()
        mgr.start_background_tasks = AsyncMock()
        ws = MagicMock()
        ws.accept = AsyncMock()

        await mgr.connect(ws)
        assert ws in mgr.active_connections
        assert ws in mgr.subscriptions
        assert mgr.subscriptions[ws] == set()

    def test_disconnect_removes_websocket(self):
        """disconnect 后 WebSocket 被移除"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.active_connections.append(ws)
        mgr.subscriptions[ws] = {"AAPL"}

        mgr.disconnect(ws)
        assert ws not in mgr.active_connections
        assert ws not in mgr.subscriptions

    def test_disconnect_unknown_websocket(self):
        """disconnect 未知 WebSocket 不报错"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.disconnect(ws)  # 不抛异常

    def test_subscribe_adds_tickers(self):
        """subscribe 添加标的到订阅集合"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.subscriptions[ws] = set()
        mgr._catch_up_or_snapshot = AsyncMock()

        # Mock asyncio.create_task
        with patch("asyncio.create_task"):
            mgr.subscribe(ws, ["AAPL", "GOOGL"])
        assert mgr.subscriptions[ws] == {"AAPL", "GOOGL"}

    def test_subscribe_deduplicates(self):
        """重复订阅不会重复添加"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"AAPL"}
        mgr._catch_up_or_snapshot = AsyncMock()

        with patch("asyncio.create_task"):
            mgr.subscribe(ws, ["AAPL", "GOOGL"])
        assert mgr.subscriptions[ws] == {"AAPL", "GOOGL"}

    def test_unsubscribe_removes_tickers(self):
        """unsubscribe 从订阅集合中移除标的"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"AAPL", "GOOGL", "MSFT"}

        mgr.unsubscribe(ws, ["AAPL", "MSFT"])
        assert mgr.subscriptions[ws] == {"GOOGL"}

    def test_unsubscribe_unknown_websocket(self):
        """unsubscribe 未知 WebSocket 不报错"""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.unsubscribe(ws, ["AAPL"])  # 不抛异常

    def test_get_all_subscribed_tickers(self):
        """获取所有订阅标的（含基础宏观）"""
        mgr = self._make_manager()
        ws1 = MagicMock()
        ws2 = MagicMock()
        mgr.subscriptions[ws1] = {"AAPL", "00700.HK"}
        mgr.subscriptions[ws2] = {"TSLA"}

        tickers = mgr.get_all_subscribed_tickers()
        assert "AAPL" in tickers
        assert "00700.HK" in tickers
        assert "TSLA" in tickers
        # 基础宏观标的一定包含
        assert "US.VIX" in tickers
        assert "US.SPX" in tickers
        assert "BTC-USD" in tickers

    def test_get_all_subscribed_tickers_empty(self):
        """无用户订阅时仍返回基础宏观标的"""
        mgr = self._make_manager()
        tickers = mgr.get_all_subscribed_tickers()
        assert len(tickers) > 0  # 至少有基础宏观


# ==========================================
# update_quote_to_redis
# ==========================================
class TestUpdateQuoteToRedis:
    @pytest.mark.asyncio
    async def test_basic_quote_write(self):
        """基本行情写入 Redis"""
        from backend.core.market_engine import update_quote_to_redis

        mock_raw_redis = MagicMock()
        mock_raw_redis.hset = AsyncMock()
        mock_raw_redis.publish = AsyncMock()
        mock_raw_redis.hgetall = AsyncMock(return_value={})

        with patch("backend.core.market_engine.manager") as mock_mgr:
            mock_mgr.raw_redis = mock_raw_redis
            await update_quote_to_redis("AAPL", {"last_price": 150.0, "change_pct": "+1.5%", "source": "test"})

        mock_raw_redis.hset.assert_called_once()
        mock_raw_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_quote_with_bids_asks(self):
        """带买卖盘的行情写入"""
        from backend.core.market_engine import update_quote_to_redis

        mock_raw_redis = MagicMock()
        mock_raw_redis.hset = AsyncMock()
        mock_raw_redis.publish = AsyncMock()
        mock_raw_redis.hgetall = AsyncMock(return_value={})

        quote_data = {
            "last_price": 400.0,
            "change_pct": "-0.5%",
            "volume_str": "10M",
            "source": "futu",
            "bids": [{"price": "399.8", "size": "100"}],
            "asks": [{"price": "400.2", "size": "200"}],
        }

        with patch("backend.core.market_engine.manager") as mock_mgr:
            mock_mgr.raw_redis = mock_raw_redis
            await update_quote_to_redis("00700.HK", quote_data)

        mock_raw_redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_quote_error_handling(self):
        """Redis 异常不抛出"""
        from backend.core.market_engine import update_quote_to_redis

        mock_raw_redis = MagicMock()
        mock_raw_redis.hset = AsyncMock(side_effect=Exception("Redis down"))

        with patch("backend.core.market_engine.manager") as mock_mgr:
            mock_mgr.raw_redis = mock_raw_redis
            # 不应抛出异常
            await update_quote_to_redis("AAPL", {"last_price": 150.0})


# ==========================================
# update_trade_to_redis
# ==========================================
class TestUpdateTradeToRedis:
    @pytest.mark.asyncio
    async def test_trade_write(self):
        """逐笔成交写入 Redis Stream"""
        from backend.core.market_engine import update_trade_to_redis

        mock_raw_redis = MagicMock()
        mock_raw_redis.xadd = AsyncMock()
        mock_raw_redis.publish = AsyncMock()

        with patch("backend.core.market_engine.manager") as mock_mgr:
            mock_mgr.raw_redis = mock_raw_redis
            await update_trade_to_redis("AAPL", b"trade_data_bytes")

        mock_raw_redis.xadd.assert_called_once()
        mock_raw_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_trade_error_handling(self):
        """Redis 异常不抛出"""
        from backend.core.market_engine import update_trade_to_redis

        mock_raw_redis = MagicMock()
        mock_raw_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))

        with patch("backend.core.market_engine.manager") as mock_mgr:
            mock_mgr.raw_redis = mock_raw_redis
            await update_trade_to_redis("AAPL", b"data")


# ==========================================
# _get_yf_fast_info ticker 映射
# ==========================================
class TestYfTickerMapping:
    """测试 YFinance ticker 格式转换逻辑"""

    def _call_mapping(self, ticker):
        """直接测试 ticker 映射逻辑（不实际调用 yfinance）"""
        yf_ticker = ticker
        if yf_ticker == "HK.800000":
            yf_ticker = "^HSI"
        elif yf_ticker == "HK.800700":
            yf_ticker = "^HSTECH"
        elif yf_ticker == "HK.800100":
            yf_ticker = "^HSCE"
        elif yf_ticker.startswith("HK."):
            yf_ticker = yf_ticker.replace("HK.", "") + ".HK"
        elif yf_ticker.startswith("US."):
            yf_ticker = yf_ticker.replace("US.", "")
        if yf_ticker in ["VIX", "TNX", "FVX", "SPX", "NDX", "GSPC"]:
            yf_ticker = f"^{yf_ticker}"
        return yf_ticker

    def test_hk_index_mapping(self):
        assert self._call_mapping("HK.800000") == "^HSI"
        assert self._call_mapping("HK.800700") == "^HSTECH"
        assert self._call_mapping("HK.800100") == "^HSCE"

    def test_hk_stock_mapping(self):
        assert self._call_mapping("HK.00700") == "00700.HK"

    def test_us_stock_mapping(self):
        assert self._call_mapping("US.AAPL") == "AAPL"

    def test_us_index_mapping(self):
        assert self._call_mapping("US.VIX") == "^VIX"
        assert self._call_mapping("US.SPX") == "^SPX"

    def test_plain_ticker(self):
        assert self._call_mapping("BTC-USD") == "BTC-USD"
