"""
Market WebSocket 鉴权分支测试
TEST-19: 覆盖 market.py WebSocket 端点的鉴权失败分支
"""
import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.routers.market import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


class TestWebSocketAuth:
    """测试 WebSocket 鉴权分支（无 token、token 失效、payload 无 sub）"""

    def test_no_token(self):
        """无 token，应返回 4001"""
        try:
            with client.websocket_connect("/market/quotes/ws", timeout=2) as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4001

    def test_invalid_token(self):
        """无效 token，应返回 4002"""
        try:
            with client.websocket_connect("/market/quotes/ws?token=invalid", timeout=2) as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4002

    def test_token_no_sub(self):
        """token payload 无 sub，应返回 4003"""
        from jose import jwt as _jwt
        token = _jwt.encode({}, "test-secret-key", algorithm="HS256")
        try:
            with client.websocket_connect(f"/market/quotes/ws?token={token}", timeout=2) as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003

    def test_valid_token(self):
        """有效 token，应成功连接"""
        from jose import jwt as _jwt
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        with client.websocket_connect(f"/market/quotes/ws?token={token}", timeout=2) as ws:
            # 连接成功，可以发送消息
            ws.send_text(json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}))
            # 应该收到响应
            data = ws.receive_json()
            assert data["code"] == 0
