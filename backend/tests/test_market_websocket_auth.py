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


class TestWebSocketMessageHandling:
    """测试 WebSocket 消息处理分支（非 dict payload、未知 action、ping、unsubscribe）"""

    @pytest.fixture
    def ws_token(self):
        from jose import jwt as _jwt
        return _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")

    def test_non_dict_payload(self, ws_token):
        """发送非 dict payload，应返回 2001"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            ws.send_text("not a json object")
            data = ws.receive_json()
            assert data["code"] == 2001
            assert "JSON" in data["msg"]

    def test_unknown_action(self, ws_token):
        """发送未知 action，应返回 2001"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            ws.send_text(json.dumps({"action": "unknown_action", "tickers": []}))
            data = ws.receive_json()
            assert data["code"] == 2001
            assert "Unknown action" in data["msg"]

    def test_ping(self, ws_token):
        """发送 ping，应返回 pong"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            ws.send_text(json.dumps({"action": "ping", "ts": 1234567890}))
            data = ws.receive_json()
            assert data["code"] == 0
            assert data["type"] == "pong"
            assert data["data"]["client_ts"] == 1234567890

    def test_subscribe_and_unsubscribe(self, ws_token):
        """订阅然后取消订阅"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            # 订阅
            ws.send_text(json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}))
            data = ws.receive_json()
            assert data["code"] == 0
            assert "US.AAPL" in data["data"]["subscribed"]

            # 取消订阅
            ws.send_text(json.dumps({"action": "unsubscribe", "tickers": ["US.AAPL"]}))
            data = ws.receive_json()
            assert data["code"] == 0
            assert "US.AAPL" in data["data"]["unsubscribed"]

    def test_subscribe_duplicate(self, ws_token):
        """重复订阅同一 ticker，应返回 already_subscribed"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            ws.send_text(json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}))
            data = ws.receive_json()
            assert data["code"] == 0
            assert "US.AAPL" in data["data"]["subscribed"]

            # 重复订阅
            ws.send_text(json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}))
            data = ws.receive_json()
            assert data["code"] == 0
            assert "US.AAPL" in data["data"]["already_subscribed"]

    def test_invalid_json(self, ws_token):
        """发送非法 JSON，应返回 2001"""
        with client.websocket_connect(f"/market/quotes/ws?token={ws_token}", timeout=2) as ws:
            ws.send_text("{invalid json}")
            data = ws.receive_json()
            assert data["code"] == 2001
            assert "Invalid JSON" in data["msg"]
