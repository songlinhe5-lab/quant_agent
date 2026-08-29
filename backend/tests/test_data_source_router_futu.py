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
import time
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
    """BE-ARCH-07b/2026-08-07: 仅远程，移除本地 futu_service 降级通道。
    router 禁用 -> 直接返回 error（不再降级本地 SDK）。"""

    @pytest.mark.asyncio
    async def test_disabled_returns_error_no_local_fallback(self):
        with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
            r = DataSourceRouter()
        out = await r.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["status"] == "error"
        assert "local SDK disabled" in out["message"]


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
    async def test_remote_capital_distribution_writes_redis_cache(self, remote_router):
        """CAPITAL_DISTRIBUTION 属低频扩展行情, 成功响应应写入 Redis 缓存。"""
        fake_resp = {
            "status": "success",
            "data": {"status": "success", "data": {"main_net": 4000000, "retail_net": 3000000}},
        }
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)
        fake_redis.set = AsyncMock()
        with (
            patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fake_resp)),
            patch(
                "backend.core.redis_client.redis_client",
                fake_redis,
                create=True,
            ),
        ):
            out = await remote_router.fetch_futu("CAPITAL_DISTRIBUTION", ticker="HK.00772")
        assert out["status"] == "success"
        # 应写入 Redis 缓存
        fake_redis.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remote_capital_distribution_hits_redis_cache(self, remote_router):
        """CAPITAL_DISTRIBUTION 命中 Redis 缓存时应直接返回, 不再发远程请求。"""
        cached = {"status": "success", "source": "futu", "data": {"main_net": 4000000, "retail_net": 3000000}}
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=__import__("json").dumps(cached))
        fake_redis.set = AsyncMock()
        with (
            patch.object(remote_router, "_send_request", new=AsyncMock()) as mock_send,
            patch(
                "backend.core.redis_client.redis_client",
                fake_redis,
                create=True,
            ),
        ):
            out = await remote_router.fetch_futu("CAPITAL_DISTRIBUTION", ticker="HK.00772")
        assert out["status"] == "success"
        # 命中缓存, 不发送远程请求
        mock_send.assert_not_awaited()
        assert out["cached"] is True

    @pytest.mark.asyncio
    async def test_remote_snapshot_maps_to_snapshot(self, remote_router):
        fake_resp = {"status": "success", "data": {"status": "success", "data": []}}
        with patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fake_resp)) as mock_send:
            await remote_router.fetch_futu("MARKET_SNAPSHOTS", tickers=["HK.00700"])
        sent_payload = mock_send.await_args.args[2]
        assert sent_payload["action"] == "SNAPSHOT"

    @pytest.mark.asyncio
    async def test_remote_failure_returns_error_no_local(self, remote_router):
        fail_resp = {"status": "error", "message": "subservice down"}
        with patch.object(remote_router, "_send_request", new=AsyncMock(return_value=fail_resp)):
            out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["status"] == "error"
        # BE-ARCH-07b: 远程子服务失败时应透传其真实错误信封（message=subservice down），
        # 不再被 router 硬编码 'local SDK disabled' 覆盖，便于上层诊断
        assert out["message"] == "subservice down"
        assert out["source"] == "futu"

    @pytest.mark.asyncio
    async def test_remote_exception_returns_error_no_local(self, remote_router):
        with patch.object(remote_router, "_send_request", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["status"] == "error"
        assert "local SDK disabled" in out["message"]


class TestFetchFutuLocalBranch:
    """BE-ARCH-07b: router 启用但主节点不健康 -> 直接返回 error（无本地降级）。"""

    @pytest.mark.asyncio
    async def test_unhealthy_master_returns_error(self, remote_router):
        remote_router._nodes["futu_master"].status = "unhealthy"
        # 源码语义: 节点不健康仍会发起远程请求（由 router 层熔断/降级处理），
        # 远程失败后返回 error（无本地 SDK 降级兜底）。
        with patch.object(
            remote_router, "_send_request", new=AsyncMock(return_value={"status": "error", "message": "node down"})
        ) as mock_send:
            out = await remote_router.fetch_futu("HISTORY", ticker="HK.00700", ktype="K_DAY", num=60)
        mock_send.assert_awaited_once()
        assert out["status"] == "error"
        # 远程失败后透传子服务真实错误信封（message=node down），无本地 SDK 降级兜底
        assert out["message"] == "node down"
        assert out["source"] == "futu"


class TestFutuBreakerMessageSeparation:
    """action 级熔断与节点级熔断必须报不同的错。

    旧实现把两者合并为同一条 "No healthy Futu remote node (local SDK disabled)"，
    导致「单个 action 冷却」被误报成「整节点不可用」——监控显示 healthy 却在报
    节点挂，严重误导排查方向（2026-08-29 实战：QUOTE 冷却被误判为 Futu 节点宕机）。
    """

    @pytest.mark.asyncio
    async def test_action_cooldown_is_not_reported_as_node_down(self, remote_router):
        node = remote_router._nodes["futu_master"]
        node.status = "healthy"  # 节点整体健康，仅单个 action 在冷却
        node.action_breaker_until["QUOTE"] = time.time() + 30

        out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["status"] == "error"
        assert "No healthy Futu remote node" not in out["message"]
        assert "QUOTE" in out["message"]

    @pytest.mark.asyncio
    async def test_action_cooldown_does_not_block_other_actions(self, remote_router):
        """QUOTE 冷却不得误伤同节点其它 action（action 级隔离仍然有效）"""
        node = remote_router._nodes["futu_master"]
        node.status = "healthy"
        node.action_breaker_until["QUOTE"] = time.time() + 30

        ok_resp = {"status": "success", "data": {"status": "success", "data": {"last_price": 12}}}
        with patch.object(remote_router, "_send_request", new=AsyncMock(return_value=ok_resp)):
            out = await remote_router.fetch_futu("HISTORY", ticker="HK.00700")
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_node_level_breaker_reports_node_fault(self, remote_router):
        """整节点熔断（进程级故障）须与单 action 冷却明确区分开"""
        node = remote_router._nodes["futu_master"]
        node.status = "unhealthy"
        node.circuit_breaker_until = time.time() + 60  # 冷却中，半开未到期

        out = await remote_router.fetch_futu("QUOTE", ticker="HK.00700")
        assert out["status"] == "error"
        assert "节点熔断中" in out["message"]
        assert "No healthy Futu remote node" not in out["message"]
