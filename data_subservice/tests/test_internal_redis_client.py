"""redis_client 单元测试 (RedisAsyncBatchWriter + LocalL1Cache, 全 mock 不连真 Redis)"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice._internal.redis_client import (
    LocalL1Cache,
    RedisAsyncBatchWriter,
)


@pytest.fixture
def mock_redis():
    client = MagicMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    client.hgetall = AsyncMock(return_value={})
    client.pipeline = MagicMock()
    return client


class TestRedisAsyncBatchWriter:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis, batch_size=2, flush_interval=0.05)
        w.start()
        assert w._task is not None and not w._task.done()
        await w.stop()

    @pytest.mark.asyncio
    async def test_flush_batch_empty_noop(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis)
        await w._flush_batch([])  # 不应调用 pipeline
        mock_redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_batch_writes_pipeline(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis)
        fake_pipe = AsyncMock()
        fake_pipe.__aenter__ = AsyncMock(return_value=fake_pipe)
        fake_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline.return_value = fake_pipe
        await w._flush_batch([("set", "k", "v", 10)])
        fake_pipe.set.assert_called_once_with("k", "v", ex=10)
        fake_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_batch_handles_exception(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis)
        fake_pipe = AsyncMock()
        fake_pipe.__aenter__ = AsyncMock(return_value=fake_pipe)
        fake_pipe.__aexit__ = AsyncMock(return_value=False)
        fake_pipe.set = MagicMock()
        fake_pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))
        mock_redis.pipeline.return_value = fake_pipe
        # 不应抛异常
        await w._flush_batch([("set", "k", "v", None)])

    @pytest.mark.asyncio
    async def test_put_and_flush_all(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis, batch_size=10, flush_interval=0.05)
        w.put_set_nowait("a", "1")
        w.put_set_nowait("b", "2")
        fake_pipe = AsyncMock()
        fake_pipe.__aenter__ = AsyncMock(return_value=fake_pipe)
        fake_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline.return_value = fake_pipe
        await w._flush_all()
        assert fake_pipe.set.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis)
        ok = await w.stop()
        assert ok is True

    @pytest.mark.asyncio
    async def test_worker_drains_on_cancel(self, mock_redis):
        w = RedisAsyncBatchWriter(mock_redis, batch_size=10, flush_interval=0.05)
        w.put_set_nowait("x", "9", 5)
        w.start()
        await asyncio.sleep(0.1)
        fake_pipe = AsyncMock()
        fake_pipe.__aenter__ = AsyncMock(return_value=fake_pipe)
        fake_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline.return_value = fake_pipe
        ok = await w.stop(timeout_s=2)
        assert ok is True


class TestLocalL1Cache:
    @pytest.mark.asyncio
    async def test_get_miss_then_cache(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        mock_redis.get.return_value = "remote"
        val = await cache.get("k1")
        assert val == "remote"
        assert "k1" in cache._cache

    @pytest.mark.asyncio
    async def test_get_hit_local(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        cache._cache["k2"] = ("local", float("inf"))
        val = await cache.get("k2")
        assert val == "local"
        mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_expired_refetches(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        cache._cache["k3"] = ("stale", 0)  # 已过期
        mock_redis.get.return_value = "fresh"
        val = await cache.get("k3")
        assert val == "fresh"

    @pytest.mark.asyncio
    async def test_get_none_not_cached(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        mock_redis.get.return_value = None
        val = await cache.get("k4")
        assert val is None
        assert "k4" not in cache._cache

    @pytest.mark.asyncio
    async def test_set_writes_both_layers(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        await cache.set("k5", "v5", ex=30)
        mock_redis.set.assert_awaited_once_with("k5", "v5", ex=30)
        assert cache._cache["k5"][0] == "v5"

    @pytest.mark.asyncio
    async def test_set_capacity_circuit_breaker(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=2)
        cache._cache["a"] = ("1", float("inf"))
        cache._cache["b"] = ("2", float("inf"))
        await cache.set("c", "3")
        # 超过 max_size -> 清空
        assert "a" not in cache._cache and "b" not in cache._cache
        assert "c" in cache._cache

    def test_invalidate(self, mock_redis):
        cache = LocalL1Cache(mock_redis, default_ttl=10, max_size=100)
        cache._cache["k6"] = ("v", float("inf"))
        cache.invalidate("k6")
        assert "k6" not in cache._cache
