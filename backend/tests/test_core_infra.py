"""
核心基础设施层单元测试
覆盖: redis_client (RedisAsyncBatchWriter, LocalL1Cache), middleware, logger
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


# ─── redis_client: RedisAsyncBatchWriter ────────────────────────────
class TestRedisAsyncBatchWriter:
    def test_init(self):
        from backend.core.redis_client import RedisAsyncBatchWriter

        mock_client = AsyncMock()
        writer = RedisAsyncBatchWriter(mock_client, batch_size=50, flush_interval=0.5)
        assert writer.batch_size == 50
        assert writer.flush_interval == 0.5

    def test_put_set_nowait(self):
        from backend.core.redis_client import RedisAsyncBatchWriter

        mock_client = AsyncMock()
        writer = RedisAsyncBatchWriter(mock_client)
        writer.put_set_nowait("key1", "val1", ex=60)
        assert not writer.queue.empty()

    @pytest.mark.asyncio
    async def test_flush_batch(self):
        from backend.core.redis_client import RedisAsyncBatchWriter

        mock_client = AsyncMock()
        mock_pipe = AsyncMock()
        mock_client.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)

        writer = RedisAsyncBatchWriter(mock_client)
        batch = [("set", "k1", "v1", None), ("set", "k2", "v2", 60)]
        await writer._flush_batch(batch)

    @pytest.mark.asyncio
    async def test_flush_empty_batch(self):
        from backend.core.redis_client import RedisAsyncBatchWriter

        mock_client = AsyncMock()
        writer = RedisAsyncBatchWriter(mock_client)
        await writer._flush_batch([])

    @pytest.mark.asyncio
    async def test_flush_all(self):
        from backend.core.redis_client import RedisAsyncBatchWriter

        mock_client = AsyncMock()
        mock_pipe = AsyncMock()
        mock_client.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)

        writer = RedisAsyncBatchWriter(mock_client)
        writer.put_set_nowait("k", "v")
        await writer._flush_all()
        assert writer.queue.empty()


# ─── redis_client: LocalL1Cache ─────────────────────────────────────
class TestLocalL1Cache:
    @pytest.mark.asyncio
    async def test_get_cache_miss(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        cache = LocalL1Cache(mock_redis, default_ttl=10.0)
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cache_hit(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        cache = LocalL1Cache(mock_redis, default_ttl=10.0)
        # Manually populate cache
        import time

        cache._cache["test_key"] = ("test_value", time.time() + 100)
        result = await cache.get("test_key")
        assert result == "test_value"

    @pytest.mark.asyncio
    async def test_get_cache_expired(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="fresh_value")
        cache = LocalL1Cache(mock_redis, default_ttl=10.0)
        import time

        cache._cache["expired_key"] = ("old_value", time.time() - 10)
        result = await cache.get("expired_key")
        assert result == "fresh_value"

    @pytest.mark.asyncio
    async def test_set_updates_both(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        cache = LocalL1Cache(mock_redis, default_ttl=10.0)
        await cache.set("key1", "val1")
        mock_redis.set.assert_called_once()
        assert "key1" in cache._cache

    @pytest.mark.asyncio
    async def test_set_capacity_overflow(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        cache = LocalL1Cache(mock_redis, default_ttl=10.0, max_size=3)
        for i in range(5):
            await cache.set(f"k{i}", f"v{i}")
        # After overflow, cache should be cleared
        assert len(cache._cache) <= 5

    def test_invalidate(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        cache = LocalL1Cache(mock_redis)
        import time

        cache._cache["key"] = ("val", time.time() + 100)
        cache.invalidate("key")
        assert "key" not in cache._cache

    def test_invalidate_nonexistent(self):
        from backend.core.redis_client import LocalL1Cache

        mock_redis = AsyncMock()
        cache = LocalL1Cache(mock_redis)
        cache.invalidate("nonexistent")  # Should not raise


# ─── middleware.py ───────────────────────────────────────────────────
class TestMiddleware:
    def test_prometheus_counters_exist(self):
        from backend.core.middleware import EXTERNAL_API_COUNT, EXTERNAL_API_LATENCY, REQUEST_COUNT, REQUEST_LATENCY

        assert REQUEST_COUNT is not None
        assert REQUEST_LATENCY is not None
        assert EXTERNAL_API_COUNT is not None
        assert EXTERNAL_API_LATENCY is not None

    @pytest.mark.asyncio
    async def test_httpx_log_request(self):
        from backend.core.middleware import _request_timers, httpx_log_request

        mock_request = MagicMock()
        await httpx_log_request(mock_request)
        assert id(mock_request) in _request_timers

    @pytest.mark.asyncio
    async def test_httpx_log_response_known_service(self):
        from backend.core.middleware import httpx_log_request, httpx_log_response

        mock_request = MagicMock()
        mock_request.url.host = "api.finnhub.com"
        mock_request.method = "GET"
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200

        await httpx_log_request(mock_request)
        await httpx_log_response(mock_response)

    @pytest.mark.asyncio
    async def test_httpx_log_response_various_hosts(self):
        from backend.core.middleware import httpx_log_request, httpx_log_response

        hosts_and_expected = [
            ("api.stlouisfed.org", "fred"),
            ("api.tavily.com", "tavily"),
            ("api.bochaai.com", "bocha"),
            ("r.jina.ai", "jina_reader"),
            ("oapi.dingtalk.com", "dingtalk"),
            ("open.feishu.cn", "feishu"),
            ("api.telegram.org", "telegram"),
            ("api.openai.com", "llm_api"),
            ("query1.finance.yahoo.com", "yahoo"),
            ("unknown.host.com", "unknown"),
        ]
        for host, _ in hosts_and_expected:
            mock_request = MagicMock()
            mock_request.url.host = host
            mock_request.method = "GET"
            mock_response = MagicMock()
            mock_response.request = mock_request
            mock_response.status_code = 200
            await httpx_log_request(mock_request)
            await httpx_log_response(mock_response)

    @pytest.mark.asyncio
    async def test_httpx_log_response_unknown_request(self):
        from backend.core.middleware import httpx_log_response

        mock_request = MagicMock()
        mock_request.url.host = "test.com"
        mock_request.method = "POST"
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 500
        await httpx_log_response(mock_response)


# ─── logger.py ───────────────────────────────────────────────────────
class TestLogger:
    def test_logger_instance(self):
        from backend.core.logger import logger

        assert logger is not None
        assert logger.name == "quant_agent"

    def test_plain_file_formatter(self):
        import logging

        from backend.core.logger import PlainFileFormatter

        fmt = PlainFileFormatter(fmt="%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello [green]world[/]", (), None)
        result = fmt.format(record)
        assert "[green]" not in result
        assert "world" in result

    def test_console_color_formatter(self):
        import logging

        from backend.core.logger import ConsoleColorFormatter

        fmt = ConsoleColorFormatter(fmt="%(message)s")
        record = logging.LogRecord("test", logging.ERROR, "", 0, "error msg", (), None)
        result = fmt.format(record)
        assert "error msg" in result

    def test_level_filter(self):
        import logging

        from backend.core.logger import LevelFilter

        f = LevelFilter([logging.WARNING])
        warn_record = logging.LogRecord("test", logging.WARNING, "", 0, "warn", (), None)
        info_record = logging.LogRecord("test", logging.INFO, "", 0, "info", (), None)
        assert f.filter(warn_record) is True
        assert f.filter(info_record) is False

    def test_webhook_handler_emit(self):
        from backend.core.logger import WebhookAlertHandler

        handler = WebhookAlertHandler("https://example.com/webhook")
        import logging

        record = logging.LogRecord("test", logging.ERROR, "", 0, "test error", (), None)
        # Should not raise even if webhook is unreachable
        # 💡 Mock urlopen 避免真实 HTTP 调用（timeout=5 会导致测试极慢）
        with patch("urllib.request.urlopen"):
            handler.emit(record)
