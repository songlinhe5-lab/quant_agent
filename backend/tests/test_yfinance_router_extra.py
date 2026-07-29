"""
DIST-02: YFinanceRouter 深度单测（补齐路由/熔断/降级分支）
========================================================

覆盖 yfinance_router.py:
- _refresh_nodes 本地 5s 缓存命中 / 过期
- _select_nodes 熔断过滤 / 失败计数过滤 / 加权轮询排序
- call 成功存档 / 无节点降级 / 限流 failover / 异常记录失败
- _record_failure 三连触发内存熔断 / _record_success 重置
- _save_stale_cache / _fallback_stale 各分支
- _send_request / _sign_request
- get_status / close
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.service_registry import NodeInfo
from backend.core.yfinance_router import YFinanceRouter


def _node(nid, url="http://node", weight=10, region="us-west"):
    return NodeInfo(node_id=nid, url=url, weight=weight, region=region)


@pytest.fixture
def redis():
    return AsyncMock()


@pytest.fixture
def registry():
    r = AsyncMock()
    r.discover = AsyncMock(return_value=[_node("n1", weight=20), _node("n2", weight=10)])
    return r


@pytest.fixture
def router(registry, redis):
    return YFinanceRouter(registry, redis, hmac_secret="secret")


class TestRefreshNodes:
    async def test_cache_hit_avoid_redis(self, router, registry):
        await router._refresh_nodes()
        await router._refresh_nodes()
        assert registry.discover.await_count == 1

    async def test_cache_expired_refreshes(self, router, registry):
        await router._refresh_nodes()
        router._cache_refreshed_at = 0.0  # 模拟过期
        await router._refresh_nodes()
        assert registry.discover.await_count == 2


class TestSelectNodes:
    async def test_filters_circuit_breaker(self, router):
        router._node_circuit_until["n1"] = time.time() + 100
        nodes = await router._select_nodes()
        ids = [n.node_id for n in nodes]
        assert "n1" not in ids
        assert "n2" in ids

    async def test_filters_fail_count(self, router):
        router._node_fail_counts["n1"] = 3
        nodes = await router._select_nodes()
        ids = [n.node_id for n in nodes]
        assert "n1" not in ids

    async def test_weighted_and_rr(self, router):
        nodes = await router._select_nodes()
        assert len(nodes) == 2
        assert {n.node_id for n in nodes} == {"n1", "n2"}

    async def test_empty_when_no_registry_nodes(self, router, registry):
        registry.discover.return_value = []
        assert await router._select_nodes() == []


class TestCall:
    async def test_success_saves_stale(self, router, redis):
        router._send_request = AsyncMock(return_value={"status": "success", "data": 1})
        res = await router.call("quote", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert res["status"] == "success"
        redis.set.assert_awaited_once()

    async def test_no_nodes_falls_back(self, router, registry, redis):
        registry.discover.return_value = []
        redis.get.return_value = None
        res = await router.call("quote", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert res["degraded"] is True

    async def test_rate_limit_category_failover(self, router, redis):
        router._send_request = AsyncMock(
            return_value={"status": "error", "error_category": "rate_limit", "message": "x"}
        )
        redis.get.return_value = None
        res = await router.call("quote", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert res["degraded"] is True

    async def test_exception_records_failure(self, router, redis):
        router._send_request = AsyncMock(side_effect=Exception("boom"))
        redis.get.return_value = None
        res = await router.call("quote", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert res["degraded"] is True
        assert router._node_fail_counts["n1"] >= 1

    async def test_all_fail_stale_hit(self, router, redis):
        router._send_request = AsyncMock(return_value={"status": "error", "message": "x"})
        stale = {"status": "success", "data": 42}
        redis.get.return_value = __import__("json").dumps(stale)
        res = await router.call("quote", {"ticker": "AAPL"}, cache_key="quote:AAPL")
        assert res["degraded"] is True
        assert res["stale_source"] is True
        assert res["data"] == 42


class TestFailureCircuit:
    def test_record_failure_triggers_circuit(self, router):
        for _ in range(3):
            router._record_failure("n1")
        assert router._node_circuit_until["n1"] > time.time()

    def test_record_success_resets(self, router):
        router._record_failure("n1")
        router._record_failure("n1")
        router._record_success("n1")
        assert router._node_fail_counts["n1"] == 0


class TestStaleCache:
    async def test_save_stale_cache_redis_error(self, router, redis):
        redis.set.side_effect = Exception("redis down")
        await router._save_stale_cache("k", {"a": 1})  # 不应抛异常

    async def test_fallback_no_cache_key(self, router):
        res = await router._fallback_stale(None)
        assert res["status"] == "error" and res["degraded"] is True

    async def test_fallback_stale_hit(self, router, redis):
        redis.get.return_value = __import__("json").dumps({"status": "success", "v": 1})
        res = await router._fallback_stale("quote:AAPL")
        assert res["degraded"] is True and res["stale_source"] is True

    async def test_fallback_redis_error(self, router, redis):
        redis.get.side_effect = Exception("boom")
        res = await router._fallback_stale("quote:AAPL")
        assert res["status"] == "error" and res["degraded"] is True


class TestHttpSend:
    def test_sign_request_deterministic(self, router):
        sig1 = router._sign_request({"a": 1}, "123")
        sig2 = router._sign_request({"a": 1}, "123")
        assert sig1 == sig2 and len(sig1) == 64

    async def test_send_request_ok(self, router):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"status": "success"}
        client = AsyncMock()
        client.post = AsyncMock(return_value=resp)
        router._http_client = client
        node = _node("n1")
        res = await router._send_request(node, "quote", {"ticker": "AAPL"})
        assert res["status"] == "success"
        # HMAC 头应被写入
        _, kwargs = client.post.call_args
        assert "X-Data-Source-Signature" in kwargs["headers"]

    def test_ensure_http_client_creates(self, router):
        router._http_client = None
        router._ensure_http_client()
        assert router._http_client is not None


class TestStatusAndClose:
    async def test_get_status(self, router):
        status = await router.get_status()
        assert status["total_nodes"] == 2
        assert "nodes" in status

    async def test_close_with_client(self, router):
        client = AsyncMock()
        router._http_client = client
        await router.close()
        client.aclose.assert_awaited_once()

    async def test_close_no_client(self, router):
        router._http_client = None
        await router.close()  # 不应抛异常
