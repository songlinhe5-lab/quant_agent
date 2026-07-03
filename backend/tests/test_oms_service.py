"""
OMS Service 单元测试
覆盖: backend/services/oms_service.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── OmsService 单元测试 ───────────────────────────────────────────────────────
class TestOmsService:
    """OMS 核心服务测试"""

    @patch("backend.services.oms_service.redis_client")
    def test_create_order_success(self, mock_redis):
        """创建订单成功"""
        from backend.services.oms_service import OmsService

        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.publish = AsyncMock()

        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_order.order_id = "ord_001"
        mock_order.symbol = "00700.HK"
        mock_order.side = "BUY"
        mock_order.price = 400.0
        mock_order.qty = 100
        mock_order.filled_qty = 0
        mock_order.status = "SUBMITTED"
        mock_order.created_at = datetime.now()

        service = OmsService()

        with patch("backend.services.oms_service.Order", return_value=mock_order):
            import asyncio

            result = asyncio.run(service.create_order(mock_db, "ord_001", "00700.HK", "BUY", "LIMIT", 100, 400.0))

        assert result["status"] == "success"
        assert result["order_id"] == "ord_001"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_order_db_error(self):
        """创建订单 DB 异常回滚"""
        from backend.services.oms_service import OmsService

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit.side_effect = Exception("DB error")

        service = OmsService()

        result = asyncio.run(service.create_order(mock_db, "ord_002", "00700.HK", "BUY", "LIMIT", 100, 400.0))

        assert result["status"] == "error"
        assert "DB error" in result["message"]
        mock_db.rollback.assert_called_once()

    @patch("backend.services.oms_service.redis_client")
    def test_update_order_status_success(self, mock_redis):
        """更新订单状态成功"""
        from backend.services.oms_service import OmsService

        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.publish = AsyncMock()

        mock_order = MagicMock()
        mock_order.order_id = "ord_001"
        mock_order.status = "SUBMITTED"
        mock_order.created_at = datetime.now()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order

        service = OmsService()

        result = asyncio.run(service.update_order_status(mock_db, "ord_001", "FILLED", filled_qty=100))

        assert result is True
        assert mock_order.status == "FILLED"
        assert mock_order.filled_qty == 100
        mock_db.commit.assert_called_once()

    def test_update_order_status_not_found(self):
        """更新不存在的订单返回 False"""
        from backend.services.oms_service import OmsService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = OmsService()

        result = asyncio.run(service.update_order_status(mock_db, "ord_not_exist", "FILLED"))

        assert result is False

    @patch("backend.services.oms_service.redis_client")
    def test_get_active_orders_from_cache(self, mock_redis):
        """活动订单从 Redis 缓存读取"""
        from backend.services.oms_service import OmsService

        cached_orders = [{"id": "ord_001", "symbol": "00700.HK", "status": "SUBMITTED"}]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_orders))

        mock_db = MagicMock()
        service = OmsService()

        result = asyncio.run(service.get_active_orders(mock_db))

        assert len(result) == 1
        assert result[0]["id"] == "ord_001"
        mock_db.query.assert_not_called()

    @patch("backend.services.oms_service.redis_client")
    def test_get_active_orders_from_db(self, mock_redis):
        """缓存未命中时从 DB 加载"""
        from backend.services.oms_service import OmsService

        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_order = MagicMock()
        mock_order.order_id = "ord_002"
        mock_order.symbol = "00700.HK"
        mock_order.side = "BUY"
        mock_order.price = 400.0
        mock_order.qty = 100
        mock_order.filled_qty = 0
        mock_order.status = "SUBMITTED"
        mock_order.created_at = datetime.now()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_order]

        service = OmsService()

        result = asyncio.run(service.get_active_orders(mock_db))

        assert len(result) == 1
        assert result[0]["id"] == "ord_002"
        mock_redis.set.assert_called_once()

    @patch("backend.services.oms_service.redis_client")
    def test_get_historical_trades(self, mock_redis):
        """获取历史成交记录"""
        from backend.services.oms_service import OmsService

        mock_trade = MagicMock()
        mock_trade.id = 1
        mock_trade.ticker = "00700.HK"
        mock_trade.action = "BUY"
        mock_trade.price = 400.0
        mock_trade.qty = 100
        mock_trade.timestamp = datetime.now()

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_trade]

        service = OmsService()

        result = asyncio.run(service.get_historical_trades(mock_db, limit=10))

        assert len(result) == 1
        assert result[0]["symbol"] == "00700.HK"
        assert result[0]["side"] == "BUY"

    @patch("backend.services.oms_service.redis_client")
    def test_mark_all_orders_cancelled(self, mock_redis):
        """熔断时标记所有订单为 CANCELLED"""
        from backend.services.oms_service import OmsService

        mock_redis.delete = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.publish = AsyncMock()

        mock_query = MagicMock()
        mock_query.filter.return_value.update.return_value = 3

        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        service = OmsService()

        result = asyncio.run(service.mark_all_orders_cancelled(mock_db))

        assert result == 3
        mock_db.commit.assert_called_once()
        mock_redis.delete.assert_called_once()

    @patch("backend.services.oms_service.redis_client")
    def test_get_cached_positions(self, mock_redis):
        """从 Redis 缓存读取持仓"""
        from backend.services.oms_service import OmsService

        positions = [{"code": "00700.HK", "qty": 100}]
        mock_redis.get = AsyncMock(return_value=json.dumps(positions))

        service = OmsService()

        result = asyncio.run(service.get_cached_positions("HK"))

        assert len(result) == 1
        assert result[0]["code"] == "00700.HK"

    @patch("backend.services.oms_service.redis_client")
    def test_get_cached_positions_empty(self, mock_redis):
        """缓存为空时返回空列表"""
        from backend.services.oms_service import OmsService

        mock_redis.get = AsyncMock(return_value=None)

        service = OmsService()

        result = asyncio.run(service.get_cached_positions("HK"))

        assert result == []

    def test_order_to_api_format(self):
        """订单模型转 API 格式"""
        from backend.services.oms_service import OmsService

        mock_order = MagicMock()
        mock_order.order_id = "ord_001"
        mock_order.symbol = "00700.HK"
        mock_order.side = "BUY"
        mock_order.price = 400.5
        mock_order.qty = 100
        mock_order.filled_qty = 50
        mock_order.status = "SUBMITTED"
        mock_order.created_at = datetime(2024, 1, 1, 10, 30, 45)

        result = OmsService._order_to_api_format(mock_order)

        assert result["id"] == "ord_001"
        assert result["symbol"] == "00700.HK"
        assert result["price"] == "400.50"
        assert result["qty"] == 100
        assert result["filled"] == 50
        assert result["time"] == "10:30:45"

    def test_trade_to_api_format(self):
        """成交记录转 API 格式"""
        from backend.services.oms_service import OmsService

        mock_trade = MagicMock()
        mock_trade.id = 42
        mock_trade.ticker = "00700.HK"
        mock_trade.action = "SELL"
        mock_trade.price = 410.0
        mock_trade.qty = 100
        mock_trade.timestamp = datetime(2024, 1, 1, 14, 0, 0)

        result = OmsService._trade_to_api_format(mock_trade)

        assert result["id"] == "42"
        assert result["symbol"] == "00700.HK"
        assert result["side"] == "SELL"
        assert result["avg_price"] == "410.00"
        assert result["qty"] == 100
