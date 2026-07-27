"""补充 routers/macro.py 遗漏分支的覆盖率测试。

macro 路由为薄层, 现有测试已覆盖各 GET 端点, 仅余:
- 69: /macro/sector-fund-flow 路由本体
- 128-186: /macro/news/ws WebSocket 处理器
- 192-265: /macro/calendar/ws WebSocket 处理器

WebSocket 握手用 HS256 JWT 鉴权 (密钥取自 macro_router._WS_SECRET_KEY);
pubsub 与 stream 拉取函数均 mock, 避免真实 redis / 外部依赖。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt
from starlette.websockets import WebSocketDisconnect

from backend.routers import macro as macro_router


@pytest.fixture
def client(test_client):
    return test_client


def _make_ws_token():
    return jwt.encode({"sub": "cov_user"}, macro_router._WS_SECRET_KEY, algorithm="HS256")


def _fake_pubsub():
    pubsub = MagicMock()

    async def _block_forever():
        # 永不产出, 使 listen_redis 任务保持 pending, 直到客户端断开触发
        # listen_client 任务完成 -> asyncio.wait 返回, 避免 handler 提前结束
        # 关闭连接与客户端接收 snapshot 之间的竞态。
        while True:
            await asyncio.sleep(3600)

    pubsub.listen = lambda: _block_forever()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.close = AsyncMock()
    return pubsub


# ── /macro/sector-fund-flow (69) ───────────────────────────────────────────
def test_sector_fund_flow_route(client):
    with patch(
        "backend.routers.macro.get_sector_fund_flow",
        new=AsyncMock(return_value={"status": "success", "data": []}),
    ):
        resp = client.get("/api/v1/macro/sector-fund-flow")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "success"


# ── /macro/news/ws (128-186) ───────────────────────────────────────────────
def test_news_websocket(client):
    pubsub = _fake_pubsub()
    rc = MagicMock()
    rc.pubsub = lambda: pubsub
    token = _make_ws_token()
    with (
        patch("backend.app.macro_app.redis_client", rc),
        patch(
            "backend.app.macro_app._fetch_macro_news_from_stream",
            new=AsyncMock(return_value=[]),
        ),
    ):
        with client.websocket_connect(f"/api/v1/macro/news/ws?token={token}") as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "news_snapshot"
        # 退出上下文 -> 客户端断开 -> 服务端 WebSocketDisconnect 收尾


# ── /macro/calendar/ws (192-265) ───────────────────────────────────────────
def test_calendar_websocket(client):
    pubsub = _fake_pubsub()
    rc = MagicMock()
    rc.pubsub = lambda: pubsub
    token = _make_ws_token()
    with (
        patch("backend.app.macro_app.redis_client", rc),
        patch(
            "backend.app.macro_app._fetch_macro_calendar_data",
            new=AsyncMock(return_value={"status": "success", "data": []}),
        ),
    ):
        with client.websocket_connect(f"/api/v1/macro/calendar/ws?token={token}") as ws:
            alert = ws.receive_json()
            assert alert["type"] == "macro_alert"
        # 退出上下文 -> 客户端断开 -> 服务端收尾 (256-265)


# ── WS 鉴权失败分支 (129-142, 193-206) ─────────────────────────────────────
def test_news_websocket_missing_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/macro/news/ws"):
            pass  # 缺 token -> 服务端 close(4001) 后直接 return


def test_news_websocket_invalid_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/macro/news/ws?token=garbage"):
            pass  # token 解码失败 -> close(4002)
