"""数据服务能力落点测试 (修复3 剥离 yfinance)。

原主服务残留的 /proxy/yfinance、/proxy/akshare 端点 (commit 93f1ecf 删除
data_subservice/routes.py 后未清理) 已移除。yfinance / akshare 代理能力现
物理解耦到独立数据子服务 data_subservice, 经统一端点 /api/v1/data 提供。
本文件把原 test_data_source_router_proxy.py 的用例迁移到数据子服务, 验证:
  1. /api/v1/data 端点按 source+action 正确路由到 yfinance / akshare worker
  2. 返回归一化信封 {code, data}
  3. HMAC 鉴权: 缺头/签名错误返回 403 (原 proxy 端点声称的安全能力)
"""

import hashlib
import hmac
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# 让子服务包可被 backend 测试导入
_SUB = os.path.join(os.path.dirname(__file__), "..", "..", "data_subservice")
sys.path.insert(0, os.path.abspath(_SUB))

HMAC_SECRET = "test-subservice-secret"


@pytest.fixture
def client():
    """导入子服务 app, 注入测试用 HMAC 密钥并 mock 两个 worker。"""
    with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": HMAC_SECRET}):
        import data_subservice.main as mod

        mod.HMAC_SECRET = HMAC_SECRET
        # mock worker 实现, 隔离外部依赖
        mod.handle_yfinance = AsyncMock(return_value={"symbol": "AAPL", "ok": True})
        mod.handle_akshare = AsyncMock(return_value={"symbol": "000001", "ok": True})
        with (
            patch.object(mod, "handle_yfinance", mod.handle_yfinance),
            patch.object(mod, "handle_akshare", mod.handle_akshare),
        ):
            yield TestClient(mod.app)


def _sign(body: str, ts: str = None) -> dict:
    ts = ts or str(int(time.time()))
    sig = hmac.new(HMAC_SECRET.encode(), f"{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


class TestProxyCapabilitiesInDataService:
    """原 proxy 端点能力现由数据子服务 /api/v1/data 承接。"""

    def test_yfinance_quote_routed_to_worker(self, client):
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = client.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        assert r.json()["code"] == 0
        assert r.json()["data"] == {"symbol": "AAPL", "ok": True}
        # 验证路由到 yfinance worker 且 action/params 透传
        import data_subservice.main as mod

        mod.handle_yfinance.assert_awaited_once_with("QUOTE", {"symbol": "AAPL"})

    def test_yfinance_history_routed(self, client):
        body = '{"source":"yfinance","action":"HISTORY","params":{"symbol":"AAPL","period":"1y"}}'
        r = client.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        import data_subservice.main as mod

        mod.handle_yfinance.assert_awaited_once_with("HISTORY", {"symbol": "AAPL", "period": "1y"})

    def test_yfinance_tech_routed(self, client):
        body = '{"source":"yfinance","action":"TECH","params":{"symbol":"AAPL"}}'
        r = client.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        import data_subservice.main as mod

        mod.handle_yfinance.assert_awaited_once_with("TECH", {"symbol": "AAPL"})

    def test_akshare_southbound_routed(self, client):
        body = '{"source":"akshare","action":"FUND_FLOW","params":{"symbol":"000001"}}'
        r = client.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        import data_subservice.main as mod

        mod.handle_akshare.assert_awaited_once_with("FUND_FLOW", {"symbol": "000001"})

    def test_unknown_source_rejected(self, client):
        body = '{"source":"bogus","action":"QUOTE","params":{}}'
        r = client.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 400


class TestHmacEnforcement:
    """原 proxy 端点声称的 HMAC/IP 安全能力, 现由子服务统一端点强制实施。"""

    def test_missing_hmac_headers_returns_403(self, client):
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = client.post("/api/v1/data", content=body)
        assert r.status_code == 403

    def test_wrong_signature_returns_403(self, client):
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        headers = {
            "X-Timestamp": str(int(time.time())),
            "X-Signature": "deadbeef" * 8,
            "Content-Type": "application/json",
        }
        r = client.post("/api/v1/data", content=body, headers=headers)
        assert r.status_code == 403
