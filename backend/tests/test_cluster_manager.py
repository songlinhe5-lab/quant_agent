"""
ClusterManager 集成测试

覆盖:
- _refresh_from_redis: mock Redis scan, 验证节点发现
- _rebuild_pools: 验证 collector -> [node_ids] 映射
- call_collector failover: mock httpx, 第一次失败第二次成功
- _mark_unhealthy / _mark_healthy: 连续失败 3 次降级, 恢复后升级
- get_cluster_status: 返回完整集群状态
- _parse_static_slaves: SLAVE_NODES 环境变量解析
- get_available_nodes: 过滤不健康节点
"""

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.workers.cluster_manager import (
    RECOVERY_INTERVAL,
    ClusterManager,
    SlaveNode,
)

# ==========================================
# Fixtures
# ==========================================


@pytest.fixture
def manager():
    """创建干净的 ClusterManager 实例"""
    cm = ClusterManager()
    return cm


@pytest.fixture
def sample_nodes():
    """构造测试节点数据"""
    return {
        "slave-1": SlaveNode(
            node_id="slave-1",
            host="10.0.0.1",
            port=8001,
            collectors=["yfinance", "finnhub"],
            status="healthy",
            last_seen=time.time(),
        ),
        "slave-2": SlaveNode(
            node_id="slave-2",
            host="10.0.0.2",
            port=8001,
            collectors=["futu"],
            status="healthy",
            last_seen=time.time(),
        ),
    }


# ==========================================
# SlaveNode 单元测试
# ==========================================


class TestSlaveNode:
    """SlaveNode 数据类属性测试"""

    def test_base_url(self):
        node = SlaveNode(node_id="test", host="10.0.0.1", port=8001, collectors=[])
        assert node.base_url == "http://10.0.0.1:8001"

    def test_is_available_healthy(self):
        node = SlaveNode(node_id="test", host="h", port=1, collectors=[], status="healthy")
        assert node.is_available is True

    def test_is_available_unhealthy_recent(self):
        node = SlaveNode(
            node_id="test",
            host="h",
            port=1,
            collectors=[],
            status="unhealthy",
            last_failure_time=time.time(),
        )
        assert node.is_available is False

    def test_is_available_unhealthy_recovered(self):
        node = SlaveNode(
            node_id="test",
            host="h",
            port=1,
            collectors=[],
            status="unhealthy",
            last_failure_time=time.time() - RECOVERY_INTERVAL - 1,
        )
        assert node.is_available is True

    def test_is_available_unknown(self):
        node = SlaveNode(node_id="test", host="h", port=1, collectors=[], status="unknown")
        assert node.is_available is False


# ==========================================
# _parse_static_slaves 测试
# ==========================================


class TestParseStaticSlaves:
    """SLAVE_NODES 环境变量解析"""

    def test_empty_env(self, manager):
        with patch.dict(os.environ, {"SLAVE_NODES": ""}):
            manager._parse_static_slaves()
        assert len(manager._nodes) == 0

    def test_single_slave(self, manager):
        with patch.dict(os.environ, {"SLAVE_NODES": "http://overseas-1:8001"}):
            manager._parse_static_slaves()
        assert "overseas-1" in manager._nodes
        node = manager._nodes["overseas-1"]
        assert node.host == "overseas-1"
        assert node.port == 8001
        assert node.status == "unknown"

    def test_multiple_slaves(self, manager):
        with patch.dict(os.environ, {"SLAVE_NODES": "http://node-a:8001,http://node-b:8002"}):
            manager._parse_static_slaves()
        assert len(manager._nodes) == 2
        assert "node-a" in manager._nodes
        assert "node-b" in manager._nodes
        assert manager._nodes["node-b"].port == 8002

    def test_invalid_url_skipped(self, manager):
        with patch.dict(os.environ, {"SLAVE_NODES": "not-a-url,http://valid:8001"}):
            manager._parse_static_slaves()
        # not-a-url 会被 urlparse 解析为 scheme="not-a-url", 但 hostname 为 None -> localhost
        assert "valid" in manager._nodes


# ==========================================
# _rebuild_pools 测试
# ==========================================


