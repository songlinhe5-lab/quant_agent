"""CPU 密集型任务专用进程池 (ARCH-07)。

背景
----
`asyncio.to_thread` 把同步函数丢进默认线程池，但 Python 线程受 GIL 约束：
CPU 密集型任务（回测、网格搜索、蒙特卡洛、批量回测）在子线程里依然无法真正
并行，还会占用默认线程池（默认 32 线程）的容量，挤占那些本应快速返回的
阻塞 SDK/DB 卸载任务，进而拖慢整个网关事件循环。

策略 (见 docs/03 §7.6)
--------------------
- I/O 密集（akshare/futu/yfinance/redis/pg 等同步 SDK、文件读写）：继续用
  `asyncio.to_thread`，这是调用同步库的唯一非阻塞手段，属「正确用法」。
- CPU 密集（指标/回测计算）：必须卸载到独立 `ProcessPoolExecutor`，绕开 GIL
  实现真并行，且不污染默认线程池。

本模块提供 `run_cpu_bound()` 作为 CPU 密集任务的统一入口：
- 自动检测负载是否可 pickle；不可 pickle 的调用（绑定方法、测试 Mock、闭包、
  含锁对象）自动回退 `asyncio.to_thread`，保证既有测试与生产行为不变。
- 进程池初始化或执行异常时同样回退线程池，绝不因进程池故障而让请求失败。
- 默认启用，可用环境变量 ``QUANT_CPU_POOL_ENABLED=0`` 关闭（强制回退线程）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 进程池懒初始化；默认与逻辑核数对齐，避免与默认线程池争抢 CPU。
_cpu_executor: "ProcessPoolExecutor | None" = None
_cpu_pool_enabled = os.getenv("QUANT_CPU_POOL_ENABLED", "1").lower() not in (
    "0",
    "false",
    "no",
)


def _ensure_cpu_executor() -> "ProcessPoolExecutor | None":
    """懒初始化进程池；失败或无可用环境时返回 None（调用方回退线程）。"""
    global _cpu_executor
    if not _cpu_pool_enabled:
        return None
    if _cpu_executor is None:
        try:
            import multiprocessing as mp

            ctx = mp.get_context("fork") if hasattr(mp, "get_context") and os.name != "nt" else None
            _cpu_executor = ProcessPoolExecutor(
                max_workers=os.cpu_count() or 2,
                mp_context=ctx,
            )
        except Exception:  # pragma: no cover - 受限环境退化为线程
            logger.warning(
                "ProcessPoolExecutor init failed; cpu-bound tasks fall back to thread",
                exc_info=True,
            )
            _cpu_executor = None
    return _cpu_executor


def _is_picklable(*parts: Any) -> bool:
    """负载（函数 + 参数）是否可序列化到子进程。"""
    try:
        pickle.dumps(parts)
        return True
    except Exception:
        return False


def _invoke(func: Callable[..., T], args: tuple, kwargs: dict) -> T:
    return func(*args, **kwargs)


async def run_cpu_bound(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """将 CPU 密集型任务卸载到独立进程池。

    不可 pickle 或进程池不可用时自动回退 ``asyncio.to_thread``，行为安全等价。
    """
    if _is_picklable(func, args, kwargs):
        ex = _ensure_cpu_executor()
        if ex is not None:
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(ex, _invoke, func, args, kwargs)
            except Exception:  # pragma: no cover - 进程池异常回退线程
                logger.warning("cpu pool execution failed; fallback to thread", exc_info=True)
    return await asyncio.to_thread(func, *args, **kwargs)


def shutdown_cpu_pool() -> None:
    """释放进程池（应用关闭时调用，可选）。"""
    global _cpu_executor
    if _cpu_executor is not None:
        _cpu_executor.shutdown(wait=False)
        _cpu_executor = None
