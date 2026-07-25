"""
ARCH-06: 流式响应辅助

为 SSE / NDJSON 等长连接提供统一的「心跳保活 + 客户端断开检测 + 超时熔断」能力，
避免被 Cloudflare (100s) / Nginx 等反向代理因静默超时而掐断，并在客户端断开后
及时取消下游任务，避免无谓的算力空转。
"""

import asyncio
import time
from typing import AsyncIterator, Optional, Tuple

from fastapi import Request

# SSE 标准心跳注释行 (被代理/浏览器忽略，仅用于保活)
SSE_HEARTBEAT = b": keep-alive\n\n"
# NDJSON 心跳 (前端打字机/解析器忽略空行)
NDJSON_HEARTBEAT = b"\n"


async def heartbeat_wrap(
    source: AsyncIterator,
    request: Request,
    *,
    interval: float = 15.0,
    heartbeat: bytes = NDJSON_HEARTBEAT,
    deadline: Optional[float] = None,
) -> AsyncIterator[bytes]:
    """
    包裹一个流式 body 迭代器，提供三层保护：

    1. 心跳保活：若源在 `interval` 秒内未产出任何 chunk，则下发 `heartbeat`
       (默认 15s，对齐 Cloudflare 100s 代理超时，避免连接被中间层判定为死链)。
    2. 客户端断开：`await request.is_disconnected()` 为真立即终止，并取消下游 pump 任务。
    3. 超时熔断：超过 `deadline` (time.monotonic 时间戳) 立即终止。

    源本身抛出的异常会原样上抛，由上层中间件 / 异常处理器接管。
    """
    queue: "asyncio.Queue[Tuple[str, object]]" = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for chunk in source:
                await queue.put(("chunk", chunk))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 透传给外层
            await queue.put(("err", exc))
        finally:
            await queue.put(("stop", None))

    task = asyncio.create_task(_pump())
    try:
        while True:
            if await request.is_disconnected():
                break
            if deadline is not None and time.monotonic() > deadline:
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield heartbeat
                continue
            kind, value = item
            if kind == "stop":
                break
            if kind == "err":
                raise value  # type: ignore[misc]
            yield value  # type: ignore[misc]
    finally:
        # 客户端断开 / 超时 / 源结束 -> 取消下游 pump 任务，级联取消源协程
        task.cancel()
        try:
            await task
        except BaseException:
            pass
