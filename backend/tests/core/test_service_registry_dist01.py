"""
DIST-01: ServiceRegistry 服务注册表单测
========================================

覆盖:
  - register / deregister
  - heartbeat (成功 / 节点不存在)
  - discover (按能力/区域过滤, draining 排除, dead 排除)
  - mark_draining / unmark_draining
  - cleanup_dead_nodes
  - get_cluster_overview
  - get_stats
  - NodeInfo 模型验证
  - 并发安全性
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.service_registry import (
    _KEY_DRAINING,
    _KEY_HEARTBEATS,
    _KEY_NODES,
    NodeInfo,
    NodeStatus,
    ServiceRegistry,
)

# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


def _make_node(
    node_id: str = "ca-primary",
    url: str = "http://38.60.126.42:8000",
    region: str = "us-west",
    weight: int = 10,
    capabilities: list = None,
) -> NodeInfo:
    return NodeInfo(
        node_id=node_id,
        url=url,
        region=region,
        weight=weight,
        capabilities=capabilities or ["yfinance", "quote"],
    )


class FakeRedis:
    """模拟 Redis 客户端，支持 pipeline + 常用操作"""

    def __init__(self):
        self._hash: dict[str, dict[str, str]] = {}
        self._zset: dict[str, dict[str, float]] = {}
        self._set: dict[str, set] = {}
        self._strings: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    def _ensure_hash(self, key):
        if key not in self._hash:
            self._hash[key] = {}

    def _ensure_zset(self, key):
        if key not in self._zset:
            self._zset[key] = {}

    def _ensure_set(self, key):
        if key not in self._set:
            self._set[key] = set()

    async def hset(self, key, field, value):
        self._ensure_hash(key)
        self._hash[key][field] = value

    async def hget(self, key, field):
        return self._hash.get(key, {}).get(field)

    async def hgetall(self, key):
        return dict(self._hash.get(key, {}))

    async def hdel(self, key, field):
        if key in self._hash and field in self._hash[key]:
            del self._hash[key][field]

    async def hincrbyfloat(self, key, field, amount):
        self._ensure_hash(key)
        current = float(self._hash[key].get(field, 0))
        self._hash[key][field] = str(current + amount)

    async def zadd(self, key, mapping):
        self._ensure_zset(key)
        self._zset[key].update(mapping)

    async def zrem(self, key, member):
        if key in self._zset:
            self._zset[key].pop(member, None)

    async def zrangebyscore(self, key, min_score, max_score):
        if key not in self._zset:
            return []
        if min_score == "-inf":
            min_score = float("-inf")
        if max_score == "+inf":
            max_score = float("inf")
        return [
            member
            for member, score in self._zset[key].items()
            if min_score <= score <= max_score
        ]

    async def sadd(self, key, *members):
        self._ensure_set(key)
        self._set[key].update(members)

    async def srem(self, key, *members):
        if key in self._set:
            self._set[key] -= set(members)

    async def sismember(self, key, member):
        return member in self._set.get(key, set())

    async def delete(self, key):
        self._hash.pop(key, None)
        self._zset.pop(key, None)
        self._set.pop(key, None)
        self._strings.pop(key, None)

    async def expire(self, key, ttl):
        self._ttls[key] = ttl

    async def get(self, key):
        return self._strings.get(key)

    async def set(self, key, value, ex=None):
        self._strings[key] = value
        if ex:
            self._ttls[key] = ex

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    """模拟 Redis Pipeline (支持 async with)"""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def hset(self, key, field, value):
        self._ops.append(("hset", key, field, value))

    def hget(self, key, field):
        self._ops.append(("hget", key, field))

    def hdel(self, key, field):
        self._ops.append(("hdel", key, field))

    def hincrbyfloat(self, key, field, amount):
        self._ops.append(("hincrbyfloat", key, field, amount))

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))

    def zrem(self, key, member):
        self._ops.append(("zrem", key, member))

    def sadd(self, key, *members):
        self._ops.append(("sadd", key, *members))

    def srem(self, key, *members):
        self._ops.append(("srem", key, *members))

    def delete(self, key):
        self._ops.append(("delete", key))

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))

    async def execute(self):
        results = []
        for op in self._ops:
            cmd = op[0]
            if cmd == "hset":
                await self._redis.hset(op[1], op[2], op[3])
                results.append(1)
            elif cmd == "hget":
                val = await self._redis.hget(op[1], op[2])
                results.append(val)
            elif cmd == "hdel":
                await self._redis.hdel(op[1], op[2])
                results.append(1)
            elif cmd == "hincrbyfloat":
                await self._redis.hincrbyfloat(op[1], op[2], op[3])
                results.append(1)
            elif cmd == "zadd":
                await self._redis.zadd(op[1], op[2])
                results.append(1)
            elif cmd == "zrem":
                await self._redis.zrem(op[1], op[2])
                results.append(1)
            elif cmd == "sadd":
                await self._redis.sadd(op[1], *op[2:])
                results.append(1)
            elif cmd == "srem":
                await self._redis.srem(op[1], *op[2:])
                results.append(1)
            elif cmd == "delete":
                await self._redis.delete(op[1])
                results.append(1)
            elif cmd == "expire":
                await self._redis.expire(op[1], op[2])
                results.append(1)
        self._ops.clear()
        return results


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def registry(fake_redis):
    return ServiceRegistry(redis_client=fake_redis, heartbeat_ttl=30)


# ─────────────────────────────────────────
#  NodeInfo 模型测试
# ─────────────────────────────────────────


class TestNodeInfo:
    def test_create_default(self):
        node = _make_node()
        assert node.node_id == "ca-primary"
        assert node.region == "us-west"
        assert node.weight == 10
        assert node.status == NodeStatus.ACTIVE
        assert "yfinance" in node.capabilities

    def test_is_alive_within_ttl(self):
        node = _make_node()
        node.last_heartbeat = time.time()
        assert node.is_alive(ttl=30) is True

    def test_is_alive_expired(self):
        node = _make_node()
        node.last_heartbeat = time.time() - 60  # 60s ago
        assert node.is_alive(ttl=30) is False

    def test_serialization_roundtrip(self):
        node = _make_node()
        json_str = node.model_dump_json()
        restored = NodeInfo.model_validate_json(json_str)
        assert restored.node_id == node.node_id
        assert restored.url == node.url
        assert restored.capabilities == node.capabilities

    def test_weight_bounds(self):
        with pytest.raises(Exception):
            NodeInfo(node_id="x", url="http://x", weight=0)
        with pytest.raises(Exception):
            NodeInfo(node_id="x", url="http://x", weight=101)


# ─────────────────────────────────────────
#  register / deregister
# ─────────────────────────────────────────


class TestRegisterDeregister:
    @pytest.mark.asyncio
    async def test_register_success(self, registry, fake_redis):
        node = _make_node()
        result = await registry.register(node)
        assert result is True

        # Hash 中应有节点数据
        stored = await fake_redis.hget(_KEY_NODES, "ca-primary")
        assert stored is not None
        data = json.loads(stored)
        assert data["node_id"] == "ca-primary"
        assert data["url"] == "http://38.60.126.42:8000"

        # ZSet 中应有心跳时间戳
        assert "ca-primary" in fake_redis._zset.get(_KEY_HEARTBEATS, {})

    @pytest.mark.asyncio
    async def test_register_overwrite(self, registry):
        """重复注册应覆盖旧数据"""
        node1 = _make_node(weight=5)
        await registry.register(node1)

        node2 = _make_node(weight=20)
        await registry.register(node2)

        stored = await registry.get_node("ca-primary")
        assert stored is not None
        assert stored.weight == 20

    @pytest.mark.asyncio
    async def test_deregister_success(self, registry, fake_redis):
        node = _make_node()
        await registry.register(node)
        result = await registry.deregister("ca-primary")
        assert result is True

        # Hash 和 ZSet 中应无数据
        stored = await fake_redis.hget(_KEY_NODES, "ca-primary")
        assert stored is None
        assert "ca-primary" not in fake_redis._zset.get(_KEY_HEARTBEATS, {})

    @pytest.mark.asyncio
    async def test_deregister_nonexistent(self, registry):
        """注销不存在的节点应返回 True (幂等)"""
        result = await registry.deregister("nonexistent")
        assert result is True


# ─────────────────────────────────────────
#  heartbeat
# ─────────────────────────────────────────


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_success(self, registry):
        node = _make_node()
        await registry.register(node)

        old_time = node.last_heartbeat
        await asyncio.sleep(0.01)
        result = await registry.heartbeat("ca-primary")
        assert result is True

        updated = await registry.get_node("ca-primary")
        assert updated.last_heartbeat > old_time

    @pytest.mark.asyncio
    async def test_heartbeat_with_metrics(self, registry):
        node = _make_node()
        await registry.register(node)
        await registry.heartbeat("ca-primary", metrics={"success_count": 1, "avg_latency_ms": 50.0})

        stats = await registry.get_stats("ca-primary")
        assert stats["success_count"] == 1.0
        assert stats["avg_latency_ms"] == 50.0

    @pytest.mark.asyncio
    async def test_heartbeat_unregistered_node(self, registry):
        result = await registry.heartbeat("nonexistent")
        assert result is False


# ─────────────────────────────────────────
#  discover
# ─────────────────────────────────────────


class TestDiscover:
    @pytest.mark.asyncio
    async def test_discover_all_active(self, registry):
        await registry.register(_make_node("node-1", capabilities=["yfinance"]))
        await registry.register(_make_node("node-2", capabilities=["akshare"]))

        nodes = await registry.discover()
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_discover_filter_by_capability(self, registry):
        await registry.register(_make_node("yf-node", capabilities=["yfinance", "quote"]))
        await registry.register(_make_node("ak-node", capabilities=["akshare", "southbound"]))

        nodes = await registry.discover(capability="yfinance")
        assert len(nodes) == 1
        assert nodes[0].node_id == "yf-node"

    @pytest.mark.asyncio
    async def test_discover_filter_by_region(self, registry):
        await registry.register(_make_node("ca-node", region="us-west"))
        await registry.register(_make_node("bj-node", region="cn-north", url="http://bj:8000"))

        nodes = await registry.discover(region="us-west")
        assert len(nodes) == 1
        assert nodes[0].node_id == "ca-node"

    @pytest.mark.asyncio
    async def test_discover_excludes_draining(self, registry):
        await registry.register(_make_node("active-node"))
        await registry.register(_make_node("draining-node"))
        await registry.mark_draining("draining-node")

        nodes = await registry.discover()
        assert len(nodes) == 1
        assert nodes[0].node_id == "active-node"

    @pytest.mark.asyncio
    async def test_discover_includes_draining_when_requested(self, registry):
        await registry.register(_make_node("active-node"))
        await registry.register(_make_node("draining-node"))
        await registry.mark_draining("draining-node")

        nodes = await registry.discover(include_draining=True)
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_discover_excludes_dead_nodes(self, registry):
        """心跳超时的节点不应被发现"""
        await registry.register(_make_node("alive-node"))

        # 注册一个心跳已过期的节点
        dead_node = _make_node("dead-node")
        dead_node.last_heartbeat = time.time() - 60  # 60s ago, TTL=30
        await registry.register(dead_node)
        # 手动将心跳时间戳设为过期
        registry._redis._zset[_KEY_HEARTBEATS]["dead-node"] = time.time() - 60
        # 更新 Hash 中的 last_heartbeat
        node_json = await registry._redis.hget(_KEY_NODES, "dead-node")
        node_data = json.loads(node_json)
        node_data["last_heartbeat"] = time.time() - 60
        await registry._redis.hset(_KEY_NODES, "dead-node", json.dumps(node_data))

        nodes = await registry.discover()
        assert len(nodes) == 1
        assert nodes[0].node_id == "alive-node"

    @pytest.mark.asyncio
    async def test_discover_sorted_by_weight(self, registry):
        await registry.register(_make_node("low-weight", weight=5))
        await registry.register(_make_node("high-weight", weight=20))
        await registry.register(_make_node("mid-weight", weight=10))

        nodes = await registry.discover()
        assert len(nodes) == 3
        assert nodes[0].node_id == "high-weight"
        assert nodes[1].node_id == "mid-weight"
        assert nodes[2].node_id == "low-weight"


# ─────────────────────────────────────────
#  mark_draining / unmark_draining
# ─────────────────────────────────────────


class TestDraining:
    @pytest.mark.asyncio
    async def test_mark_draining(self, registry, fake_redis):
        await registry.register(_make_node())
        result = await registry.mark_draining("ca-primary")
        assert result is True

        # Set 中应有节点
        assert "ca-primary" in fake_redis._set.get(_KEY_DRAINING, set())

        # 节点状态应为 draining
        node = await registry.get_node("ca-primary")
        assert node.status == NodeStatus.DRAINING

    @pytest.mark.asyncio
    async def test_unmark_draining(self, registry):
        await registry.register(_make_node())
        await registry.mark_draining("ca-primary")
        result = await registry.unmark_draining("ca-primary")
        assert result is True

        node = await registry.get_node("ca-primary")
        assert node.status == NodeStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_heartbeat_keeps_draining_status(self, registry):
        """draining 节点发心跳不应改变 draining 状态"""
        await registry.register(_make_node())
        await registry.mark_draining("ca-primary")
        await registry.heartbeat("ca-primary")

        node = await registry.get_node("ca-primary")
        assert node.status == NodeStatus.DRAINING


# ─────────────────────────────────────────
#  cleanup_dead_nodes
# ─────────────────────────────────────────


class TestCleanupDeadNodes:
    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, registry, fake_redis):
        await registry.register(_make_node("alive-node"))
        await registry.register(_make_node("dead-node"))

        # 手动将 dead-node 的心跳设为过期
        fake_redis._zset[_KEY_HEARTBEATS]["dead-node"] = time.time() - 60
        node_json = fake_redis._hash[_KEY_NODES]["dead-node"]
        node_data = json.loads(node_json)
        node_data["last_heartbeat"] = time.time() - 60
        fake_redis._hash[_KEY_NODES]["dead-node"] = json.dumps(node_data)

        cleaned = await registry.cleanup_dead_nodes()
        assert "dead-node" in cleaned
        assert "alive-node" not in cleaned

        # dead-node 应从 Hash 和 ZSet 中移除
        assert await fake_redis.hget(_KEY_NODES, "dead-node") is None
        assert "dead-node" not in fake_redis._zset.get(_KEY_HEARTBEATS, {})

    @pytest.mark.asyncio
    async def test_cleanup_no_dead_nodes(self, registry):
        await registry.register(_make_node())
        cleaned = await registry.cleanup_dead_nodes()
        assert cleaned == []

    @pytest.mark.asyncio
    async def test_cleanup_also_removes_draining_set(self, registry, fake_redis):
        """清理死节点时也应从 draining set 中移除"""
        await registry.register(_make_node("dead-draining"))
        await registry.mark_draining("dead-draining")

        # 设为过期
        fake_redis._zset[_KEY_HEARTBEATS]["dead-draining"] = time.time() - 60
        node_json = fake_redis._hash[_KEY_NODES]["dead-draining"]
        node_data = json.loads(node_json)
        node_data["last_heartbeat"] = time.time() - 60
        fake_redis._hash[_KEY_NODES]["dead-draining"] = json.dumps(node_data)

        cleaned = await registry.cleanup_dead_nodes()
        assert "dead-draining" in cleaned
        assert "dead-draining" not in fake_redis._set.get(_KEY_DRAINING, set())


# ─────────────────────────────────────────
#  get_cluster_overview
# ─────────────────────────────────────────


class TestClusterOverview:
    @pytest.mark.asyncio
    async def test_overview_counts(self, registry):
        await registry.register(_make_node("active-1", region="us-west"))
        await registry.register(_make_node("active-2", region="us-west"))
        await registry.register(_make_node("draining-1", region="cn-north", url="http://bj:8000"))
        await registry.mark_draining("draining-1")

        overview = await registry.get_cluster_overview()
        assert overview["total_nodes"] == 3
        assert overview["active_nodes"] == 2
        assert overview["draining_nodes"] == 1
        assert overview["regions"]["us-west"] == 2
        assert overview["regions"].get("cn-north", 0) == 0  # draining 不计入 active regions


# ─────────────────────────────────────────
#  get_stats
# ─────────────────────────────────────────


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_accumulate(self, registry):
        await registry.register(_make_node())
        await registry.heartbeat("ca-primary", metrics={"success_count": 1})
        await registry.heartbeat("ca-primary", metrics={"success_count": 1})

        stats = await registry.get_stats("ca-primary")
        assert stats["success_count"] == 2.0

    @pytest.mark.asyncio
    async def test_stats_empty_for_unknown(self, registry):
        stats = await registry.get_stats("nonexistent")
        assert stats == {}


# ─────────────────────────────────────────
#  异常处理
# ─────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_register_redis_failure(self):
        """Redis 异常时 register 应返回 False 而非抛异常"""
        bad_redis = MagicMock()
        bad_redis.pipeline = MagicMock(side_effect=Exception("Redis down"))
        reg = ServiceRegistry(redis_client=bad_redis)

        result = await reg.register(_make_node())
        assert result is False

    @pytest.mark.asyncio
    async def test_get_node_redis_failure(self):
        """Redis 异常时 get_node 应返回 None"""
        bad_redis = MagicMock()
        bad_redis.hget = AsyncMock(side_effect=Exception("Redis down"))
        reg = ServiceRegistry(redis_client=bad_redis)

        result = await reg.get_node("ca-primary")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_nodes_parse_error(self, registry, fake_redis):
        """损坏的 JSON 数据应被跳过而非崩溃"""
        fake_redis._hash[_KEY_NODES] = {
            "good-node": _make_node("good-node").model_dump_json(),
            "bad-node": "not-valid-json{{{",
        }
        nodes = await registry.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "good-node"
