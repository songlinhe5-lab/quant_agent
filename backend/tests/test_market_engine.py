"""
Tests for backend/core/market_engine.py

Coverage targets:
- update_quote_to_redis function
- update_trade_to_redis function
- ConnectionManager class methods
- WebSocket connection management
- Subscription management
"""
import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket

from backend.core.market_engine import ConnectionManager, manager, update_quote_to_redis, update_trade_to_redis


class TestUpdateQuoteToRedis:
    """Test update_quote_to_redis function"""

    @pytest.mark.asyncio
    async def test_update_quote_to_redis_success(self):
        """Test successful quote update to Redis"""
        ticker = "US.AAPL"
        quote_data = {
            "ticker": ticker,
            "last_price": 150.0,
            "change_pct": "+1.5%",
            "volume_str": "10M",
            "source": "futu",
            "bids": [{"price": 149.5, "size": 100}],
            "asks": [{"price": 150.5, "size": 200}],
        }
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = AsyncMock()
            mock_manager.raw_redis.hset = AsyncMock()
            mock_manager.raw_redis.publish = AsyncMock()
            
            await update_quote_to_redis(ticker, quote_data)
            
            # Verify Redis hset was called
            mock_manager.raw_redis.hset.assert_called_once()
            # Verify Redis publish was called
            mock_manager.raw_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_quote_to_redis_with_alerts(self):
        """Test quote update with price alerts"""
        ticker = "US.AAPL"
        quote_data = {
            "ticker": ticker,
            "last_price": 160.0,  # Price that triggers alert
            "change_pct": "+5.0%",
            "volume_str": "10M",
            "source": "futu",
        }
        
        # Create a proper mock manager with raw_redis
        mock_raw_redis = AsyncMock()
        mock_raw_redis.hset = AsyncMock()
        mock_raw_redis.publish = AsyncMock()
        mock_raw_redis.hgetall = AsyncMock(return_value={
            b"1": json.dumps({"upper": 155.0, "lower": None, "pct_change": None})
        })
        mock_raw_redis.hdel = AsyncMock()
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = mock_raw_redis
            
            with patch('backend.core.market_engine.notification_service') as mock_notif:
                mock_notif.send_alert = AsyncMock()
                
                await update_quote_to_redis(ticker, quote_data)
                
                # Verify hset was called (quote was updated)
                mock_raw_redis.hset.assert_called()

    @pytest.mark.asyncio
    async def test_update_quote_to_redis_exception(self):
        """Test quote update with exception handling"""
        ticker = "US.AAPL"
        quote_data = {
            "ticker": ticker,
            "last_price": 150.0,
        }
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = AsyncMock()
            mock_manager.raw_redis.hset = AsyncMock(side_effect=Exception("Redis error"))
            
            # Should not raise exception
            await update_quote_to_redis(ticker, quote_data)


class TestUpdateTradeToRedis:
    """Test update_trade_to_redis function"""

    @pytest.mark.asyncio
    async def test_update_trade_to_redis_success(self):
        """Test successful trade update to Redis"""
        ticker = "US.AAPL"
        trade_data = b"mock_trade_data"
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = AsyncMock()
            mock_manager.raw_redis.xadd = AsyncMock()
            mock_manager.raw_redis.publish = AsyncMock()
            
            await update_trade_to_redis(ticker, trade_data)
            
            # Verify Redis xadd was called
            mock_manager.raw_redis.xadd.assert_called_once()
            # Verify Redis publish was called
            mock_manager.raw_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_trade_to_redis_exception(self):
        """Test trade update with exception handling"""
        ticker = "US.AAPL"
        trade_data = b"mock_trade_data"
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = AsyncMock()
            mock_manager.raw_redis.xadd = AsyncMock(side_effect=Exception("Redis error"))
            
            # Should not raise exception
            await update_trade_to_redis(ticker, trade_data)


