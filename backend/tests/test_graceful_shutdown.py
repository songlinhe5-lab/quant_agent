"""
ARCH-03: Graceful Shutdown 组件测试
覆盖 GracefulExecutor 的优雅关闭语义（等待在途任务 / 超时强制 / 统计 / 幂等）。
不依赖外部 Redis / DB / Futu，可独立运行。
"""

import asyncio
import time

import pytest

from backend.core.graceful_executor import GracefulExecutor


@pytest.mark.asyncio
async def test_executor_waits_for_inflight_task():
    """提交一个短耗时任务，graceful_shutdown 应等待其完成并返回 True。"""
    executor = GracefulExecutor(max_workers=2, max_wait_s=10)

    def slow_task():
        time.sleep(0.3)
        return "done"

    fut = executor.submit(slow_task)
    ok = await executor.graceful_shutdown()
    assert ok is True
    assert fut.result() == "done"


@pytest.mark.asyncio
async def test_executor_forces_termination_on_timeout():
    """任务超出生死线时，graceful_shutdown 应返回 False（不阻塞）。"""
    executor = GracefulExecutor(max_workers=1, max_wait_s=1)

    def very_slow_task():
        time.sleep(3)

    executor.submit(very_slow_task)
    ok = await executor.graceful_shutdown()
    assert ok is False


@pytest.mark.asyncio
async def test_executor_collects_stats():
    """submit 后统计计数应正确递增。"""
    executor = GracefulExecutor(max_workers=2, max_wait_s=5)

    def task():
        return 1

    fut = executor.submit(task)
    await asyncio.wait_for(fut, timeout=5)
    stats = executor.get_stats()
    assert stats["submitted_count"] >= 1
    assert stats["completed_count"] >= 1
    executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_executor_double_shutdown_idempotent():
    """重复调用 graceful_shutdown 不应抛异常。"""
    executor = GracefulExecutor(max_workers=1, max_wait_s=5)
    executor.submit(lambda: 1)
    await executor.graceful_shutdown()
    await executor.graceful_shutdown()  # 应安全返回
