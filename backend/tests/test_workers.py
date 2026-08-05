"""Workers 模块单元测试：quote_publisher（daemon.py 已移除）"""

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

            async def fake_fetch(action, **kwargs):
                if action == "QUOTE":
                    return {"last_price": 150.0, "change_pct": "1.5%", "volume_str": "10M"}
                return {"bids": [{"price": 149.5, "size": 100}], "asks": [{"price": 150.5, "size": 200}]}

            with patch(
                "backend.services.datasource.router.data_source_router.fetch_futu",
                new=AsyncMock(side_effect=fake_fetch),
            ):
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
            with patch(
                "backend.services.datasource.router.data_source_router.fetch_futu",
                new=AsyncMock(side_effect=RuntimeError("连接失败")),
            ):
                with pytest.raises(ConnectionError):
                    await pub._fetch_futu_data("US.AAPL")

    async def test_poll_and_publish_success_publishes_to_redis(self):
        """测试成功拉取后发布 Protobuf 到 Redis"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()

            async def fake_fetch(action, **kwargs):
                if action == "QUOTE":
                    return {"last_price": 150.0, "change_pct": "1.5%", "volume_str": "10M"}
                return {"bids": [{"price": 149.5, "size": 100}], "asks": []}

            with patch(
                "backend.services.datasource.router.data_source_router.fetch_futu",
                new=AsyncMock(side_effect=fake_fetch),
            ):
                await pub.poll_and_publish("US.AAPL")
                assert pub.redis.hset.called
                assert pub.redis.publish.called

    async def test_poll_and_publish_futu_failure_injects_no_mock_data(self):
        """测试 Futu 拉取失败后零幻觉: 不向行情总线注入任何 Mock 假数据"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()
            with patch.object(pub, "_fetch_futu_data", side_effect=asyncio.TimeoutError()):
                await pub.poll_and_publish("US.AAPL")
                # 零幻觉红线: 失败时必须直接跳过发布, 绝不推送假价格 100.00
                assert not pub.redis.hset.called
                assert not pub.redis.publish.called

    async def test_run_daemon_cancellation_exits_gracefully(self):
        """测试 Daemon 收到取消信号后优雅退出"""
        with patch("backend.workers.quote_publisher.redis.from_url"):
            from backend.workers.quote_publisher import QuotePublisher

            pub = QuotePublisher()
            pub.redis = AsyncMock()

            async def fake_fetch(action, **kwargs):
                if action == "QUOTE":
                    return {"last_price": 150.0}
                return {}

            with patch(
                "backend.services.datasource.router.data_source_router.fetch_futu",
                new=AsyncMock(side_effect=fake_fetch),
            ):
                task = asyncio.create_task(pub.run_daemon(["US.AAPL"], interval=0.01))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                assert pub.is_running is False
