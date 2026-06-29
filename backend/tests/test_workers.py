"""Workers 模块单元测试：quote_publisher + daemon"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("HOME", "/tmp/fake_home")


class TestQuotePublisher:
    """行情生产者 Worker 测试"""

    def test_init_default_redis_url_uses_env_vars(self):
        """测试默认构造使用环境变量构建 Redis URL"""
        with patch.dict(os.environ, {"REDIS_HOST": "myhost", "REDIS_PORT": "6380", "REDIS_PASSWORD": "secret"}):
            with patch("backend.workers.quote_publisher.redis.from_url") as mock_from_url:
                mock_from_url.return_value = MagicMock()
                from backend.workers.quote_publisher import QuotePublisher

                pub = QuotePublisher()
                assert pub.is_running is False
                url_arg = mock_from_url.call_args[0][0]
                assert "myhost" in url_arg
                assert "6380" in url_arg

    def test_init_custom_redis_url_uses_provided(self):
        """测试传入自定义 Redis URL"""
        with patch("backend.workers.quote_publisher.redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            from backend.workers.quote_publisher import QuotePublisher

            QuotePublisher(redis_url="redis://custom:6379")
            assert mock_from_url.call_args[0][0] == "redis://custom:6379"

    async def test_fetch_futu_data_success_returns_combined_data(self):
        """测试 Futu 数据拉取成功返回组合行情"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            with patch("backend.workers.quote_publisher.futu_service") as mock_futu:
                mock_futu.get_quote = AsyncMock(
                    return_value={"last_price": 150.0, "change_pct": "1.5%", "volume_str": "10M"}
                )
                mock_futu.get_order_book = AsyncMock(
                    return_value={"bids": [{"price": 149.5, "size": 100}], "asks": [{"price": 150.5, "size": 200}]}
                )
                result = await pub._fetch_futu_data("US.AAPL")
                assert result["ticker"] == "US.AAPL"
                assert result["last_price"] == 150.0
                assert result["source"] == "futu"
                assert len(result["bids"]) == 1
                assert len(result["asks"]) == 1

    async def test_fetch_futu_data_quote_exception_raises_connection_error(self):
        """测试报价拉取异常抛出 ConnectionError"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            with patch("backend.workers.quote_publisher.futu_service") as mock_futu:
                mock_futu.get_quote = AsyncMock(side_effect=RuntimeError("连接失败"))
                mock_futu.get_order_book = AsyncMock(return_value={})
                with pytest.raises(ConnectionError):
                    await pub._fetch_futu_data("US.AAPL")

    def test_get_mock_data_returns_correct_structure(self):
        """测试 Mock 兜底数据结构正确"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            data = pub._get_mock_data("US.AAPL")
            assert data["ticker"] == "US.AAPL"
            assert data["last_price"] == 100.00
            assert data["source"] == "mock"

    async def test_poll_and_publish_success_publishes_to_redis(self):
        """测试成功拉取后发布 Protobuf 到 Redis"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()
            with patch("backend.workers.quote_publisher.futu_service") as mock_futu:
                mock_futu.get_quote = AsyncMock(
                    return_value={"last_price": 150.0, "change_pct": "1.5%", "volume_str": "10M"}
                )
                mock_futu.get_order_book = AsyncMock(return_value={"bids": [{"price": 149.5, "size": 100}], "asks": []})
                await pub.poll_and_publish("US.AAPL")
                assert pub.redis.hset.called
                assert pub.redis.publish.called

    async def test_poll_and_publish_futu_failure_falls_back_to_mock(self):
        """测试 Futu 拉取失败后降级到 Mock 数据"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()
            with patch.object(pub, "_fetch_futu_data", side_effect=asyncio.TimeoutError()):
                await pub.poll_and_publish("US.AAPL")
                assert pub.redis.hset.called

    async def test_run_daemon_cancellation_exits_gracefully(self):
        """测试 Daemon 收到取消信号后优雅退出"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()
            with patch("backend.workers.quote_publisher.futu_service") as mock_futu:
                mock_futu.get_quote = AsyncMock(return_value={"last_price": 150.0})
                mock_futu.get_order_book = AsyncMock(return_value={})
                task = asyncio.create_task(pub.run_daemon(["US.AAPL"], interval=0.01))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                assert pub.is_running is False


class TestDaemon:
    """daemon.py Worker 测试"""

    def test_init_trade_db_is_noop(self):
        """测试 init_trade_db 为空操作"""
        from backend.workers.daemon import init_trade_db

        init_trade_db()

    def test_log_trade_success_writes_to_db(self):
        """测试 log_trade 成功写入数据库"""
        mock_db = MagicMock()
        with patch("backend.workers.daemon.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_sl.return_value.__exit__ = MagicMock(return_value=None)
            from backend.workers.daemon import log_trade

            log_trade("US.AAPL", "BUY", 150.0, 100, "success", "ok")
            assert mock_db.add.called
            assert mock_db.commit.called

    def test_log_trade_failure_does_not_raise(self):
        """测试 log_trade 数据库异常时不抛出"""
        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB error")
        with patch("backend.workers.daemon.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_sl.return_value.__exit__ = MagicMock(return_value=None)
            from backend.workers.daemon import log_trade

            log_trade("US.AAPL", "BUY", 150.0, 100, "success", "ok")

    async def test_execute_trade_success_returns_response(self):
        """测试 execute_trade 成功返回响应"""
        from backend.workers.daemon import QuoteMonitorHandler

        handler = QuoteMonitorHandler()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "success"}
        mock_resp.raise_for_status = MagicMock()
        with patch("backend.workers.daemon.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client
            result = await handler.execute_trade("US.AAPL", "BUY", 1, 150.0)
            assert result["status"] == "success"

    async def test_execute_trade_failure_returns_error(self):
        """测试 execute_trade 网络异常返回错误"""
        from backend.workers.daemon import QuoteMonitorHandler

        handler = QuoteMonitorHandler()
        with patch("backend.workers.daemon.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client
            result = await handler.execute_trade("US.AAPL", "BUY", 1, 150.0)
            assert result["status"] == "error"

    def test_start_daemon_runs_without_error(self):
        """测试 start_daemon 初始化不报错"""
        with patch("backend.workers.daemon.init_trade_db") as mock_init:
            from backend.workers.daemon import start_daemon

            start_daemon()
            assert mock_init.called
