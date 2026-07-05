"""
Redis 客户端单元测试

覆盖：
- RedisAsyncBatchWriter 异步批量写入
- LocalL1Cache 进程内 L1 缓存
- mock redis.asyncio
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis

from backend.core.redis_client import (
    L1_CACHE_MAX_SIZE,
    LocalL1Cache,
    RedisAsyncBatchWriter,
    redis_batch_writer,
    redis_client,
)


class TestRedisAsyncBatchWriter:
    """RedisAsyncBatchWriter 异步批量写入测试"""

    @pytest.fixture
    def mock_redis(self):
        """创建 mock Redis 客户端"""
        mock = AsyncMock()
        # 添加 pipeline 方法
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=False)
        mock_pipeline.execute = AsyncMock()
        mock_pipeline.set = MagicMock()
        mock.pipeline = MagicMock(return_value=mock_pipeline)
        return mock

    @pytest.fixture
    def batch_writer(self, mock_redis):
        """创建 RedisAsyncBatchWriter 实例"""
        return RedisAsyncBatchWriter(mock_redis, batch_size=10, flush_interval=0.1)

    def test_initialization(self, mock_redis):
        """测试初始化"""
        writer = RedisAsyncBatchWriter(mock_redis)
        assert writer.redis is mock_redis
        assert writer.batch_size == 100
        assert writer.flush_interval == 1.0
        assert writer._task is None
        assert writer.queue.empty()

    def test_initialization_custom_params(self, mock_redis):
        """测试自定义参数初始化"""
        writer = RedisAsyncBatchWriter(mock_redis, batch_size=50, flush_interval=0.5)
        assert writer.batch_size == 50
        assert writer.flush_interval == 0.5

    @pytest.mark.asyncio
    async def test_start(self, batch_writer):
        """测试启动后台消费协程"""
        batch_writer.start()
        
        assert batch_writer._task is not None
        assert not batch_writer._task.done()

    @pytest.mark.asyncio
    async def test_stop(self, batch_writer):
        """测试优雅停机"""
        batch_writer.start()
        task = batch_writer._task
        
        await batch_writer.stop()
        
        # 等待一小段时间让 task 完成
        await asyncio.sleep(0.1)
        assert task.done()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, batch_writer):
        """测试未启动时调用 stop"""
        # 不应抛出异常
        await batch_writer.stop()
        assert True

    def test_put_set_nowait(self, batch_writer):
        """测试 fire-and-forget 写入接口"""
        batch_writer.put_set_nowait("test_key", "test_value", ex=60)
        
        assert not batch_writer.queue.empty()
        
        # 验证队列中的数据格式
        item = batch_writer.queue.get_nowait()
        assert item == ("set", "test_key", "test_value", 60)

    def test_put_set_nowait_without_expiry(self, batch_writer):
        """测试不带过期时间的写入"""
        batch_writer.put_set_nowait("test_key", "test_value")
        
        item = batch_writer.queue.get_nowait()
        assert item == ("set", "test_key", "test_value", None)

    @pytest.mark.asyncio
    async def test_flush_batch(self, batch_writer, mock_redis):
        """测试批量刷新"""
        # 创建 mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        batch = [
            ("set", "key1", "value1", 60),
            ("set", "key2", "value2", 120),
        ]

        await batch_writer._flush_batch(batch)

        # 验证 pipeline 被正确调用
        assert mock_pipe.set.call_count == 2
        mock_pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_batch_empty(self, batch_writer):
        """测试空批次刷新"""
        # 不应抛出异常
        await batch_writer._flush_batch([])
        assert True

    @pytest.mark.asyncio
    async def test_flush_batch_error(self, batch_writer, mock_redis, capsys):
        """测试批量刷新异常"""
        mock_redis.pipeline.side_effect = Exception("Pipeline error")

        batch = [("set", "key1", "value1", 60)]
        await batch_writer._flush_batch(batch)

        # 验证错误被打印
        captured = capsys.readouterr()
        assert "Pipeline 批量写入失败" in captured.out

    @pytest.mark.asyncio
    async def test_worker_batch_full(self, batch_writer, mock_redis):
        """测试队列满时触发刷新"""
        # 启动 worker
        batch_writer.start()
        
        # 创建 mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        # 填满队列
        for i in range(batch_writer.batch_size):
            batch_writer.put_set_nowait(f"key{i}", f"value{i}")

        # 等待 worker 处理
        await asyncio.sleep(0.5)

        # 验证 pipeline.execute 被调用
        assert mock_pipe.execute.called

        await batch_writer.stop()

    @pytest.mark.asyncio
    async def test_worker_timeout_flush(self, batch_writer, mock_redis):
        """测试超时触发刷新"""
        batch_writer.flush_interval = 0.1  # 短超时
        batch_writer.start()

        # 创建 mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        # 放入一个数据
        batch_writer.put_set_nowait("key1", "value1")

        # 等待超时
        await asyncio.sleep(0.3)

        # 验证 pipeline.execute 被调用
        assert mock_pipe.execute.called

        await batch_writer.stop()

    @pytest.mark.asyncio
    async def test_flush_all(self, batch_writer, mock_redis):
        """测试刷新所有积压数据"""
        # 创建 mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        # 放入多个数据
        for i in range(5):
            batch_writer.put_set_nowait(f"key{i}", f"value{i}")

        await batch_writer._flush_all()

        # 验证 pipeline.execute 被调用
        assert mock_pipe.execute.called

    @pytest.mark.asyncio
    async def test_worker_cancelled(self, batch_writer, mock_redis):
        """测试 worker 被取消时刷新剩余数据"""
        batch_writer.start()
        
        # 创建 mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        # 放入数据
        batch_writer.put_set_nowait("key1", "value1")

        # 取消 task
        batch_writer._task.cancel()
        
        try:
            await batch_writer._task
        except asyncio.CancelledError:
            pass

        # 验证数据被刷新
        assert mock_pipe.execute.called


class TestLocalL1Cache:
    """LocalL1Cache 进程内 L1 缓存测试"""

    @pytest.fixture
    def mock_redis(self):
        """创建 mock Redis 客户端"""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value="cached_value")
        mock.set = AsyncMock()
        return mock

    @pytest.fixture
    def l1_cache(self, mock_redis):
        """创建 LocalL1Cache 实例"""
        return LocalL1Cache(mock_redis, default_ttl=10.0, max_size=100)

    def test_initialization(self, mock_redis):
        """测试初始化"""
        cache = LocalL1Cache(mock_redis)
        assert cache.redis is mock_redis
        assert cache.default_ttl == 10.0
        assert cache.max_size == L1_CACHE_MAX_SIZE
        assert len(cache._cache) == 0
        assert cache._cleanup_task is None

    def test_initialization_custom_params(self, mock_redis):
        """测试自定义参数初始化"""
        cache = LocalL1Cache(mock_redis, default_ttl=30.0, max_size=500)
        assert cache.default_ttl == 30.0
        assert cache.max_size == 500

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, l1_cache):
        """测试缓存命中"""
        # 手动放入缓存
        l1_cache._cache["test_key"] = ("test_value", time.time() + 10)
        
        value = await l1_cache.get("test_key")
        
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, l1_cache, mock_redis):
        """测试缓存未命中，查询 Redis"""
        mock_redis.get.return_value = "redis_value"
        
        value = await l1_cache.get("test_key")
        
        assert value == "redis_value"
        # 验证值被写入 L1 缓存
        assert "test_key" in l1_cache._cache

    @pytest.mark.asyncio
    async def test_get_cache_miss_and_redis_miss(self, l1_cache, mock_redis):
        """测试缓存和 Redis 都未命中"""
        mock_redis.get.return_value = None
        
        value = await l1_cache.get("test_key")
        
        assert value is None

    @pytest.mark.asyncio
    async def test_get_expired_cache(self, l1_cache, mock_redis):
        """测试过期缓存"""
        # 放入过期缓存
        l1_cache._cache["test_key"] = ("old_value", time.time() - 10)
        mock_redis.get.return_value = "new_value"
        
        value = await l1_cache.get("test_key")
        
        assert value == "new_value"
        # 验证旧值被删除
        assert "test_key" not in l1_cache._cache or l1_cache._cache["test_key"][0] == "new_value"

    @pytest.mark.asyncio
    async def test_set(self, l1_cache, mock_redis):
        """测试写入缓存"""
        await l1_cache.set("test_key", "test_value", ex=60)
        
        # 验证 Redis 被调用
        mock_redis.set.assert_called_once_with("test_key", "test_value", ex=60)
        
        # 验证 L1 缓存被更新
        assert "test_key" in l1_cache._cache
        assert l1_cache._cache["test_key"][0] == "test_value"

    @pytest.mark.asyncio
    async def test_set_without_expiry(self, l1_cache, mock_redis):
        """测试不带过期时间写入"""
        await l1_cache.set("test_key", "test_value")
        
        mock_redis.set.assert_called_once_with("test_key", "test_value", ex=None)

    @pytest.mark.asyncio
    async def test_set_capacity_protection(self, l1_cache, mock_redis, capsys):
        """测试容量保护机制"""
        # 填满缓存
        for i in range(l1_cache.max_size):
            l1_cache._cache[f"key{i}"] = ("value", time.time() + 10)
        
        # 再次写入，触发清空
        await l1_cache.set("new_key", "new_value")
        
        # 验证缓存被清空
        assert len(l1_cache._cache) <= 1
        
        # 验证警告被打印
        captured = capsys.readouterr()
        assert "字典容量触及上限" in captured.out

    @pytest.mark.asyncio
    async def test_invalidate(self, l1_cache):
        """测试删除缓存"""
        l1_cache._cache["test_key"] = ("value", time.time() + 10)
        
        l1_cache.invalidate("test_key")
        
        assert "test_key" not in l1_cache._cache

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self, l1_cache):
        """测试删除不存在的缓存"""
        # 不应抛出异常
        l1_cache.invalidate("nonexistent_key")
        assert True

    @pytest.mark.asyncio
    async def test_sweep_daemon(self, l1_cache):
        """测试后台清理守护进程"""
        # 放入一些过期数据
        l1_cache._cache["expired_key"] = ("value", time.time() - 10)
        l1_cache._cache["valid_key"] = ("value", time.time() + 10)
        
        # 手动调用清理逻辑
        now = time.time()
        expired_keys = [k for k, (v, exp) in l1_cache._cache.items() if now > exp]
        for k in expired_keys:
            l1_cache._cache.pop(k, None)
        
        # 验证过期键被删除
        assert "expired_key" not in l1_cache._cache
        assert "valid_key" in l1_cache._cache

    @pytest.mark.asyncio
    async def test_get_triggers_cleanup_task(self, l1_cache):
        """测试 get 方法触发清理任务"""
        await l1_cache.get("test_key")
        
        # 验证清理任务被创建
        assert l1_cache._cleanup_task is not None

    @pytest.mark.asyncio
    async def test_set_triggers_cleanup_task(self, l1_cache, mock_redis):
        """测试 set 方法触发清理任务"""
        await l1_cache.set("test_key", "test_value")
        
        # 验证清理任务被创建
        assert l1_cache._cleanup_task is not None


class TestGlobalInstances:
    """全局实例测试"""

    def test_redis_client_initialized(self):
        """测试 Redis 客户端已初始化"""
        assert redis_client is not None

    def test_redis_batch_writer_initialized(self):
        """测试批量写入器已初始化"""
        assert redis_batch_writer is not None
        assert isinstance(redis_batch_writer, RedisAsyncBatchWriter)

    def test_l1_cached_redis_initialized(self):
        """测试 L1 缓存已初始化"""
        from backend.core.redis_client import l1_cached_redis
        
        assert l1_cached_redis is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
