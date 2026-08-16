"""GracefulExecutor 单元测试 (线程池 + 优雅关闭)"""

import asyncio

import pytest

from data_subservice._internal.graceful_executor import (
    GracefulExecutor,
    get_global_executor,
    shutdown_global_executor,
)


class TestGracefulExecutor:
    def test_init_stats(self):
        ex = GracefulExecutor(max_workers=4, max_wait_s=10)
        stats = ex.get_stats()
        assert stats["submitted_count"] == 0
        assert stats["completed_count"] == 0
        assert stats["active_tasks"] == 0
        assert stats["max_wait_s"] == 10
        assert ex.stats() == stats

    @pytest.mark.asyncio
    async def test_submit_sync_result(self):
        ex = GracefulExecutor(max_workers=2)
        fut = ex.submit(lambda: 21 * 2)
        assert await asyncio.wait_for(fut, timeout=5) == 42
        stats = ex.get_stats()
        assert stats["submitted_count"] == 1
        assert stats["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_submit_exception_propagates(self):
        ex = GracefulExecutor(max_workers=2)

        def boom():
            raise RuntimeError("kaboom")

        fut = ex.submit(boom)
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(fut, timeout=5)
        assert ex.get_stats()["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_submits(self):
        ex = GracefulExecutor(max_workers=4)
        futs = [ex.submit(lambda i=i: i * i) for i in range(10)]
        results = await asyncio.gather(*[asyncio.wait_for(f, timeout=5) for f in futs])
        assert sorted(results) == [i * i for i in range(10)]
        assert ex.get_stats()["submitted_count"] == 10
        assert ex.get_stats()["completed_count"] == 10

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self):
        ex = GracefulExecutor(max_workers=2)
        ex.submit(lambda: 1)
        ok = await ex.graceful_shutdown(timeout_s=5)
        assert ok is True

    @pytest.mark.asyncio
    async def test_global_executor_singleton(self):
        a = get_global_executor()
        b = get_global_executor()
        assert a is b
        await shutdown_global_executor()
