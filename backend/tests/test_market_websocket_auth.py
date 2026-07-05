"""
Market WebSocket 鉴权分支测试
TEST-19: 覆盖 market.py WebSocket 端点的鉴权失败分支

策略：直接测试 WebSocket handler 函数的鉴权逻辑，
通过 mock WebSocket 对象避免 TestClient 线程管理问题。
"""
import os
import sys
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _make_mock_ws(token=None, query_params=None):
    """构建 mock WebSocket 对象"""
    ws = AsyncMock()
    params = {}
    if token is not None:
        params["token"] = token
    if query_params:
        params.update(query_params)
    ws.query_params = params
    ws.receive_text = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def reset_market_module_state():
    """每个测试前重置 market 模块的关键状态"""
    from backend.routers import market as market_module
    market_module._SECRET_KEY = "test-secret-key"
    mock_manager = MagicMock()
    mock_manager.subscriptions = {}
    mock_manager.connect = AsyncMock()
    mock_manager.subscribe = MagicMock()
    mock_manager.unsubscribe = MagicMock()
    mock_manager.disconnect = MagicMock()
    market_module.manager = mock_manager
    yield


class TestWebSocketAuth:
    """测试 WebSocket 鉴权分支（无 token、token 失效、payload 无 sub）"""

    @pytest.mark.asyncio
    async def test_no_token(self):
        """无 token，应返回 4001"""
        from backend.routers.market import quotes_websocket
        ws = _make_mock_ws()
        await quotes_websocket(ws)
        ws.close.assert_called_once()
        assert ws.close.call_args[1]["code"] == 4001 or ws.close.call_args.kwargs.get("code") == 4001

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        """无效 token，应返回 4002"""
        from backend.routers.market import quotes_websocket
        ws = _make_mock_ws(token="invalid")
        await quotes_websocket(ws)
        ws.close.assert_called_once()
        call_kwargs = ws.close.call_args.kwargs
        assert call_kwargs.get("code") == 4002

    @pytest.mark.asyncio
    async def test_token_no_sub(self):
        """token payload 无 sub，应返回 4003"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        await quotes_websocket(ws)
        ws.close.assert_called_once()
        call_kwargs = ws.close.call_args.kwargs
        assert call_kwargs.get("code") == 4003

    @pytest.mark.asyncio
    async def test_valid_token(self):
        """有效 token，应成功连接并处理订阅"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        # 模拟收到一条订阅消息后断开
        ws.receive_text.side_effect = [
            json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}),
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        # 验证 send_text 被调用（发送了订阅确认）
        assert ws.send_text.called
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 0


class TestWebSocketMessageHandling:
    """测试 WebSocket 消息处理分支"""

    @pytest.mark.asyncio
    async def test_non_dict_payload(self):
        """发送非 dict payload，应返回 2001"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        ws.receive_text.side_effect = [
            "not a json object",
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 2001
        assert "JSON" in sent_data["msg"]

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        """发送未知 action，应返回 2001"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        ws.receive_text.side_effect = [
            json.dumps({"action": "unknown_action", "tickers": []}),
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 2001
        assert "Unknown action" in sent_data["msg"]

    @pytest.mark.asyncio
    async def test_ping(self):
        """发送 ping，应返回 pong"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        ws.receive_text.side_effect = [
            json.dumps({"action": "ping", "ts": 1234567890}),
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 0
        assert sent_data["type"] == "pong"
        assert sent_data["data"]["client_ts"] == 1234567890

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self):
        """订阅然后取消订阅"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        ws.receive_text.side_effect = [
            json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}),
            json.dumps({"action": "unsubscribe", "tickers": ["US.AAPL"]}),
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        # 第一次响应：订阅确认
        sub_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sub_data["code"] == 0
        assert "US.AAPL" in sub_data["data"]["subscribed"]
        # 第二次响应：取消订阅确认
        unsub_data = json.loads(ws.send_text.call_args_list[1][0][0])
        assert unsub_data["code"] == 0
        assert "US.AAPL" in unsub_data["data"]["unsubscribed"]

    @pytest.mark.asyncio
    async def test_subscribe_duplicate(self):
        """重复订阅同一 ticker，应返回 already_subscribed"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        # 模拟 manager.subscriptions 已有 US.AAPL
        from backend.routers import market as market_module
        market_module.manager.subscriptions = {ws: {"US.AAPL"}}
        ws.receive_text.side_effect = [
            json.dumps({"action": "subscribe", "tickers": ["US.AAPL"]}),
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 0
        assert "US.AAPL" in sent_data["data"]["already_subscribed"]

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """发送非法 JSON，应返回 2001"""
        from jose import jwt as _jwt
        from backend.routers.market import quotes_websocket
        token = _jwt.encode({"sub": "testuser"}, "test-secret-key", algorithm="HS256")
        ws = _make_mock_ws(token=token)
        ws.receive_text.side_effect = [
            "{invalid json}",
            Exception("WebSocketDisconnect"),
        ]
        await quotes_websocket(ws)
        sent_data = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_data["code"] == 2001
        assert "Invalid JSON" in sent_data["msg"]
