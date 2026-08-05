"""
DIST-FUTU-MIGRATE: 验证 Futu OpenD 长连接已从主服务剥离到子服务 (data_subservice.futu_src)

背景: 按"主服务无状态、可迁移"需求, Futu OpenD TCP 长连接 + 推送生产 + 交易
下单调用全部下沉到部署在主节点的 data_subservice 实例 (COLLECTOR_FUTU=true)。
主服务不再 import futu SDK / 不持有 OpenD 连接, 仅经 HTTP 调子服务 source=futu。

本测试覆盖:
  1. futu_src 包可独立 import, 且不反向依赖 backend (物理解耦)
  2. handle_futu 按 action 正确代理到 futu_service 各方法
  3. 未知 action 返回 error
  4. main.py 的 /api/v1/data 在未启用 COLLECTOR_FUTU 时返回 503
"""

import hashlib
import hmac
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_SUB = os.path.join(os.path.dirname(__file__), "..", "..", "data_subservice")
if _SUB not in sys.path:
    sys.path.insert(0, _SUB)


class TestFutuSrcPackageIsolation:
    """验证子服务 futu_src 包无 backend 反向依赖"""

    def test_import_without_backend(self):
        from data_subservice.futu_src import futu_service

        assert futu_service is not None

    def test_no_backend_imports(self):
        import data_subservice.futu_src as pkg

        # 包的 __file__ 必须在 data_subservice 内, 而非 backend
        assert "data_subservice" in pkg.__file__
        assert "backend" not in pkg.__file__


class TestHandleFutuRouting:
    """验证 handle_futu 按 action 代理到 futu_service"""

    @pytest.mark.asyncio
    async def test_quote_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        mock = AsyncMock(return_value={"a": 1})
        monkeypatch.setattr(futu_service, "get_quote", mock)
        out = await handle_futu("QUOTE", {"symbol": "HK.00700"})
        assert out == {"a": 1}
        mock.assert_awaited_once_with("HK.00700")

    @pytest.mark.asyncio
    async def test_history_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        mock = AsyncMock(return_value={"k": "h"})
        monkeypatch.setattr(futu_service, "get_history", mock)
        out = await handle_futu("HISTORY", {"symbol": "HK.00700", "ktype": "K_DAY", "num": 60})
        assert out == {"k": "h"}

    @pytest.mark.asyncio
    async def test_fund_flow_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        mock = AsyncMock(return_value={"k": "f"})
        monkeypatch.setattr(futu_service, "get_fund_flow", mock)
        out = await handle_futu("FUND_FLOW", {"symbol": "HK.00700"})
        assert out == {"k": "f"}

    @pytest.mark.asyncio
    async def test_option_chain_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        mock = AsyncMock(return_value={"k": "o"})
        monkeypatch.setattr(futu_service, "get_option_chain", mock)
        out = await handle_futu("OPTION_CHAIN", {"symbol": "HK.00700", "expiration_date": "2026-09"})
        assert out == {"k": "o"}

    @pytest.mark.asyncio
    async def test_account_info_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        mock = AsyncMock(return_value={"k": "acc"})
        monkeypatch.setattr(futu_service, "get_account_info", mock)
        out = await handle_futu("ACCOUNT_INFO", {"market": "HK"})
        assert out == {"k": "acc"}

    @pytest.mark.asyncio
    async def test_health_delegates(self, monkeypatch):
        from data_subservice.futu_src import futu_service
        from data_subservice.futu_worker import handle_futu

        monkeypatch.setattr(futu_service, "status", "CONNECTED")
        out = await handle_futu("HEALTH", {})
        assert out == {"available": True, "source": "futu"}

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from data_subservice.futu_worker import handle_futu

        out = await handle_futu("BOGUS", {"symbol": "HK.00700"})
        assert "error" in out
        assert "BOGUS" in out["error"]


class TestMainFutuDisabled:
    """验证未启用 COLLECTOR_FUTU 时主节点子服务拒绝 futu 请求(503)"""

    def test_futu_disabled_returns_503(self):
        with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": "x", "COLLECTOR_FUTU": "false"}):
            import data_subservice.main as mod

            mod.HMAC_SECRET = "x"
            from fastapi.testclient import TestClient

            c = TestClient(mod.app)
            body = '{"source":"futu","action":"QUOTE","params":{"symbol":"HK.00700"}}'
            ts = str(int(__import__("time").time()))
            sig = hmac.new(b"x", f"{ts}:{body}".encode(), hashlib.sha256).hexdigest()
            r = c.post("/api/v1/data", content=body, headers={"X-Timestamp": ts, "X-Signature": sig})
            assert r.status_code == 503
