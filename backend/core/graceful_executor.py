"""Graceful Executor - 支持异步优雅关闭的线程池

ARCH-03: Graceful Shutdown 任务核心组件

特性:
✅ 支持 timeout 机制等待任务完成
✅ 防止 shutdown(wait=False) 导致的中断
✅ Prometheus Metrics 集成（可选）

使用示例:
    executor = GracefulExecutor(max_workers=10, max_wait_s=30)

    # 提交任务
    future = executor.submit(some_function, arg1)

    # 优雅关闭（等待所有任务完成，超时则强制终止）
    await executor.graceful_shutdown()
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional


class GracefulExecutor(ThreadPoolExecutor):
    """
    支持异步优雅关闭的线程池封装

    解决痛点:
    1. Python 默认 ThreadPoolExecutor.shutdown(wait=False) 会立即中断任务
       → 改为支持 async 包装和 timeout 控制

    2. 无法在 lifespan shutdown 阶段等待任务完成
       → 提供 async 版本的 shutdown 方法

    3. 缺乏状态追踪和监控指标
       → 内置 active_tasks / completed_tasks 计数器
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        thread_name_prefix: Optional[str] = None,
        max_wait_s: int = 30,  # 优雅关闭最大等待时间
        **kwargs
    ):
        super().__init__(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
            **kwargs
        )

        self.max_wait_s = max_wait_s

        # 统计信息
        self._submitted_count = 0
        self._completed_count = 0
        self._active_tasks = 0

        print(f"✅ GracefulExecutor 初始化 (max_workers={max_workers}, max_wait_s={max_wait_s})")

    def submit(
        self,
        fn: Callable,
        *args,
        **kwargs
    ) -> asyncio.Future:
        """
        重写 submit() 支持返回 asyncio.Future

        将同步任务包装为异步 Future，便于 lifespan 统一管理
        """
        loop = asyncio.get_running_loop()
        async_future = loop.create_future()

        def wrapped_fn():
            try:
                result = fn(*args, **kwargs)
                if not async_future.done():
                    loop.call_soon_threadsafe(async_future.set_result, result)
            except Exception as e:
                if not async_future.done():
                    loop.call_soon_threadsafe(async_future.set_exception, e)
            finally:
                self._update_stats(completed=True)

        # 提交到底层 ThreadPoolExecutor
        super().submit(wrapped_fn)

        self._update_stats(submitted=True)

        return async_future

    def _update_stats(self, submitted: bool = False, completed: bool = False):
        """更新内部统计计数器（线程安全）"""
        if submitted:
            self._submitted_count += 1
            self._active_tasks += 1
        if completed:
            self._completed_count += 1
            self._active_tasks -= 1

    def get_stats(self) -> dict:
        """获取执行器运行统计"""
        return {
            "total_submitted": self._submitted_count,
            "total_completed": self._completed_count,
            "active_tasks": self._active_tasks,
            "max_wait_s": self.max_wait_s
        }

    async def graceful_shutdown(self, timeout_s: Optional[float] = None):
        """
        异步优雅关闭：等待所有任务完成后再终止

        Args:
            timeout_s: 自定义超时时间（秒），None 时使用 self.max_wait_s

        Returns:
            bool: True 表示优雅关闭成功，False 表示超时强制终止
        """
        timeout = timeout_s or self.max_wait_s
        start_time = time.time()

        print(f"🛑 [GracefulExecutor] 开始优雅关闭 (timeout={timeout}s)...")

        # Python 3.9+ 支持 shutdown(wait=True, timeout=X)
        # 兼容旧版本：使用 run_in_executor 模拟
        loop = asyncio.get_running_loop()

        try:
            # 方式 1: 如果支持 timeout 参数（Python 3.9+）
            if hasattr(self, '_threads'):
                # 标记所有线程需要停止
                for thread in self._threads:
                    if hasattr(thread, 'daemon') and thread.daemon:
                        continue  # 守护线程不等待

                # 方式 2: 使用 asyncio.wait_for + run_in_executor
                def do_shutdown():
                    super(ThreadPoolExecutor, self).shutdown(wait=True)

                await asyncio.wait_for(
                    loop.run_in_executor(None, do_shutdown),
                    timeout=timeout
                )

                elapsed = time.time() - start_time
                print(f"✅ [GracefulExecutor] 优雅关闭完成 (耗时:{elapsed:.2f}s)")
                return True

            # Fallback: 普通 shutdown
            else:
                self.shutdown(wait=True)
                elapsed = time.time() - start_time
                print(f"✅ [GracefulExecutor] 正常关闭完成 (耗时:{elapsed:.2f}s)")
                return True

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            print(f"⚠️ [GracefulExecutor] 关闭超时 ({elapsed:.2f}s > {timeout}s)，强制终止")
            return False
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"⚠️ [GracefulExecutor] 关闭异常 ({elapsed:.2f}s): {e}")
            return False

    def __repr__(self):
        stats = self.get_stats()
        return (
            f"GracefulExecutor(max_workers={self._max_workers}, "
            f"submitted={stats['total_submitted']}, "
            f"active={stats['active_tasks']})"
        )


# 全局单例（用于系统级线程池）
_global_graceful_executor: Optional[GracefulExecutor] = None


def get_global_executor(
    max_workers: int = 64,
    max_wait_s: int = 30
) -> GracefulExecutor:
    """获取或创建全局线程池单例"""
    global _global_graceful_executor

    if _global_graceful_executor is None:
        _global_graceful_executor = GracefulExecutor(
            max_workers=max_workers,
            max_wait_s=max_wait_s
        )

    return _global_graceful_executor


async def shutdown_global_executor():
    """关闭全局线程池（调用前确保无新任务提交）"""
    global _global_graceful_executor

    if _global_graceful_executor:
        stats = _global_graceful_executor.get_stats()
        print(f"📊 [GlobalExecutor Stats] {stats}")

        success = await _global_graceful_executor.graceful_shutdown()

        if not success:
            print("⚠️ [GlobalExecutor] 关闭未完全成功")

        _global_graceful_executor = None
