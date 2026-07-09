"""
RL-13: Registry 路由感知限流状态单测
======================================

验证:
- DataSourceNode 新增限流压力字段
- _get_healthy_nodes 同步限流状态
- _select_node 优先选择未限流节点
- 限流节点自动 failover
- get_health_status 暴露限流压力信息
"""

import asyncio
from unittest.mock import patch

import pytest

from backend.services.data_source_router import DataSourceNode, DataSourceRouter
from backend.services.datasource import datasource_registry


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试前重置全局注册表"""
    datasource_registry.clear()
    yield
    datasource_registry.clear()


@pytest.fixture
def router():
    """创建测试用路由器（不依赖环境变量）"""
    with patch.dict("os.environ", {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
        r = DataSourceRouter()
        yield r


# ─────────────────────────────────────────
#  DataSourceNode 新增字段
# ─────────────────────────────────────────

class TestNodeFields:
    def test_node_has_throttle_fields(self):
        node = DataSourceNode(name="test", url="http://localhost")
        assert hasattr(node, "is_throttled")
        assert hasattr(node, "consecutive_rate_limits")
        assert hasattr(node, "estimated_limit_rpm")

    def test_node_default_throttle_values(self):
        node = DataSourceNode(name="test", url="http://localhost")
        assert node.is_throttled is False
        assert node.consecutive_rate_limits == 0
        assert node.estimated_limit_rpm is None


# ─────────────────────────────────────────
#  _get_healthy_nodes 限流状态同步
# ─────────────────────────────────────────

class TestGetHealthyNodes:
    def test_syncs_throttle_status_from_registry(self, router):
        """从 registry 同步限流状态到节点"""
        # 添加一个测试节点
        router._nodes["test_node"] = DataSourceNode(
            name="test_node",
            url="http://localhost",
            capabilities=["test_cap"],
        )
        # 在 registry 中触发限流
        throttler = datasource_registry.get_throttler("test_node")
        throttler.on_rate_limit()

        # 获取健康节点
        healthy = router._get_healthy_nodes("test_cap")
        assert len(healthy) == 1
        assert healthy[0].is_throttled is True
        assert healthy[0].consecutive_rate_limits == 1

    def test_no_throttle_when_clean(self, router):
        """无限流时节点状态为 clean"""
        router._nodes["clean_node"] = DataSourceNode(
            name="clean_node",
            url="http://localhost",
            capabilities=["test_cap"],
        )

        healthy = router._get_healthy_nodes("test_cap")
        assert len(healthy) == 1
        assert healthy[0].is_throttled is False
        assert healthy[0].consecutive_rate_limits == 0


# ─────────────────────────────────────────
#  _select_node 优先级排序
# ─────────────────────────────────────────

class TestSelectNode:
    def test_prefers_non_throttled_node(self, router):
        """优先选择未被限流的节点"""
        # 节点 A: weight=10, 被限流
        router._nodes["node_a"] = DataSourceNode(
            name="node_a", url="http://a", weight=10, capabilities=["cap"],
        )
        # 节点 B: weight=5, 未被限流
        router._nodes["node_b"] = DataSourceNode(
            name="node_b", url="http://b", weight=5, capabilities=["cap"],
        )
        # 限流节点 A
        datasource_registry.get_throttler("node_a").on_rate_limit()

        selected = asyncio.get_event_loop().run_until_complete(
            router._select_node("cap")
        )
        # 应该选择未限流的 B（即使 weight 更低）
        assert selected.name == "node_b"

    def test_prefers_higher_weight_when_equal_throttle(self, router):
        """限流状态相同时选择 weight 更高的节点"""
        router._nodes["node_a"] = DataSourceNode(
            name="node_a", url="http://a", weight=10, capabilities=["cap"],
        )
        router._nodes["node_b"] = DataSourceNode(
            name="node_b", url="http://b", weight=5, capabilities=["cap"],
        )
        # 两个都不限流

        selected = asyncio.get_event_loop().run_until_complete(
            router._select_node("cap")
        )
        assert selected.name == "node_a"

    def test_prefers_lower_rate_limits_when_equal_weight(self, router):
        """weight 相同时选择限流次数更少的节点"""
        router._nodes["node_a"] = DataSourceNode(
            name="node_a", url="http://a", weight=10, capabilities=["cap"],
        )
        router._nodes["node_b"] = DataSourceNode(
            name="node_b", url="http://b", weight=10, capabilities=["cap"],
        )
        # 两个都被限流，但 A 限流次数更多
        throttler_a = datasource_registry.get_throttler("node_a")
        throttler_a.on_rate_limit()
        throttler_a.on_rate_limit()
        throttler_a.on_rate_limit()
        throttler_b = datasource_registry.get_throttler("node_b")
        throttler_b.on_rate_limit()

        selected = asyncio.get_event_loop().run_until_complete(
            router._select_node("cap")
        )
        # B 限流次数更少，优先选择
        assert selected.name == "node_b"

    def test_returns_none_when_no_healthy(self, router):
        """无健康节点时返回 None"""
        selected = asyncio.get_event_loop().run_until_complete(
            router._select_node("nonexistent_cap")
        )
        assert selected is None


# ─────────────────────────────────────────
#  get_health_status 暴露限流信息
# ─────────────────────────────────────────

class TestHealthStatus:
    def test_health_includes_throttle_info(self, router):
        """健康状态包含限流压力信息"""
        router._nodes["test_node"] = DataSourceNode(
            name="test_node", url="http://test", capabilities=["cap"],
        )
        # 触发限流
        datasource_registry.get_throttler("test_node").on_rate_limit()

        health = asyncio.get_event_loop().run_until_complete(
            router.get_health_status()
        )
        node_info = health["nodes"]["test_node"]
        assert "is_throttled" in node_info
        assert "consecutive_rate_limits" in node_info
        assert "total_rate_limits_1h" in node_info
        assert "estimated_limit_rpm" in node_info
        assert "backoff_strategy" in node_info
        assert node_info["is_throttled"] is True
        assert node_info["consecutive_rate_limits"] == 1

    def test_health_clean_node(self, router):
        """干净节点限流信息为默认值"""
        router._nodes["clean_node"] = DataSourceNode(
            name="clean_node", url="http://clean", capabilities=["cap"],
        )

        health = asyncio.get_event_loop().run_until_complete(
            router.get_health_status()
        )
        node_info = health["nodes"]["clean_node"]
        assert node_info["is_throttled"] is False
        assert node_info["consecutive_rate_limits"] == 0
