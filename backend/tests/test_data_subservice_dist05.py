"""
DIST-05: data_subservice 主服务入口集成测试（重构后版）
===================================================

背景: 原 DIST-05 测试针对旧版 main.py, 引用了已重构移除的符号:
  - DS_NODE_ID / DS_NODE_PORT (旧分布式注册表)
  - lifespan 上下文管理 / _heartbeat_loop / ServiceRegistry / aioredis
  - /ds/health 端点 / DS_CAPABILITIES

当前 data_subservice/main.py 架构 (物理解耦, 无 backend 依赖):
  - GET  /health                         -> 200 healthy (liveness)
  - POST /api/v1/data (HMAC 鉴权)        -> 路由 yfinance / akshare / tushare worker
  - GET  /metrics/circuit               -> 熔断状态快照
  - startup 事件可选注册 Redis 心跳 (ENABLE_REDIS_HEARTBEAT, 失败仅 warning)

本文件重写为适配当前架构。
"""

import hashlib
import hmac
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

_SUB = os.path.join(os.path.dirname(__file__), "..", "..", "data_subservice")
sys.path.insert(0, os.path.abspath(_SUB))

HMAC_SECRET = "test-subservice-secret"


def _sign(body: str, ts: str = None) -> dict:
    ts = ts or str(int(time.time()))
    sig = hmac.new(HMAC_SECRET.encode(), f"{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


@pytest.fixture
def client():
    with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": HMAC_SECRET}):
        import data_subservice.main as mod

        mod.HMAC_SECRET = HMAC_SECRET

        # akshare / tushare 经延迟导入分支加载, 真实 SDK 在测试环境未必安装。
        # 因此构造 stub 模块注入 sys.modules, 让 main.fetch_data 的 __import__ 拿到,
        # 同时把 AsyncMock 作为 handle_* 挂上去, 既避免真实 SDK 依赖又保留断言能力。
        import types

        akshare_mod = types.ModuleType("data_subservice.akshare_worker")
        akshare_mod.handle_akshare = AsyncMock(return_value={"k": "ak"})
        tushare_mod = types.ModuleType("data_subservice.tushare_worker")
        tushare_mod.handle_tushare = AsyncMock(return_value={"k": "ts"})
        sys.modules["data_subservice.akshare_worker"] = akshare_mod
        sys.modules["data_subservice.tushare_worker"] = tushare_mod

        with patch.object(mod, "handle_yfinance", AsyncMock(return_value={"k": "yf"})):
            tc = __import__("fastapi.testclient").testclient.TestClient(mod.app)
            yield mod, tc, akshare_mod, tushare_mod


# ─────────────────────────────────────────
#  入口存活 / 网关
# ─────────────────────────────────────────


class TestSubserviceEntrypoint:
    def test_health_liveness(self, client):
        _, c, _, _ = client
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    def test_circuit_metrics(self, client):
        _, c, _, _ = client
        r = c.get("/metrics/circuit")
        assert r.status_code == 200
        # status_snapshot 返回 dict (key -> state)
        assert isinstance(r.json(), dict)


# ─────────────────────────────────────────
#  /api/v1/data 路由分发 (含 HMAC)
# ─────────────────────────────────────────


class TestDataSourceDispatch:
    def test_yfinance_routed(self, client):
        mod, c, _, _ = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        assert r.json()["data"] == {"k": "yf"}
        mod.handle_yfinance.assert_awaited_once_with("QUOTE", {"symbol": "AAPL"})

    def test_akshare_routed(self, client):
        _, c, ak_mod, _ = client
        body = '{"source":"akshare","action":"SOUTHBOUND","params":{}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        assert r.json()["data"] == {"k": "ak"}
        ak_mod.handle_akshare.assert_awaited_once_with("SOUTHBOUND", {})

    def test_tushare_routed(self, client):
        _, c, _, ts_mod = client
        body = '{"source":"tushare","action":"STOCK_HISTORY","params":{"symbol":"000001.SZ"}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        assert r.json()["data"] == {"k": "ts"}
        ts_mod.handle_tushare.assert_awaited_once_with("STOCK_HISTORY", {"symbol": "000001.SZ"})

    def test_unknown_source_rejected(self, client):
        _, c, _, _ = client
        body = '{"source":"bogus","action":"QUOTE","params":{}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        # 网关对未声明能力(DS_CAPABILITIES 不含)统一返回 503 服务不可用
        assert r.status_code == 503

    def test_missing_hmac_returns_403(self, client):
        _, c, _, _ = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = c.post("/api/v1/data", content=body)
        assert r.status_code == 403

    def test_wrong_signature_returns_403(self, client):
        _, c, _, _ = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        headers = {
            "X-Timestamp": str(int(time.time())),
            "X-Signature": "deadbeef" * 8,
            "Content-Type": "application/json",
        }
        r = c.post("/api/v1/data", content=body, headers=headers)
        assert r.status_code == 403
