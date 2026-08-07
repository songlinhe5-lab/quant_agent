"""
DIST-06: data_subservice yfinance 核心逻辑迁移 — 单元测试（重构后版）
================================================================

背景: 原 DIST-06 测试针对旧版 `YFinanceWorker` 类 + daemon + `/ds/health`
架构, 而子服务已重构为函数式 `handle_yfinance` + 模块级单例 `yfinance_service`
(叶子节点, 无守护进程)。旧测试引用的 `YFinanceWorker` / `_yf_worker` /
`DS_CAPABILITIES` / `/ds/health` 等符号已不存在, 导致整文件 collection error。

本文件重写为适配当前架构, 覆盖:
  1. `yfinance_service` 单例身份 (叶子节点, 无 macro daemon)
  2. `fetch_yf_data` 统一入口路由表
  3. `handle_yfinance` 按 action 正确代理到 service 各方法
  4. 未知 action 返回 error
  5. main.py `/api/v1/data` 端点正确路由到 yfinance + HMAC 鉴权 + 归一化信封
"""

import hashlib
import hmac
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

# 让子服务包可被 backend 测试导入
_SUB = os.path.join(os.path.dirname(__file__), "..", "..", "data_subservice")
sys.path.insert(0, os.path.abspath(_SUB))

HMAC_SECRET = "test-subservice-secret"


# ─────────────────────────────────────────
#  1. yfinance_service 单例身份
# ─────────────────────────────────────────


