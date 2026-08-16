"""ServiceRegistry 单元测试 (全 mock redis 客户端)"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice._internal.service_registry import (
    NodeInfo,
    NodeStatus,
    ServiceRegistry,
)


def _make_registry():
    r = MagicMock()
    # pipeline 上下文管理
    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    r.pipeline = MagicMock(return_value=pipe)
    # 真实 redis 客户端方法是协程
    r.hget = AsyncMock(return_value=None)
    r.hgetall = AsyncMock(return_value={})
    r.zadd = AsyncMock()
    r.zrangebyscore = AsyncMock(return_value=[])
    r.hdel = AsyncMock()
    r.sismember = AsyncMock(return_value=False)
    r.hincrbyfloat = AsyncMock()
    return ServiceRegistry(r), r, pipe


def _node(node_id="n1", capabilities=None, region="us-west", status=NodeStatus.ACTIVE, alive=True):
    n = NodeInfo(
        node_id=node_id,
        url=f"http://{node_id}:8001",
        region=region,
        capabilities=capabilities or ["yfinance"],
        status=status,
    )
    if not alive:
        n.last_heartbeat = 0.0
    return n


class TestRegisterDeregister:
    @pytest.mark.asyncio
    async def test_register_success(self):
        reg, r, pipe = _make_registry()
        ok = await reg.register(_node())
        assert ok is True
        pipe.hset.assert_called()
        pipe.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_register_failure(self):
        reg, r, pipe = _make_registry()
        pipe.execute = AsyncMock(side_effect=RuntimeError("redis err"))
        ok = await reg.register(_node())
        assert ok is False

    @pytest.mark.asyncio
    async def test_deregister_success(self):
        reg, r, pipe = _make_registry()
        ok = await reg.deregister("n1")
        assert ok is True
        pipe.hdel.assert_called()

    @pytest.mark.asyncio
    async def test_deregister_failure(self):
        reg, r, pipe = _make_registry()
        pipe.execute = AsyncMock(side_effect=ConnectionError("down"))
        ok = await reg.deregister("n1")
        assert ok is False


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_success_with_metrics(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=_node().model_dump_json().encode())
        ok = await reg.heartbeat("n1", metrics={"avg_latency_ms": 12.0})
        assert ok is True
        pipe.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_heartbeat_unregistered(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=None)
        ok = await reg.heartbeat("n1")
        assert ok is False

    @pytest.mark.asyncio
    async def test_heartbeat_exception(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(side_effect=ValueError("x"))
        ok = await reg.heartbeat("n1")
        assert ok is False


class TestDiscover:
    @pytest.mark.asyncio
    async def test_discover_filters_by_capability(self):
        reg, r, pipe = _make_registry()
        nodes = {
            b"n1": _node("n1", ["yfinance"]).model_dump_json().encode(),
            b"n2": _node("n2", ["futu"]).model_dump_json().encode(),
        }
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=False)
        result = await reg.discover(capability="yfinance")
        assert [n.node_id for n in result] == ["n1"]

    @pytest.mark.asyncio
    async def test_discover_excludes_draining(self):
        reg, r, pipe = _make_registry()
        nodes = {b"n1": _node("n1", status=NodeStatus.DRAINING).model_dump_json().encode()}
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=True)
        result = await reg.discover()
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_include_draining(self):
        reg, r, pipe = _make_registry()
        nodes = {b"n1": _node("n1", status=NodeStatus.DRAINING).model_dump_json().encode()}
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=True)
        result = await reg.discover(include_draining=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_discover_filters_region(self):
        reg, r, pipe = _make_registry()
        nodes = {b"n1": _node("n1", region="cn-north").model_dump_json().encode()}
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=False)
        result = await reg.discover(region="us-west")
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_sorts_by_weight(self):
        reg, r, pipe = _make_registry()
        n_hi = _node("hi", ["x"])
        n_hi.weight = 90
        n_lo = _node("lo", ["x"])
        n_lo.weight = 10
        nodes = {b"hi": n_hi.model_dump_json().encode(), b"lo": n_lo.model_dump_json().encode()}
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=False)
        result = await reg.discover(capability="x")
        assert [n.node_id for n in result] == ["hi", "lo"]

    @pytest.mark.asyncio
    async def test_discover_skips_dead(self):
        reg, r, pipe = _make_registry()
        nodes = {b"n1": _node("n1", alive=False).model_dump_json().encode()}
        r.hgetall = AsyncMock(return_value=nodes)
        r.sismember = AsyncMock(return_value=False)
        result = await reg.discover()
        assert result == []


class TestGetters:
    @pytest.mark.asyncio
    async def test_get_node_success(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=_node().model_dump_json().encode())
        n = await reg.get_node("n1")
        assert n.node_id == "n1"

    @pytest.mark.asyncio
    async def test_get_node_none(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=None)
        assert await reg.get_node("n1") is None

    @pytest.mark.asyncio
    async def test_get_node_parse_error(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=b"not json")
        assert await reg.get_node("n1") is None

    @pytest.mark.asyncio
    async def test_get_all_nodes_marks_dead(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(return_value={b"n1": _node("n1", alive=False).model_dump_json().encode()})
        r.sismember = AsyncMock(return_value=False)
        nodes = await reg.get_all_nodes()
        assert nodes[0].status == NodeStatus.DEAD

    @pytest.mark.asyncio
    async def test_get_all_nodes_marks_draining(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(return_value={b"n1": _node("n1").model_dump_json().encode()})
        r.sismember = AsyncMock(return_value=True)
        nodes = await reg.get_all_nodes()
        assert nodes[0].status == NodeStatus.DRAINING

    @pytest.mark.asyncio
    async def test_get_all_nodes_empty_on_error(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(side_effect=RuntimeError("x"))
        assert await reg.get_all_nodes() == []


class TestDraining:
    @pytest.mark.asyncio
    async def test_mark_draining_with_existing(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=_node().model_dump_json().encode())
        ok = await reg.mark_draining("n1")
        assert ok is True

    @pytest.mark.asyncio
    async def test_mark_draining_failure(self):
        reg, r, pipe = _make_registry()
        pipe.execute = AsyncMock(side_effect=Exception("x"))
        assert await reg.mark_draining("n1") is False

    @pytest.mark.asyncio
    async def test_unmark_draining(self):
        reg, r, pipe = _make_registry()
        r.hget = AsyncMock(return_value=_node(status=NodeStatus.DRAINING).model_dump_json().encode())
        assert await reg.unmark_draining("n1") is True

    @pytest.mark.asyncio
    async def test_unmark_draining_failure(self):
        reg, r, pipe = _make_registry()
        pipe.execute = AsyncMock(side_effect=Exception("x"))
        assert await reg.unmark_draining("n1") is False


class TestCleanupStatsOverview:
    @pytest.mark.asyncio
    async def test_cleanup_no_dead(self):
        reg, r, pipe = _make_registry()
        r.zrangebyscore.return_value = []
        assert await reg.cleanup_dead_nodes() == []

    @pytest.mark.asyncio
    async def test_cleanup_dead(self):
        reg, r, pipe = _make_registry()
        r.zrangebyscore.return_value = [b"n1", b"n2"]
        result = await reg.cleanup_dead_nodes()
        assert result == [b"n1", b"n2"]
        assert pipe.hdel.call_count == 2

    @pytest.mark.asyncio
    async def test_cleanup_failure(self):
        reg, r, pipe = _make_registry()
        r.zrangebyscore = AsyncMock(side_effect=RuntimeError("x"))
        assert await reg.cleanup_dead_nodes() == []

    @pytest.mark.asyncio
    async def test_update_stats(self):
        reg, r, pipe = _make_registry()
        await reg._update_stats("n1", {"avg_latency_ms": 10.0})
        pipe.hincrbyfloat.assert_called()

    @pytest.mark.asyncio
    async def test_update_stats_failure(self):
        reg, r, pipe = _make_registry()
        pipe.execute = AsyncMock(side_effect=Exception("x"))
        await reg._update_stats("n1", {"x": 1.0})  # 不抛

    @pytest.mark.asyncio
    async def test_get_stats(self):
        reg, r, pipe = _make_registry()
        # Redis 真实返回 bytes key/value，源码仅 float(value) 不 decode key
        r.hgetall = AsyncMock(return_value={b"avg_latency_ms": b"12.5"})
        stats = await reg.get_stats("n1")
        assert stats == {b"avg_latency_ms": 12.5}

    @pytest.mark.asyncio
    async def test_get_stats_empty(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(return_value={})
        assert await reg.get_stats("n1") == {}

    @pytest.mark.asyncio
    async def test_get_stats_failure(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(side_effect=Exception("x"))
        assert await reg.get_stats("n1") == {}

    @pytest.mark.asyncio
    async def test_cluster_overview(self):
        reg, r, pipe = _make_registry()
        r.hgetall = AsyncMock(
            return_value={
                b"n1": _node("n1", region="us-west").model_dump_json().encode(),
                b"n2": _node("n2", status=NodeStatus.DEAD, alive=False).model_dump_json().encode(),
            }
        )
        r.sismember = AsyncMock(return_value=False)
        ov = await reg.get_cluster_overview()
        assert ov["total_nodes"] == 2
        assert ov["active_nodes"] == 1
        assert ov["dead_nodes"] == 1
        assert ov["regions"]["us-west"] == 1
