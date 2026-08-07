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
  含锁对象）自动回退到 **独立** 的 fallback 线程池，与默认事件循环线程池
  （承载 akshare/futu/redis 等快速 SDK 卸载）物理隔离，避免重 CPU 任务饿死快速调用。
- 经 ``asyncio.Semaphore`` 对并发 CPU 密集任务总数封顶，提供背压，超容任务在
  信号量处排队而非无界占用线程。
- 进程池初始化或执行异常时同样回退上述独立线程池，绝不因进程池故障而让请求失败。
- 默认启用，可用环境变量 ``QUANT_CPU_POOL_ENABLED=0`` 关闭（强制回退线程）。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import pickle
import queue
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 进程池懒初始化；默认与逻辑核数对齐，避免与默认线程池争抢 CPU。
_cpu_executor: "ProcessPoolExecutor | None" = None
# fallback 线程池：与默认事件循环线程池物理隔离，专供不可 pickle / 进程池故障时的重 CPU 任务
_fallback_executor: "ThreadPoolExecutor | None" = None
# 每个事件循环一把信号量（按 loop id 缓存），对并发 CPU 密集任务总数封顶提供背压
_semaphores: dict = {}
_cpu_pool_enabled = os.getenv("QUANT_CPU_POOL_ENABLED", "1").lower() not in (
    "0",
    "false",
    "no",
)


def _resolve_max_workers() -> int:
    """解析进程池上限，避免多 worker 部署下的进程爆炸 (ARCH-07 追问 2)。

    - 显式 ``QUANT_CPU_POOL_MAX_WORKERS`` 优先；
    - 否则在 gunicorn/uvicorn ``--workers N`` 部署下，按 worker 数均分逻辑核，
      保证 ``uvicorn_workers × pool_workers ≲ cpu_count``，杜绝 CPU oversubscription；
    - 单 worker 场景也封顶 4，避免无谓的进程开销。
    """
    env_max = os.getenv("QUANT_CPU_POOL_MAX_WORKERS")
    if env_max and env_max.isdigit():
        return max(1, int(env_max))
    cpu = os.cpu_count() or 2
    siblings = int(os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS") or "1")
    return max(1, min(cpu // max(siblings, 1), 4))


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
                max_workers=_resolve_max_workers(),
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


def _ensure_fallback_executor() -> ThreadPoolExecutor:
    """懒初始化 fallback 线程池，与默认事件循环线程池隔离。"""
    global _fallback_executor
    if _fallback_executor is None:
        _fallback_executor = ThreadPoolExecutor(
            max_workers=_resolve_max_workers(),
            thread_name_prefix="cpu-fallback",
        )
    return _fallback_executor


def _get_semaphore(limit: int) -> "asyncio.Semaphore":
    """取当前事件循环的信号量（按 loop id 缓存，避免跨 loop 绑定告警）。"""
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(id(loop))
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[id(loop)] = sem
    return sem


async def run_cpu_bound(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """将 CPU 密集型任务卸载到独立进程池，并对并发数做背压限流。

    - 负载可 pickle → 走独立 ``ProcessPoolExecutor``（真并行，绕开 GIL）；
    - 不可 pickle / 进程池不可用 / 进程池异常 → 回退到 **独立** 的 fallback 线程池，
      与默认事件循环线程池（承载 akshare/futu/redis 等快速 SDK 卸载）物理隔离；
    - 全程经 ``asyncio.Semaphore`` 对并发 CPU 密集任务总数封顶，提供背压。
    """
    sem = _get_semaphore(_resolve_max_workers())
    async with sem:
        if _is_picklable(func, args, kwargs):
            ex = _ensure_cpu_executor()
            if ex is not None:
                loop = asyncio.get_running_loop()
                try:
                    return await loop.run_in_executor(ex, _invoke, func, args, kwargs)
                except Exception:  # pragma: no cover - 进程池异常回退线程
                    logger.warning("cpu pool execution failed; fallback to thread", exc_info=True)
        fb = _ensure_fallback_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(fb, _invoke, func, args, kwargs)


def shutdown_cpu_pool() -> None:
    """释放进程池与 fallback 线程池（应用关闭时调用，可选）。"""
    global _cpu_executor, _fallback_executor
    if _cpu_executor is not None:
        _cpu_executor.shutdown(wait=False)
        _cpu_executor = None
    if _fallback_executor is not None:
        _fallback_executor.shutdown(wait=False)
        _fallback_executor = None


async def run_cpu_bound_with_progress(
    func: Callable[..., Any],
    *args: Any,
    on_progress: Callable[[dict], None] | None = None,
    **kwargs: Any,
) -> Any:
    """在 worker 线程中执行 CPU 密集函数，并实时流式回传进度。

    与 :func:`run_cpu_bound` 不同，本函数使用 **线程**（fallback 线程池）而非进程池，
    以便在主线程与 worker 之间共享一个进程内 :class:`queue.Queue` 来传递进度包。

    * ``func`` **必须** 接受 ``progress_queue`` 关键字参数（一个 :class:`queue.Queue`），
      并在执行过程中按阶段推送形如
      ``{"progress": 0-100, "stage": str, "detail": str}`` 的进度字典。
      若 ``func`` 不接受 ``progress_queue``（通过签名探测），则不注入，此时仅外层
      stage 进度（由调用方通过 ``on_progress`` 自行推送）生效 —— 不会抛错。
    * ``on_progress(payload)`` 为同步回调，在事件循环中每个进度包被 drain 时调用，
      通常用于将进度推入 asyncio 队列以驱动 SSE 流。
    * 返回值即 ``func`` 的返回值。

    注意：由于 vbt / numba / numpy 在 C 扩展内会释放 GIL，worker 线程执行重计算时
    事件循环仍可调度 drain 协程，因此进度上报不会被饿死。
    """
    q: "queue.Queue" = queue.Queue()

    try:
        accepts = "progress_queue" in inspect.signature(func).parameters
    except (ValueError, TypeError):
        accepts = False

    loop = asyncio.get_running_loop()
    if accepts:
        # run_in_executor 仅转发位置参数给 func，故 progress_queue 须作为末位位置参数
        # run_in_executor 的 callable 类型标注偏严，func(*args, q) 运行时合法
        future = loop.run_in_executor(_ensure_fallback_executor(), func, *args, q)  # type: ignore[arg-type]
    else:
        future = loop.run_in_executor(_ensure_fallback_executor(), func, *args)

    # drain：在任务运行期间持续取出 worker 推送的进度包并回调。
    while True:
        try:
            payload = q.get_nowait()
        except queue.Empty:
            if future.done():
                break
            await asyncio.sleep(0.05)
            continue
        if on_progress is not None:
            on_progress(payload)

    # 收尾 drain：捕获 worker 在返回后、future.done() 之前压入的尾部进度。
    while not q.empty():
        payload = q.get_nowait()
        if on_progress is not None:
            on_progress(payload)

    return await future