class TestYFinanceServiceSingleton:
    """验证子服务 yfinance_service 的叶子节点身份"""

    def test_singleton_is_yfinance_service(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice._internal.yfinance.service import YFinanceService

        assert isinstance(yfinance_service, YFinanceService)

    def test_leaf_node_no_macro_daemon(self):
        """子服务恒为叶子节点, 无 macro daemon"""
        from data_subservice._internal.yfinance import yfinance_service

        assert yfinance_service.get_macro_daemon() is None
        assert yfinance_service.source_name == "yfinance"


# ─────────────────────────────────────────
#  2. fetch_yf_data 统一入口路由表
# ─────────────────────────────────────────


class TestFetchYfDataRouting:
    """验证 fetch_yf_data 按 endpoint 路由到具体实现"""

    @pytest.mark.asyncio
    async def test_routes_quote(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_quote", new=AsyncMock(return_value={"k": "quote"})) as m:
            out = await yfinance_service.fetch_yf_data("quote", "AAPL")
            assert out == {"k": "quote"}
            m.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_routes_history(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_history", new=AsyncMock(return_value={"k": "hist"})) as m:
            out = await yfinance_service.fetch_yf_data("history", "AAPL", period="1y")
            assert out == {"k": "hist"}
            m.assert_awaited_once_with("AAPL", period="1y")

    @pytest.mark.asyncio
    async def test_routes_flow(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_fund_flow", new=AsyncMock(return_value={"k": "flow"})) as m:
            out = await yfinance_service.fetch_yf_data("flow", "AAPL")
            assert out == {"k": "flow"}
            m.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_routes_financials(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_financials", new=AsyncMock(return_value={"k": "fin"})) as m:
            out = await yfinance_service.fetch_yf_data("financials", "AAPL", kind="quarter")
            assert out == {"k": "fin"}
            m.assert_awaited_once_with("AAPL", kind="quarter")

    @pytest.mark.asyncio
    async def test_routes_option_chain(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_option_chain", new=AsyncMock(return_value={"k": "opt"})) as m:
            out = await yfinance_service.fetch_yf_data("option_chain", "AAPL")
            assert out == {"k": "opt"}
            m.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_routes_search(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "search", new=AsyncMock(return_value=[{"symbol": "AAPL"}])) as m:
            out = await yfinance_service.fetch_yf_data("search", "Apple", limit=5)
            assert out == [{"symbol": "AAPL"}]
            m.assert_awaited_once_with("Apple", limit=5)

    @pytest.mark.asyncio
    async def test_routes_technical(self):
        from data_subservice._internal.yfinance import yfinance_service

        with patch.object(yfinance_service, "get_tech_indicators", new=AsyncMock(return_value={"k": "tech"})) as m:
            out = await yfinance_service.fetch_yf_data("technical", "AAPL", period="6mo")
            assert out == {"k": "tech"}
            m.assert_awaited_once_with("AAPL", period="6mo")

    @pytest.mark.asyncio
    async def test_unknown_endpoint_returns_error(self):
        from data_subservice._internal.yfinance import yfinance_service

        out = await yfinance_service.fetch_yf_data("bogus", "AAPL")
        assert "error" in out
        assert "bogus" in out["error"]


# ─────────────────────────────────────────
#  3. handle_yfinance 动作路由
# ─────────────────────────────────────────


class TestHandleYfinanceRouting:
    """验证 handle_yfinance 按 action 正确代理到 yfinance_service"""

    @pytest.mark.asyncio
    async def test_quote_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(
            yfinance_service, "get_quote", new=AsyncMock(return_value={"symbol": "AAPL", "price": 100})
        ) as m:
            out = await handle_yfinance("QUOTE", {"symbol": "AAPL"})
            assert out == {"symbol": "AAPL", "price": 100}
            m.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_history_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        params = {"symbol": "AAPL", "period": "1y", "interval": "1d"}
        with patch.object(yfinance_service, "get_history", new=AsyncMock(return_value={"count": 0})) as m:
            out = await handle_yfinance("HISTORY", params)
            assert out == {"count": 0}
            m.assert_awaited_once_with("AAPL", period="1y", start=None, end=None, interval="1d")

    @pytest.mark.asyncio
    async def test_fund_flow_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "get_fund_flow", new=AsyncMock(return_value={"flow": 1})) as m:
            out = await handle_yfinance("FUND_FLOW", {"symbol": "AAPL"})
            assert out == {"flow": 1}
            m.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_option_chain_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "get_option_chain", new=AsyncMock(return_value={"chain": []})) as m:
            out = await handle_yfinance("OPTION_CHAIN", {"symbol": "AAPL", "expiration": "2026-09"})
            assert out == {"chain": []}
            m.assert_awaited_once_with("AAPL", expiration="2026-09")

    @pytest.mark.asyncio
    async def test_financials_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "get_financials", new=AsyncMock(return_value={"fin": 1})) as m:
            out = await handle_yfinance("FINANCIALS", {"symbol": "AAPL", "kind": "quarter"})
            assert out == {"fin": 1}
            m.assert_awaited_once_with("AAPL", kind="quarter")

    @pytest.mark.asyncio
    async def test_search_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "search", new=AsyncMock(return_value=[{"symbol": "AAPL"}])) as m:
            out = await handle_yfinance("SEARCH", {"query": "Apple", "limit": 10})
            assert out == [{"symbol": "AAPL"}]
            m.assert_awaited_once_with("Apple", limit=10)

    @pytest.mark.asyncio
    async def test_tech_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "get_tech_indicators", new=AsyncMock(return_value={"indicators": {}})) as m:
            out = await handle_yfinance("TECH", {"symbol": "AAPL", "period": "1y", "indicators": ["RSI"]})
            assert out == {"indicators": {}}
            m.assert_awaited_once_with("AAPL", period="1y", indicators=["RSI"])

    @pytest.mark.asyncio
    async def test_batch_quote_delegates(self):
        from data_subservice._internal.yfinance import yfinance_service
        from data_subservice.yfinance_worker import handle_yfinance

        with patch.object(yfinance_service, "get_batched_quote", new=AsyncMock(return_value=[{"symbol": "AAPL"}])) as m:
            out = await handle_yfinance("BATCH_QUOTE", {"symbols": ["AAPL", "MSFT"]})
            assert out == [{"symbol": "AAPL"}]
            m.assert_awaited_once_with(["AAPL", "MSFT"])

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from data_subservice.yfinance_worker import handle_yfinance

        out = await handle_yfinance("BOGUS", {"symbol": "AAPL"})
        assert "error" in out
        assert "BOGUS" in out["error"]


# ─────────────────────────────────────────
#  4. main.py 端点集成
# ─────────────────────────────────────────


@pytest.fixture
def client():
    """导入子服务 app, 注入测试用 HMAC 密钥并 mock worker。"""
    with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": HMAC_SECRET}):
        import data_subservice.main as mod

        mod.HMAC_SECRET = HMAC_SECRET
        mod.handle_yfinance = AsyncMock(return_value={"symbol": "AAPL", "ok": True})
        with patch.object(mod, "handle_yfinance", mod.handle_yfinance):
            yield mod, __import__("fastapi.testclient").testclient.TestClient(mod.app)


def _sign(body: str, ts: str = None) -> dict:
    ts = ts or str(int(time.time()))
    sig = hmac.new(HMAC_SECRET.encode(), f"{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


class TestMainDataEndpoint:
    """验证 main.py /api/v1/data 端点正确路由 yfinance + HMAC + 信封"""

    def test_yfinance_quote_routed_to_worker(self, client):
        mod, c = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        assert r.json()["code"] == 0
        assert r.json()["data"] == {"symbol": "AAPL", "ok": True}
        mod.handle_yfinance.assert_awaited_once_with("QUOTE", {"symbol": "AAPL"})

    def test_yfinance_history_routed(self, client):
        mod, c = client
        body = '{"source":"yfinance","action":"HISTORY","params":{"symbol":"AAPL","period":"1y"}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        mod.handle_yfinance.assert_awaited_once_with("HISTORY", {"symbol": "AAPL", "period": "1y"})

    def test_yfinance_tech_routed(self, client):
        mod, c = client
        body = '{"source":"yfinance","action":"TECH","params":{"symbol":"AAPL"}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 200
        mod.handle_yfinance.assert_awaited_once_with("TECH", {"symbol": "AAPL"})

    def test_unknown_source_rejected(self, client):
        _, c = client
        body = '{"source":"bogus","action":"QUOTE","params":{}}'
        r = c.post("/api/v1/data", content=body, headers=_sign(body))
        assert r.status_code == 400

    def test_missing_hmac_headers_returns_403(self, client):
        _, c = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        r = c.post("/api/v1/data", content=body)
        assert r.status_code == 403

    def test_wrong_signature_returns_403(self, client):
        _, c = client
        body = '{"source":"yfinance","action":"QUOTE","params":{"symbol":"AAPL"}}'
        headers = {
            "X-Timestamp": str(int(time.time())),
            "X-Signature": "deadbeef" * 8,
            "Content-Type": "application/json",
        }
        r = c.post("/api/v1/data", content=body, headers=headers)
        assert r.status_code == 403