class TestRebuildPools:
    """collector -> [node_ids] 映射重建"""

    def test_basic_pool(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        manager._rebuild_pools()

        assert "yfinance" in manager._pools
        assert "slave-1" in manager._pools["yfinance"]
        assert "finnhub" in manager._pools
        assert "futu" in manager._pools
        assert "slave-2" in manager._pools["futu"]

    def test_empty_nodes(self, manager):
        manager._nodes = {}
        manager._rebuild_pools()
        assert manager._pools == {}

    def test_no_collectors(self, manager):
        manager._nodes = {
            "slave-x": SlaveNode(node_id="slave-x", host="h", port=1, collectors=[]),
        }
        manager._rebuild_pools()
        assert manager._pools == {}

    def test_shared_collector(self, manager):
        """两个 slave 都支持 yfinance"""
        manager._nodes = {
            "s1": SlaveNode(node_id="s1", host="h1", port=1, collectors=["yfinance"]),
            "s2": SlaveNode(node_id="s2", host="h2", port=1, collectors=["yfinance"]),
        }
        manager._rebuild_pools()
        assert len(manager._pools["yfinance"]) == 2


# ==========================================
# get_pool / get_available_nodes 测试
# ==========================================


class TestServicePool:
    """服务池查询与过滤"""

    def test_get_pool(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        pool = manager.get_pool("yfinance")
        assert len(pool) == 1
        assert pool[0].node_id == "slave-1"

    def test_get_pool_nonexistent(self, manager):
        assert manager.get_pool("nonexistent") == []

    def test_get_available_filters_unhealthy(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        # 标记 slave-1 不健康
        sample_nodes["slave-1"].status = "unhealthy"
        sample_nodes["slave-1"].last_failure_time = time.time()
        manager._rebuild_pools()

        available = manager.get_available_nodes("yfinance")
        assert len(available) == 0

    def test_get_available_includes_healthy(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        available = manager.get_available_nodes("yfinance")
        assert len(available) == 1


# ==========================================
# _mark_healthy / _mark_unhealthy 测试
# ==========================================


class TestHealthTracking:
    """健康追踪: 连续失败降级, 恢复升级"""

    def test_mark_unhealthy_threshold(self, manager):
        node = SlaveNode(node_id="test", host="h", port=1, collectors=[], status="healthy")
        # 前两次失败不降级
        manager._mark_unhealthy(node)
        assert node.status == "healthy"
        assert node.consecutive_failures == 1

        manager._mark_unhealthy(node)
        assert node.status == "healthy"
        assert node.consecutive_failures == 2

        # 第三次失败降级
        manager._mark_unhealthy(node)
        assert node.status == "unhealthy"
        assert node.consecutive_failures == 3

    def test_mark_healthy_recovery(self, manager):
        node = SlaveNode(
            node_id="test",
            host="h",
            port=1,
            collectors=[],
            status="unhealthy",
            consecutive_failures=5,
        )
        manager._mark_healthy(node)
        assert node.status == "healthy"
        assert node.consecutive_failures == 0

    def test_mark_healthy_idempotent(self, manager):
        node = SlaveNode(node_id="test", host="h", port=1, collectors=[], status="healthy")
        manager._mark_healthy(node)
        assert node.status == "healthy"
        assert node.consecutive_failures == 0


# ==========================================
# _refresh_from_redis 测试
# ==========================================


class TestRefreshFromRedis:
    """Redis 扫描发现从节点"""

    @pytest.mark.asyncio
    async def test_discover_nodes(self, manager):
        """模拟 Redis scan 返回节点数据"""
        node_data = json.dumps(
            {
                "node_id": "discovered-1",
                "role": "slave",
                "host": "10.0.0.5",
                "port": 8001,
                "collectors": ["yfinance"],
            }
        )

        mock_redis = AsyncMock()
        # scan 返回: (cursor, keys) - 第一次返回 key, 第二次 cursor=0 结束
        mock_redis.scan = AsyncMock(
            side_effect=[
                (1, [b"quant:node:discovered-1"]),
                (0, []),
            ]
        )
        mock_redis.get = AsyncMock(return_value=node_data)

        with patch("backend.workers.cluster_manager.redis_client", mock_redis, create=True):
            with patch("backend.core.redis_client.redis_client", mock_redis, create=True):
                await manager._refresh_from_redis()

        assert "discovered-1" in manager._nodes
        node = manager._nodes["discovered-1"]
        assert node.host == "10.0.0.5"
        assert node.port == 8001
        assert "yfinance" in node.collectors

    @pytest.mark.asyncio
    async def test_skip_master_nodes(self, manager):
        """跳过 role=master 的节点"""
        master_data = json.dumps(
            {
                "node_id": "master-1",
                "role": "master",
                "host": "10.0.0.1",
                "port": 8000,
                "collectors": [],
            }
        )

        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[
                (1, [b"quant:node:master-1"]),
                (0, []),
            ]
        )
        mock_redis.get = AsyncMock(return_value=master_data)

        with patch("backend.workers.cluster_manager.redis_client", mock_redis, create=True):
            with patch("backend.core.redis_client.redis_client", mock_redis, create=True):
                await manager._refresh_from_redis()

        assert "master-1" not in manager._nodes

    @pytest.mark.asyncio
    async def test_skip_invalid_json(self, manager):
        """跳过无效 JSON 数据"""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[
                (1, [b"quant:node:bad-node"]),
                (0, []),
            ]
        )
        mock_redis.get = AsyncMock(return_value="not-valid-json")

        with patch("backend.workers.cluster_manager.redis_client", mock_redis, create=True):
            with patch("backend.core.redis_client.redis_client", mock_redis, create=True):
                await manager._refresh_from_redis()

        assert "bad-node" not in manager._nodes


# ==========================================
# call_collector failover 测试
# ==========================================


class TestCallCollector:
    """带 failover 的 HTTP 代理调用"""

    @pytest.mark.asyncio
    async def test_call_success(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"price": 100}}
        mock_response.raise_for_status = MagicMock()
        manager._http_client.post = AsyncMock(return_value=mock_response)

        result = await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})
        assert result["data"]["price"] == 100
        assert sample_nodes["slave-1"].status == "healthy"

    @pytest.mark.asyncio
    async def test_call_failover(self, manager, sample_nodes):
        """第一个节点失败, 自动切换到第二个"""
        # 添加第二个 yfinance 节点
        sample_nodes["slave-3"] = SlaveNode(
            node_id="slave-3",
            host="10.0.0.3",
            port=8001,
            collectors=["yfinance"],
            status="healthy",
            last_seen=time.time(),
        )
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}

        call_count = 0

        async def mock_post(url, json=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("connection refused")
            mock_response = MagicMock()
            mock_response.json.return_value = {"code": 0, "data": "ok"}
            mock_response.raise_for_status = MagicMock()
            return mock_response

        manager._http_client.post = mock_post

        result = await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})
        assert result["data"] == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_call_all_failed_no_fallback(self, manager, sample_nodes):
        """所有节点都失败且无本地采集器, 抛出 RuntimeError"""
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}
        manager._http_client.post = AsyncMock(side_effect=Exception("all down"))

        with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=[]):
            with pytest.raises(RuntimeError, match="All nodes failed"):
                await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_call_no_nodes_no_fallback(self, manager):
        """没有可用节点且无本地采集器, 抛出 RuntimeError"""
        manager._http_client = AsyncMock()
        with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=[]):
            with pytest.raises(RuntimeError, match="no local fallback"):
                await manager.call_collector("nonexistent", "action", {})

    @pytest.mark.asyncio
    async def test_call_local_fallback_success(self, manager, sample_nodes):
        """所有从节点失败后降级到本地采集器"""
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}
        manager._http_client.post = AsyncMock(side_effect=Exception("slave down"))

        mock_dispatch = AsyncMock(return_value={"price": 100})
        with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=["yfinance"]):
            with patch("backend.slave_app._dispatch_collect", mock_dispatch):
                result = await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})

        assert result["data"]["price"] == 100
        assert result["source_node"] == "local"
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_no_slaves_local_fallback(self, manager):
        """没有从节点时直接降级到本地采集器"""
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}

        mock_dispatch = AsyncMock(return_value={"price": 200})
        with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=["yfinance"]):
            with patch("backend.slave_app._dispatch_collect", mock_dispatch):
                result = await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})

        assert result["data"]["price"] == 200
        assert result["source_node"] == "local"

    @pytest.mark.asyncio
    async def test_call_payload_format(self, manager, sample_nodes):
        """验证 _call_node 发送的 payload 格式对齐 CollectRequest"""
        manager._nodes = sample_nodes
        manager._rebuild_pools()
        manager._http_client = AsyncMock()
        manager._callback_redis = {"host": "redis", "port": 6379, "password": None}

        captured_payload = None

        async def capture_post(url, json=None):
            nonlocal captured_payload
            captured_payload = json
            mock_response = MagicMock()
            mock_response.json.return_value = {"code": 0, "data": {}}
            mock_response.raise_for_status = MagicMock()
            return mock_response

        manager._http_client.post = capture_post

        await manager.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL", "period": "3mo"})

        # 验证 payload 格式: ticker 在顶层, params 包含其他参数
        assert captured_payload is not None
        assert captured_payload["ticker"] == "AAPL"
        assert captured_payload["params"]["period"] == "3mo"
        assert "callback_redis" in captured_payload
        # ticker 不应出现在 params 中
        assert "ticker" not in captured_payload["params"]


# ==========================================
# get_cluster_status 测试
# ==========================================


class TestClusterStatus:
    """集群状态查询"""

    def test_status_with_slaves(self, manager, sample_nodes):
        manager._nodes = sample_nodes
        manager._rebuild_pools()

        with patch.dict(os.environ, {"NODE_ROLE": "master"}):
            with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=["akshare"]):
                status = manager.get_cluster_status()

        assert "master" in status
        assert "slaves" in status
        assert "pools" in status
        assert len(status["slaves"]) == 2
        assert "yfinance" in status["pools"]

    def test_status_empty(self, manager):
        with patch.dict(os.environ, {"NODE_ROLE": "master"}):
            with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=[]):
                status = manager.get_cluster_status()

        assert status["slaves"] == []
        assert status["pools"] == {}
