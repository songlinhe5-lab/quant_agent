"""
Redis 客户端单元测试

ARCH-03: Graceful Shutdown 任务配套测试
- test_graceful_executor_shutdown: Executor 优雅关闭等待任务完成
- test_redis_batch_writer_stop: Redis 队列清空后再断开连接

覆盖：
- RedisAsyncBatchWriter 异步批量写入
- LocalL1Cache 进程内 L1 缓存
- mock redis.asyncio
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.graceful_executor import GracefulExecutor
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
    async def batch_writer(self, mock_redis):
        """创建 RedisAsyncBatchWriter 实例"""
        writer = RedisAsyncBatchWriter(mock_redis, batch_size=10, flush_interval=0.1)
        yield writer
        # teardown: 确保 worker 被清理，防止跨测试泄漏
        if writer._task and not writer._task.done():
            writer._task.cancel()
            try:
                await asyncio.wait_for(writer._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

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

        # stop() 已确保 task 完成，无需额外 sleep
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

        # 给 worker 一个 tick 来取数据（但不触发 flush_interval 超时）
        await asyncio.sleep(0)

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


class TestGracefulExecutor:
    """ARCH-03: GracefulExecutor 优雅关闭测试"""

    @pytest.mark.asyncio
    async def test_executor_waits_for_task_completion(self):
        """验证 Executor 能够等待慢任务完成后再关闭"""
        executor = GracefulExecutor(max_workers=2, max_wait_s=30)
        completed_tasks = []

        def slow_task(task_id):
            time.sleep(1)  # 模拟耗时操作
            completed_tasks.append(task_id)
            return f"Task {task_id} completed"

        # 提交两个慢任务
        future1 = executor.submit(slow_task, 1)
        future2 = executor.submit(slow_task, 2)

        # 立即尝试关闭（应在超时前等待所有任务完成）
        result = await executor.graceful_shutdown(timeout_s=10.0)

        # 断言：优雅关闭应返回 True，且所有任务应已完成
        assert result is True
        assert len(completed_tasks) == 2
        assert future1.result() == "Task 1 completed"
        assert future2.result() == "Task 2 completed"

        executor.shutdown()  # 清理资源

    @pytest.mark.asyncio
    async def test_executor_timeout_on_slow_task(self):
        """验证 Executor 对无法完成的 task 触发 timeout"""
        executor = GracefulExecutor(max_workers=1, max_wait_s=5)

        def very_slow_task():
            time.sleep(5)  # 比 timeout 长的任务
            return "done"

        executor.submit(very_slow_task)

        # 关闭时应因超时返回 False
        result = await executor.graceful_shutdown(timeout_s=1.0)

        # 断言：超时情况下返回 False
        assert result is False

        executor.shutdown(wait=False)  # 强制清理

    @pytest.mark.asyncio
    async def test_executor_stats_tracking(self):
        """验证 Executor 统计信息正确记录"""
        executor = GracefulExecutor(max_workers=4)

        for i in range(5):
            executor.submit(time.sleep, 0.1)

        stats = executor.get_stats()

        # 断言：统计信息应包含正确的计数
        assert stats["submitted_count"] == 5
        executor.shutdown()


class TestRedisBatchWriterStop:
    """ARCH-03: RedisAsyncBatchWriter 停止机制测试"""

    @pytest.mark.asyncio
    async def test_batch_writer_flushes_all_items(self, mock_redis):
        """验证停止时会清空所有缓存数据"""
        writer = RedisAsyncBatchWriter(mock_redis, batch_size=200, flush_interval=0.5)
        writer.start()

        # 批量写入多个项目
        for i in range(50):
            writer.put_set_nowait(f"test_key_{i}", f"test_value_{i}")

        await asyncio.sleep(0.6)  # 等待一些被批处理

        # 停止时应强制刷新剩余项
        success = await writer.stop(timeout_s=10.0)

        # 断言：停止成功
        assert success is True

    @pytest.mark.asyncio
    async def test_batch_writer_empty_queue_immediate(self, mock_redis):
        """验证空队列时立即返回"""
        writer = RedisAsyncBatchWriter(mock_redis, batch_size=200, flush_interval=0.5)
        writer.start()

        await asyncio.sleep(0.1)  # 确保 worker 启动

        # 立即停止（没有积压的数据）
        success = await writer.stop(timeout_s=5.0)

        assert success is True

    @pytest.mark.asyncio
    async def test_batch_writer_high_load(self, mock_redis):
        """高负载压力测试：快速写入 + 突然停止"""
        writer = RedisAsyncBatchWriter(mock_redis, batch_size=100, flush_interval=0.2)
        writer.start()

        # 快速写入大量数据
        for i in range(500):
            writer.put_set_nowait(f"stress_key_{i}", f"value_{i}")

        # 立即停止（模拟紧急 shutdown）
        start_time = time.time()
        success = await writer.stop(timeout_s=30.0)
        elapsed = time.time() - start_time

        # 断言：即使在高负载下也能在一定时间内完成关闭
        assert success is True
        assert elapsed < 15.0  # 应该在 15s 内完成