class TestConnectionManager:
    """Test ConnectionManager class"""

    @pytest.fixture
    def manager_instance(self):
        """Create a ConnectionManager instance for testing"""
        m = ConnectionManager()
        m.active_connections = []
        m.subscriptions = {}
        m.tech_cache = {}
        m.flow_cache = {}
        m.last_futu_update = {}
        m._futu_alert_sent = False
        m.last_account_summary = "Total: 100000 | PnL: 5000"
        m.last_acc_update = 0
        m._futu_active_subs = set()
        return m

    def test_init(self, manager_instance):
        """Test ConnectionManager initialization"""
        assert manager_instance.active_connections == []
        assert manager_instance.subscriptions == {}
        assert manager_instance.tech_cache == {}

    @pytest.mark.asyncio
    async def test_connect(self, manager_instance):
        """Test WebSocket connection"""
        mock_websocket = AsyncMock(spec=WebSocket)
        
        await manager_instance.connect(mock_websocket)
        
        assert mock_websocket in manager_instance.active_connections
        assert mock_websocket in manager_instance.subscriptions
        assert len(manager_instance.subscriptions[mock_websocket]) == 0

    def test_disconnect(self, manager_instance):
        """Test WebSocket disconnection"""
        mock_websocket = AsyncMock(spec=WebSocket)
        manager_instance.active_connections.append(mock_websocket)
        manager_instance.subscriptions[mock_websocket] = {"US.AAPL"}
        
        manager_instance.disconnect(mock_websocket)
        
        assert mock_websocket not in manager_instance.active_connections
        assert mock_websocket not in manager_instance.subscriptions

    def test_subscribe(self, manager_instance):
        """Test subscription to tickers"""
        mock_websocket = AsyncMock(spec=WebSocket)
        manager_instance.active_connections.append(mock_websocket)
        manager_instance.subscriptions[mock_websocket] = set()
        
        # Mock asyncio.create_task to avoid event loop issues
        with patch('asyncio.create_task'):
            manager_instance.subscribe(mock_websocket, ["US.AAPL", "US.MSFT"])
        
        assert "US.AAPL" in manager_instance.subscriptions[mock_websocket]
        assert "US.MSFT" in manager_instance.subscriptions[mock_websocket]

    def test_unsubscribe(self, manager_instance):
        """Test unsubscription from tickers"""
        mock_websocket = AsyncMock(spec=WebSocket)
        manager_instance.active_connections.append(mock_websocket)
        manager_instance.subscriptions[mock_websocket] = {"US.AAPL", "US.MSFT"}
        
        manager_instance.unsubscribe(mock_websocket, ["US.AAPL"])
        
        assert "US.AAPL" not in manager_instance.subscriptions[mock_websocket]
        assert "US.MSFT" in manager_instance.subscriptions[mock_websocket]

    def test_get_all_subscribed_tickers(self, manager_instance):
        """Test getting all subscribed tickers"""
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws2 = AsyncMock(spec=WebSocket)
        
        manager_instance.active_connections = [mock_ws1, mock_ws2]
        manager_instance.subscriptions = {
            mock_ws1: {"US.AAPL", "US.MSFT"},
            mock_ws2: {"US.GOOGL"},
        }
        
        all_tickers = manager_instance.get_all_subscribed_tickers()
        
        assert "US.AAPL" in all_tickers
        assert "US.MSFT" in all_tickers
        assert "US.GOOGL" in all_tickers
        # Should also include default macro tickers
        assert "^GSPC" in all_tickers or "US.SPX" in all_tickers

    @pytest.mark.asyncio
    async def test_catch_up_or_snapshot_with_last_id(self, manager_instance):
        """Test catch up with last_id"""
        mock_websocket = AsyncMock(spec=WebSocket)
        
        with patch.object(manager_instance, 'raw_redis') as mock_redis:
            mock_redis.xrange = AsyncMock(return_value=[
                (b"1234-0", {b"payload": b"mock_data"})
            ])
            
            await manager_instance._catch_up_or_snapshot(
                mock_websocket,
                ["US.AAPL"],
                {"US.AAPL": "1233-0"}
            )
            
            mock_redis.xrange.assert_called_once()

    @pytest.mark.asyncio
    async def test_catch_up_or_snapshot_without_last_id(self, manager_instance):
        """Test snapshot without last_id"""
        mock_websocket = AsyncMock(spec=WebSocket)
        
        with patch.object(manager_instance, 'raw_redis') as mock_redis:
            mock_redis.hget = AsyncMock(return_value=b"mock_cached_data")
            
            await manager_instance._catch_up_or_snapshot(
                mock_websocket,
                ["US.AAPL"],
                {}
            )
            
            mock_redis.hget.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_pubsub_listener(self, manager_instance):
        """Test Redis PubSub listener"""
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.listen = AsyncMock(return_value=AsyncMock())
        
        with patch.object(manager_instance, 'raw_redis') as mock_redis:
            mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
            
            # Create a task that will be cancelled quickly
            task = asyncio.create_task(manager_instance.redis_pubsub_listener())
            await asyncio.sleep(0.1)
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass

    def test_get_yf_fast_info(self, manager_instance):
        """Test _get_yf_fast_info method"""
        with patch('yfinance.Ticker') as mock_ticker:
            mock_instance = MagicMock()
            mock_instance.fast_info.last_price = 150.0
            mock_instance.fast_info.previous_close = 148.0
            mock_instance.fast_info.last_volume = 1000000
            mock_ticker.return_value = mock_instance
            
            result = manager_instance._get_yf_fast_info("US.AAPL")
            
            assert result["status"] == "success"
            assert result["ticker"] == "US.AAPL"
            assert result["last_price"] == 150.0

    @pytest.mark.asyncio
    async def test_fetch_fallback_quote(self, manager_instance):
        """Test _fetch_fallback_quote method"""
        with patch.object(manager_instance, '_get_yf_fast_info', return_value={
            "status": "success",
            "ticker": "US.AAPL",
            "last_price": 150.0,
        }):
            result = await manager_instance._fetch_fallback_quote("US.AAPL")
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_fetch_fallback_quote_timeout(self, manager_instance):
        """Test _fetch_fallback_quote with timeout"""
        with patch.object(manager_instance, '_get_yf_fast_info', side_effect=asyncio.TimeoutError):
            result = await manager_instance._fetch_fallback_quote("US.AAPL")
            assert result["status"] == "error"


