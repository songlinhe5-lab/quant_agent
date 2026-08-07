"""DataSourceRouter Futu 通道 (HTTP 化改造 Phase 1) 单测。

验证主服务经 DataSourceRouter 访问 source=futu 时:
  1. 默认 router 禁用 -> fetch_futu 降级本地 futu_service (保留 SDK 兼容)
  2. router 启用且 futu_master 节点健康 -> 走远程 HTTP, 且 action 经 _FUTU_ACTION_MAP 映射
  3. futu_master 节点 pin 主节点, 不随机选 (OpenD 仅主节点)
  4. 远程失败 -> 降级本地 futu_service

sys.path 注入与主工程其余测试一致。
"""

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from backend.services.datasource.router import DataSourceRouter


@pytest.fixture
def remote_router():
    """router 启用且 futu_master 节点健康。"""
    with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "true", "DATA_SOURCE_HMAC_SECRET": "test-futu-secret"}):
        r = DataSourceRouter()
    assert r._enabled is True
    r._nodes["futu_master"].status = "healthy"
    return r


class TestFutuActionMap:
    def test_action_map_known(self):
        from backend.services.datasource.router import _FUTU_ACTION_MAP

        assert _FUTU_ACTION_MAP["quote"] == "QUOTE"
        assert _FUTU_ACTION_MAP["history"] == "HISTORY"
        assert _FUTU_ACTION_MAP["fund_flow"] == "FUND_FLOW"
        # 快照在子服务契约里是 SNAPSHOT (取 symbols)
        assert _FUTU_ACTION_MAP["market_snapshots"] == "SNAPSHOT"
        assert _FUTU_ACTION_MAP["stock_basicinfo"] == "STOCK_BASICINFO"
        assert _FUTU_ACTION_MAP["place_order"] == "PLACE_ORDER"


class TestFutuNodeRegistered:
    def test_futu_master_node_exists(self, remote_router):
        assert "futu_master" in remote_router._nodes
        node = remote_router._nodes["futu_master"]
        assert "futu" in node.capabilities
        assert node.url.startswith("http")


class TestFetchFutuDisabledDegradesLocal:
    """router 禁用 -> 降级本地 futu_service.get_quote。"""

    @pytest.mark.asyncio
    async def test_disabled_uses_local_futu_service(self):
        with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
            r = DataSourceRouter()
        with patch("backend.services.futu.futu_service") as mock_fs:
            mock_fs.get_quote.return_value = {"status": "success", "data": {"last_price": 10}}
            out = await r.fetch_futu("QUOTE", ticker="HK.00700")
        mock_fs.get_quote.assert_called_once_with("HK.00700")
        assert out["status"] == "success"


class TestFetchFutuRemotePinnedMaster:
    @pytest.mark.asyncio
    async def test_remote_success_maps_action(self, remote_router):
        # 子服务返回 {code:0, data: <futu_service 原始 dict>}, _normalize_response 包一层
        # _send_request 内部已调 _normalize_response 剥信封, 故 mock 返回已 normalize 的结构
        # (status="success", data=<子服务透传的 futu_service 原始 dict 双层>)。
        fake_resp = {"status": "success", "data": {"status": "success", "data": {"last_price": 12}}}
        with patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fake_resp)) as mock_send:
            out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        # 必须 pin 到 futu_master 节点
        mock_send.assert_awaited_once()
        call_node = mock_send.await_args.args[0]
        assert call_node.name == "futu_master"
        # action 经 _FUTU_ACTION_MAP 映射为大写 QUOTE
        sent_payload = mock_send.await_args.args[2]
        assert sent_payload["source"] == "futu"
        assert sent_payload["action"] == "QUOTE"
        # 业务侧传 ticker, router 已对齐为子服务 worker 契约的 symbol
        assert sent_payload["params"] == {"symbol": "HK.00700"}
        # 剥信封: _normalize_response 把子服务 data(含 futu_service 原始 dict) 透传为
        # result["data"], 故 last_price 在 result["data"]["data"] 层 (远程双层 vs 本地单层
        # 的现状差异, 见 fetch_futu 远程分支注释; 子服务侧剥信封对齐待办)
        assert out["status"] == "success"
        assert out["data"]["data"]["last_price"] == 12

    @pytest.mark.asyncio
    async def test_remote_snapshot_maps_to_snapshot(self, remote_router):
        fake_resp = {"status": "success", "data": {"status": "success", "data": []}}
        with patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fake_resp)) as mock_send:
            await remote_router.fetch_futu("MARKET_SNAPSHOTS", tickers=["HK.00700"])
        sent_payload = mock_send.await_args.args[2]
        assert sent_payload["action"] == "SNAPSHOT"

    @pytest.mark.asyncio
    async def test_remote_failure_degrades_local(self, remote_router):
        fail_resp = {"status": "error", "message": "subservice down"}
        with (
            patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fail_resp)),
            patch("backend.services.futu.futu_service") as mock_fs,
        ):
            mock_fs.get_quote.return_value = {"status": "success", "from": "local"}
            out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        mock_fs.get_quote.assert_called_once_with("HK.00700")
        assert out["from"] == "local"

    @pytest.mark.asyncio
    async def test_remote_exception_degrades_local(self, remote_router):
        with (
            patch.object(remote_router, "_send_request", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch("backend.services.futu.futu_service") as mock_fs,
        ):
            mock_fs.get_quote.return_value = {"status": "success", "from": "local"}
            out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["from"] == "local"


class TestFetchFutuLocalBranch:
    """router 启用但主节点不健康 -> 直接本地降级。"""

    @pytest.mark.asyncio
    async def test_unhealthy_master_uses_local(self, remote_router):
        remote_router._nodes["futu_master"].status = "unhealthy"
        with (
            patch.object(remote_router, "_send_request", new=AsyncMock()) as mock_send,
            patch("backend.services.futu.futu_service") as mock_fs,
        ):
            mock_fs.get_history.return_value = {"status": "success", "from": "local"}
            out = await remote_router.fetch_futu("HISTORY", ticker="HK.00700", ktype="K_DAY", num=60)
        mock_send.assert_not_awaited()
        mock_fs.get_history.assert_called_once()
        assert out["from"] == "local"
