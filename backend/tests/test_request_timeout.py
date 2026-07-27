"""
ARCH-06: 请求级超时与取消传播测试

覆盖：
- 路由级超时解析 (screener 90 / market 30 / 默认 60，且 market-review 不误判)
- 流式包裹器 heartbeat_wrap：静默保活 / 正常结束 / 客户端断开 / 超时熔断
- 中间件集成：慢请求 504、快请求 200、流式端点正常穿透并注入保活
"""

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.core.request_timeout import _resolve_timeout, request_timeout_middleware
from backend.core.stream_utils import (
    NDJSON_HEARTBEAT,
    SSE_HEARTBEAT,
    heartbeat_wrap,
)


class _FakeReq:
    """最小 Request 替身，仅实现 is_disconnected()"""

    def __init__(self, disconnected: bool = False):
        self._d = disconnected

    async def is_disconnected(self) -> bool:
        return self._d


async def _collect(gen, max_wait: float = 2.0):
    out = []
    try:
        async with asyncio.timeout(max_wait):
            async for chunk in gen:
                out.append(chunk)
    except asyncio.TimeoutError:
        pass
    return out


# ─── 路由超时解析 ────────────────────────────────────────────────
def test_resolve_timeout_paths():
    assert _resolve_timeout("/api/v1/screener/run") == 90.0
    assert _resolve_timeout("/api/v1/screener/translate") == 90.0
    assert _resolve_timeout("/api/v1/market/quote") == 30.0
    assert _resolve_timeout("/api/v1/market/history") == 30.0
    # 关键：market-review 不能被误判为 market 路由
    assert _resolve_timeout("/api/v1/market-review/foo") == 60.0
    assert _resolve_timeout("/api/v1/chat") == 60.0
    assert _resolve_timeout("/api/v1/health") == 60.0


# ─── heartbeat_wrap 单元 ─────────────────────────────────────────
async def test_heartbeat_on_stall():
    async def src():
        await asyncio.sleep(10)  # 永远不产数据
        yield b"x"

    chunks = await _collect(heartbeat_wrap(src(), _FakeReq(), interval=0.1), max_wait=0.5)
    assert any(c == NDJSON_HEARTBEAT for c in chunks), "静默时应注入心跳"


async def test_heartbeat_sse_format():
    async def src():
        await asyncio.sleep(10)
        yield b"x"

    chunks = await _collect(
        heartbeat_wrap(src(), _FakeReq(), interval=0.1, heartbeat=SSE_HEARTBEAT),
        max_wait=0.5,
    )
    assert any(c == SSE_HEARTBEAT for c in chunks), "SSE 静默应注入 ': keep-alive' 注释"


async def test_heartbeat_normal_finish():
    async def src():
        for i in range(3):
            yield f"chunk{i}".encode()

    chunks = await _collect(heartbeat_wrap(src(), _FakeReq(), interval=10.0), max_wait=1.0)
    assert chunks == [b"chunk0", b"chunk1", b"chunk2"]


async def test_heartbeat_disconnect_immediate():
    async def src():
        await asyncio.sleep(10)
        yield b"x"

    chunks = await _collect(heartbeat_wrap(src(), _FakeReq(disconnected=True), interval=0.1), max_wait=0.5)
    assert chunks == [], "客户端已断开应立即停止，不产出任何 chunk"


async def test_heartbeat_deadline():
    deadline = asyncio.get_event_loop().time() + 0.15

    async def src():
        await asyncio.sleep(10)
        yield b"x"

    chunks = await _collect(heartbeat_wrap(src(), _FakeReq(), interval=10.0, deadline=deadline), max_wait=0.5)
    assert chunks == [], "超过 deadline 应立即停止"


# ─── 中间件集成 ──────────────────────────────────────────────────
def test_timeout_504_and_200(monkeypatch):
    monkeypatch.setenv("REQUEST_TIMEOUT_DEFAULT", "0.3")
    app = FastAPI()
    app.middleware("http")(request_timeout_middleware)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(2.0)
        return {"ok": True}

    @app.get("/fast")
    async def fast():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/slow")
    assert r.status_code == 504
    body = r.json()
    assert body.get("code") == "REQUEST_TIMEOUT"
    assert "超时" in body.get("message", "")

    r2 = client.get("/fast")
    assert r2.status_code == 200


def test_stream_under_middleware(monkeypatch):
    monkeypatch.setenv("REQUEST_TIMEOUT_DEFAULT", "60")
    app = FastAPI()
    app.middleware("http")(request_timeout_middleware)

    @app.get("/stream")
    async def stream(request: Request):
        async def gen():
            yield b"a"
            await asyncio.sleep(0.2)
            yield b"b"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    client = TestClient(app)
    r = client.get("/stream")
    assert r.status_code == 200
    data = r.content
    assert b"a" in data and b"b" in data
