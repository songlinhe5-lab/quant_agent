"""Graceful Executor - 支持异步优雅关闭的线程池

ARCH-03: Graceful Shutdown 任务核心组件
（复制自 backend.core.graceful_executor，物理解耦，零 backend 依赖）
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional


class GracefulExecutor(ThreadPoolExecutor):
    """支持异步优雅关闭的线程池封装"""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        thread_name_prefix: Optional[str] = None,
        max_wait_s: int = 30,
        **kwargs,
    ):
        super().__init__(max_workers=max_workers, thread_name_prefix=thread_name_prefix, **kwargs)

        self.max_wait_s = max_wait_s

        self._submitted_count = 0
        self._completed_count = 0
        self._active_tasks = 0

        print(f"✅ GracefulExecutor 初始化 (max_workers={max_workers}, max_wait_s={max_wait_s})")

    def submit(self, fn: Callable, *args, **kwargs) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        async_future = loop.create_future()

        def wrapped_fn():
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                self._update_stats(completed=True)
                if not async_future.done():
                    loop.call_soon_threadsafe(async_future.set_exception, e)
            else:
                self._update_stats(completed=True)
                if not async_future.done():
                    loop.call_soon_threadsafe(async_future.set_result, result)

        super().submit(wrapped_fn)
        self._update_stats(submitted=True)
        return async_future

    def _update_stats(self, submitted: bool = False, completed: bool = False):
        if submitted:
            self._submitted_count += 1
            self._active_tasks += 1
        if completed:
            self._completed_count += 1
            self._active_tasks -= 1

    def get_stats(self) -> dict:
        return {
            "submitted_count": self._submitted_count,
            "completed_count": self._completed_count,
            "active_tasks": self._active_tasks,
            "max_wait_s": self.max_wait_s,
        }

    def stats(self) -> dict:
        return self.get_stats()

    async def graceful_shutdown(self, timeout_s: Optional[float] = None):
        timeout = timeout_s or self.max_wait_s
        start_time = time.time()
        loop = asyncio.get_running_loop()

        try:
            if hasattr(self, "_threads"):

                def do_shutdown():
                    ThreadPoolExecutor.shutdown(self, wait=True)

                await asyncio.wait_for(loop.run_in_executor(None, do_shutdown), timeout=timeout)
                return True
            else:
                self.shutdown(wait=True)
                return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False


_global_graceful_executor: Optional[GracefulExecutor] = None


def get_global_executor(max_workers: int = 64, max_wait_s: int = 30) -> GracefulExecutor:
    global _global_graceful_executor
    if _global_graceful_executor is None:
        _global_graceful_executor = GracefulExecutor(max_workers=max_workers, max_wait_s=max_wait_s)
    return _global_graceful_executor


async def shutdown_global_executor():
    global _global_graceful_executor
    if _global_graceful_executor:
        success = await _global_graceful_executor.graceful_shutdown()
        if not success:
            print("⚠️ [GlobalExecutor] 关闭未完全成功")
        _global_graceful_executor = None