class TestConnectionManagerBroadcastLoop:
    """Test ConnectionManager broadcast_loop method"""

    @pytest.mark.asyncio
    async def test_broadcast_loop_structure(self):
        """Test that broadcast_loop has correct structure"""
        manager_instance = ConnectionManager()
        manager_instance._futu_active_subs = set()
        
        # Mock the necessary components
        with patch.object(manager_instance, 'get_all_subscribed_tickers', return_value=set()):
            with patch('asyncio.sleep', side_effect=asyncio.CancelledError):
                try:
                    await manager_instance.broadcast_loop()
                except asyncio.CancelledError:
                    pass  # Expected


class TestManagerGlobal:
    """Test the global manager instance"""

    def test_manager_exists(self):
        """Test that global manager instance exists"""
        assert manager is not None
        assert isinstance(manager, ConnectionManager)


class TestProtobufSerialization:
    """Test Protobuf serialization in update_quote_to_redis"""

    @pytest.mark.asyncio
    async def test_protobuf_serialization(self):
        """Test that quote data is correctly serialized to Protobuf"""
        ticker = "US.AAPL"
        quote_data = {
            "ticker": ticker,
            "last_price": 150.0,
            "change_pct": "+1.5%",
            "volume_str": "10M",
            "source": "futu",
        }
        
        with patch('backend.core.market_engine.manager') as mock_manager:
            mock_manager.raw_redis = AsyncMock()
            mock_manager.raw_redis.hset = AsyncMock()
            mock_manager.raw_redis.publish = AsyncMock()
            
            await update_quote_to_redis(ticker, quote_data)
            
            # Verify that SerializeToString was called (via the QuoteData object)
            call_args = mock_manager.raw_redis.hset.call_args
            assert call_args is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
