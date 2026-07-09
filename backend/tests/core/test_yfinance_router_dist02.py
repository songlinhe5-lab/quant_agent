"""
DIST-02: YFinanceRouter 客户端路由器单测
==========================================

覆盖:
  - _refresh_nodes: 5s 缓存 + 从 ServiceRegistry 发现
  - _select_nodes: 加权排序 + 熔断过滤 + 轮询偏移
  - call: 成功路径 + failover + 限流不计熔断 + STALE 降级
  - _save_stale_cache / _fallback_stale: 缓存存档与降级
  - _record_failure: 内存熔断 (3 次触发 30s 冷却)
  - get_status: 状态查询
  - 0 节点场景
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.service_registry import NodeInfo, NodeStatus
from backend.core.yfinance_router import (
    _NODE_CACHE_TTL,
    _STALE_KEY_PREFIX,
    YFinanceRouter,
)

# ─────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────


def _make_node(
    node_id: str = "ca-yf-01",
    url: str = "http://38.60.126.42:8000",
    weight: int = 10,
    region: str = "us-west",
) -> NodeInfo:
    return NodeInfo(
        node_id=node_id,
        url=url,
        region=region,
        weight=weight,
        capabilities=["yfinance", "quote", "history"],
        status=NodeStatus.ACTIVE,
        last_heartbeat=time.time(),
    )


class FakeRedis:
    """简易 Redis mock"""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value


class FakeRegistry:
    """简易 ServiceRegistry mock"""

    def __init__(self, nodes=None):
        self._nodes = nodes or []

    async def discover(self, capability=None, region=None, include_draining=False):
        return self._nodes


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def fake_registry():
    return FakeRegistry()


@pytest.fixture
def router(fake_registry, fake_redis):
    return YFinanceRouter(
        service_registry=fake_registry,
        redis_client=fake_redis,
        hmac_secret="test-secret",
    )


# ─────────────────────────────────────────
#  _refresh_nodes
# ─────────────────────────────────────────


class TestRefreshNodes:
    @pytest.mark.asyncio
    async def test_refresh_from_registry(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1"), _make_node("node-2")]
        nodes = await router._refresh_nodes()
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_refresh_uses_local_cache(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1")]
        nodes1 = await router._refresh_nodes()
        assert len(nodes1) == 1

        fake_registry._nodes = [_make_node("node-1"), _make_node("node-2")]
        nodes2 = await router._refresh_nodes()
        assert len(nodes2) == 1  # 仍返回缓存

    @pytest.mark.asyncio
    async def test_refresh_after_cache_expiry(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1")]
        await router._refresh_nodes()

        router._cache_refreshed_at = time.time() - _NODE_CACHE_TTL - 1
        fake_registry._nodes = [_make_node("node-1"), _make_node("node-2")]
        nodes = await router._refresh_nodes()
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_refresh_empty_registry(self, router, fake_registry):
        fake_registry._nodes = []
        nodes = await router._refresh_nodes()
        assert nodes == []


# ─────────────────────────────────────────
#  _select_nodes
# ─────────────────────────────────────────


class TestSelectNodes:
    @pytest.mark.asyncio
    async def test_select_sorted_by_weight(self, router, fake_registry):
        fake_registry._nodes = [
            _make_node("low", weight=5),
            _make_node("high", weight=20),
            _make_node("mid", weight=10),
        ]
        nodes = await router._select_nodes()
        assert len(nodes) == 3
        node_ids = [n.node_id for n in nodes]
        assert "high" in node_ids

    @pytest.mark.asyncio
    async def test_select_filters_circuit_open(self, router, fake_registry):
        fake_registry._nodes = [_make_node("open-node"), _make_node("healthy-node")]
        router._node_circuit_until["open-node"] = time.time() + 30

        nodes = await router._select_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "healthy-node"

    @pytest.mark.asyncio
    async def test_select_filters_excessive_failures(self, router, fake_registry):
        fake_registry._nodes = [_make_node("failing-node"), _make_node("good-node")]
        router._node_fail_counts["failing-node"] = 3

        nodes = await router._select_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "good-node"

    @pytest.mark.asyncio
    async def test_select_empty_when_all_filtered(self, router, fake_registry):
        fake_registry._nodes = [_make_node("only-node")]
        router._node_circuit_until["only-node"] = time.time() + 30

        nodes = await router._select_nodes()
        assert nodes == []

    @pytest.mark.asyncio
    async def test_select_round_robin_rotation(self, router, fake_registry):
        fake_registry._nodes = [
            _make_node("a", weight=10),
            _make_node("b", weight=10),
            _make_node("c", weight=10),
        ]
        first_nodes = []
        for _ in range(6):
            nodes = await router._select_nodes()
            first_nodes.append(nodes[0].node_id)

        unique_firsts = set(first_nodes)
        assert len(unique_firsts) > 1


# ─────────────────────────────────────────
#  call: 成功路径
# ─────────────────────────────────────────


class TestCallSuccess:
    @pytest.mark.asyncio
    async def test_call_success_first_node(self, router, fake_registry, fake_redis):
        fake_registry._nodes = [_make_node("node-1")]

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "success", "data": {"price": 150.0}}
        mock_resp.raise_for_status = MagicMock()

        router._http_client = AsyncMock()
        router._http_client.post = AsyncMock(return_value=mock_resp)

        result = await router.call("yfinance", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert result["status"] == "success"
        assert result["data"]["price"] == 150.0

        cached = fake_redis._store.get(f"{_STALE_KEY_PREFIX}:quote:AAPL")
        assert cached is not None
        assert json.loads(cached)["status"] == "success"

    @pytest.mark.asyncio
    async def test_call_success_resets_fail_count(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1")]
        router._node_fail_counts["node-1"] = 2

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "success", "data": {}}
        mock_resp.raise_for_status = MagicMock()
        router._http_client = AsyncMock()
        router._http_client.post = AsyncMock(return_value=mock_resp)

        await router.call("yfinance", {"ticker": "AAPL"})
        assert router._node_fail_counts["node-1"] == 0


# ─────────────────────────────────────────
#  call: failover
# ─────────────────────────────────────────


class TestCallFailover:
    @pytest.mark.asyncio
    async def test_call_failover_tries_all_nodes(self, router, fake_registry):
        """所有节点失败时应尝试每个节点并最终降级"""
        fake_registry._nodes = [
            _make_node("fail-1", url="http://fail-1:8000", weight=20),
            _make_node("fail-2", url="http://fail-2:8000", weight=5),
        ]

        urls_called = []

        async def mock_post(url, json=None, headers=None):
            urls_called.append(url)
            raise Exception("Connection refused")

        router._http_client = AsyncMock()
        router._http_client.post = mock_post

        # 无 STALE 缓存，应返回 error
        result = await router.call("yfinance", {"ticker": "AAPL"}, cache_key="quote:TEST")
        assert result["degraded"] is True
        # 两个节点都应被尝试
        assert len(urls_called) == 2
        assert any("fail-1" in u for u in urls_called)
        assert any("fail-2" in u for u in urls_called)

    @pytest.mark.asyncio
    async def test_call_rate_limit_no_circuit(self, router, fake_registry):
        fake_registry._nodes = [_make_node("limited-node"), _make_node("ok-node")]

        async def mock_post(url, json=None, headers=None):
            if "limited-node" in url:
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "status": "error",
                    "error_category": "rate_limit",
                    "message": "429 Too Many Requests",
                }
                mock_resp.raise_for_status = MagicMock()
                return mock_resp
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"status": "success", "data": {}}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        router._http_client = AsyncMock()
        router._http_client.post = mock_post

        result = await router.call("yfinance", {"ticker": "AAPL"})
        assert result["status"] == "success"
        assert router._node_fail_counts.get("limited-node", 0) == 0


# ─────────────────────────────────────────
#  call: STALE 降级
# ─────────────────────────────────────────


class TestStaleFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_stale_cache(self, router, fake_registry, fake_redis):
        fake_registry._nodes = [_make_node("only-node")]

        stale_data = {"status": "success", "data": {"price": 140.0}, "cached": True}
        fake_redis._store[f"{_STALE_KEY_PREFIX}:quote:AAPL"] = json.dumps(stale_data)

        router._http_client = AsyncMock()
        router._http_client.post = AsyncMock(side_effect=Exception("All down"))

        result = await router.call("yfinance", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert result["status"] == "success"
        assert result["degraded"] is True
        assert result["data"]["price"] == 140.0

    @pytest.mark.asyncio
    async def test_fallback_no_cache_key(self, router, fake_registry):
        fake_registry._nodes = []

        result = await router.call("yfinance", {"ticker": "AAPL"})
        assert result["status"] == "error"
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_fallback_no_stale_data(self, router, fake_registry, fake_redis):
        fake_registry._nodes = [_make_node("only-node")]

        router._http_client = AsyncMock()
        router._http_client.post = AsyncMock(side_effect=Exception("Down"))

        result = await router.call("yfinance", {"ticker": "AAPL"}, cache_key="quote:NEW")
        assert result["status"] == "error"
        assert result["degraded"] is True
        assert "无 STALE 缓存" in result["message"]


# ─────────────────────────────────────────
#  _record_failure: 内存熔断
# ─────────────────────────────────────────


class TestMemoryCircuit:
    def test_record_failure_triggers_circuit(self, router):
        router._record_failure("node-1")
        assert router._node_fail_counts["node-1"] == 1
        assert "node-1" not in router._node_circuit_until

        router._record_failure("node-1")
        assert router._node_fail_counts["node-1"] == 2

        router._record_failure("node-1")
        assert router._node_fail_counts["node-1"] == 3
        assert "node-1" in router._node_circuit_until

    def test_record_success_resets_count(self, router):
        router._record_failure("node-1")
        router._record_failure("node-1")
        router._record_success("node-1")
        assert router._node_fail_counts["node-1"] == 0


# ─────────────────────────────────────────
#  get_status
# ─────────────────────────────────────────


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_status_with_nodes(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1"), _make_node("node-2")]
        router._node_fail_counts["node-1"] = 1

        status = await router.get_status()
        assert status["total_nodes"] == 2
        assert status["available_nodes"] == 2
        assert len(status["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_status_with_circuit_open(self, router, fake_registry):
        fake_registry._nodes = [_make_node("node-1")]
        router._node_circuit_until["node-1"] = time.time() + 30

        status = await router.get_status()
        assert status["available_nodes"] == 0
        assert status["nodes"][0]["is_circuit_open"] is True


# ─────────────────────────────────────────
#  HMAC 签名
# ─────────────────────────────────────────


class TestHMACSignature:
    def test_sign_request_deterministic(self, router):
        sig1 = router._sign_request({"ticker": "AAPL"}, "1234567890")
        sig2 = router._sign_request({"ticker": "AAPL"}, "1234567890")
        assert sig1 == sig2

    def test_sign_request_different_payload(self, router):
        sig1 = router._sign_request({"ticker": "AAPL"}, "1234567890")
        sig2 = router._sign_request({"ticker": "GOOG"}, "1234567890")
        assert sig1 != sig2

    def test_sign_request_no_secret(self, fake_registry, fake_redis):
        router = YFinanceRouter(fake_registry, fake_redis, hmac_secret="")
        sig = router._sign_request({"ticker": "AAPL"}, "1234567890")
        assert isinstance(sig, str)


# ─────────────────────────────────────────
#  close
# ─────────────────────────────────────────


class TestClose:
    @pytest.mark.asyncio
    async def test_close_with_client(self, router):
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        router._http_client = mock_client
        await router.close()
        mock_client.aclose.assert_called_once()
        assert router._http_client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self, router):
        router._http_client = None
        await router.close()
