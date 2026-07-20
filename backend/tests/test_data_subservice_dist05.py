"""
DIST-05: data_subservice 子服务工程 — 单元测试
================================================

验证:
  1. 环境变量解析与 NodeInfo 构造
  2. Startup: 注册到 ServiceRegistry
  3. 心跳: 后台任务定时发送心跳
  4. Shutdown: 注销节点 + 关闭 Redis
  5. 端点: /health, /ds/health, /ds/{source}/{action} (501)
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────
#  Mock 基础设施
# ─────────────────────────────────────────


class FakeRedis:
    """模拟 Redis 客户端"""

    def __init__(self):
        self._data = {}
        self._closed = False

    async def ping(self):
        return True

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value, ex=None):
        self._data[key] = value
        return True

    async def hset(self, name, key, value):
        if name not in self._data:
            self._data[name] = {}
        self._data[name][key] = value
        return 1

    async def hget(self, name, key):
        h = self._data.get(name, {})
        return h.get(key)

    async def hgetall(self, name):
        return self._data.get(name, {})

    async def hdel(self, name, *keys):
        h = self._data.get(name, {})
        count = 0
        for k in keys:
            if k in h:
                del h[k]
                count += 1
        return count

    async def zadd(self, name, mapping):
        if name not in self._data:
            self._data[name] = {}
        self._data[name].update(mapping)
        return len(mapping)

    async def zrem(self, name, *keys):
        z = self._data.get(name, {})
        count = 0
        for k in keys:
            if k in z:
                del z[k]
                count += 1
        return count

    async def zrangebyscore(self, name, min_score, max_score):
        return []

    async def sadd(self, name, *values):
        if name not in self._data:
            self._data[name] = set()
        self._data[name].update(values)
        return len(values)

    async def srem(self, name, *values):
        s = self._data.get(name, set())
        count = 0
        for v in values:
            if v in s:
                s.discard(v)
                count += 1
        return count

    async def sismember(self, name, value):
        return value in self._data.get(name, set())

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                count += 1
        return count

    async def aclose(self):
        self._closed = True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    """模拟 Redis Pipeline"""

    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def hset(self, name, key, value):
        self._ops.append(("hset", name, key, value))
        return self

    def hdel(self, name, *keys):
        self._ops.append(("hdel", name, keys))
        return self

    def zadd(self, name, mapping):
        self._ops.append(("zadd", name, mapping))
        return self

    def zrem(self, name, *keys):
        self._ops.append(("zrem", name, keys))
        return self

    def sadd(self, name, *values):
        self._ops.append(("sadd", name, values))
        return self

    def srem(self, name, *values):
        self._ops.append(("srem", name, values))
        return self

    def delete(self, *keys):
        self._ops.append(("delete", keys))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "hset":
                r = await self._redis.hset(op[1], op[2], op[3])
                results.append(r)
            elif op[0] == "hdel":
                r = await self._redis.hdel(op[1], *op[2])
                results.append(r)
            elif op[0] == "zadd":
                r = await self._redis.zadd(op[1], op[2])
                results.append(r)
            elif op[0] == "zrem":
                r = await self._redis.zrem(op[1], *op[2])
                results.append(r)
            elif op[0] == "sadd":
                r = await self._redis.sadd(op[1], *op[2])
                results.append(r)
            elif op[0] == "srem":
                r = await self._redis.srem(op[1], *op[2])
                results.append(r)
            elif op[0] == "delete":
                r = await self._redis.delete(*op[1])
                results.append(r)
            elif op[0] == "expire":
                results.append(True)
        self._ops.clear()
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def env_vars():
    """设置子服务所需的环境变量"""
    env = {
        "DS_NODE_ID": "test-node-01",
        "DS_NODE_PORT": "8001",
        "DS_REGION": "us-west",
        "DS_WEIGHT": "10",
        "DS_CAPABILITIES": "yfinance,akshare",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
    }
    with patch.dict(os.environ, env):
        yield env


@pytest.fixture
def fake_redis():
    return FakeRedis()


# ─────────────────────────────────────────
#  1. 环境变量解析与 NodeInfo 构造
# ─────────────────────────────────────────


class TestNodeInfoBuild:
    """验证从环境变量构造 NodeInfo"""

    def test_build_node_info(self, env_vars, fake_redis):
        """NodeInfo 应正确反映环境变量"""
        # 需要重新导入以获取更新后的环境变量
        with (
            patch("data_subservice.main.DS_NODE_ID", "test-node-01"),
            patch("data_subservice.main.DS_NODE_PORT", 8001),
            patch("data_subservice.main.DS_REGION", "us-west"),
            patch("data_subservice.main.DS_WEIGHT", 10),
            patch("data_subservice.main.DS_CAPABILITIES", ["yfinance", "akshare"]),
        ):
            from data_subservice.main import _build_node_info

            node = _build_node_info()

            assert node.node_id == "test-node-01"
            assert node.region == "us-west"
            assert node.weight == 10
            assert "yfinance" in node.capabilities
            assert "akshare" in node.capabilities

    def test_build_node_url(self):
        """URL 应包含端口"""
        with patch("data_subservice.main.DS_NODE_PORT", 9999):
            from data_subservice.main import _build_node_url

            url = _build_node_url()
            assert "9999" in url


# ─────────────────────────────────────────
#  2. Startup: 注册到 ServiceRegistry
# ─────────────────────────────────────────


class TestStartupRegistration:
    """验证启动时注册流程"""

    @pytest.mark.asyncio
    async def test_register_called_on_startup(self, env_vars, fake_redis):
        """启动时应调用 registry.register()"""
        import data_subservice.main as mod

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
        ):
            async with mod.lifespan(mod.app):
                mock_registry.register.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_startup_fails_without_node_id(self):
        """缺少 DS_NODE_ID 应抛出 RuntimeError"""
        with patch("data_subservice.main.DS_NODE_ID", ""):
            from data_subservice.main import app, lifespan

            with pytest.raises(RuntimeError, match="DS_NODE_ID"):
                async with lifespan(app):
                    pass


# ─────────────────────────────────────────
#  3. 心跳后台任务
# ─────────────────────────────────────────


class TestHeartbeat:
    """验证心跳后台任务"""

    @pytest.mark.asyncio
    async def test_heartbeat_sends_metrics(self, env_vars, fake_redis):
        """心跳应附带 uptime_seconds 指标"""
        import data_subservice.main as mod
        from data_subservice.main import _heartbeat_loop

        mock_registry = AsyncMock()
        mock_registry.heartbeat = AsyncMock(return_value=True)
        mod._registry = mock_registry
        mod._start_time = 1000.0  # 固定起始时间

        # 运行一次心跳 (通过缩短 sleep 时间)
        with (
            patch("data_subservice.main.HEARTBEAT_INTERVAL", 0),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
        ):
            task = asyncio.create_task(_heartbeat_loop())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_registry.heartbeat.assert_awaited()
        call_args = mock_registry.heartbeat.call_args
        assert call_args[0][0] == "test-node-01"
        metrics = call_args[1].get("metrics", {})
        assert "uptime_seconds" in metrics


# ─────────────────────────────────────────
#  4. Shutdown: 注销 + 关闭
# ─────────────────────────────────────────


class TestShutdown:
    """验证关闭流程"""

    @pytest.mark.asyncio
    async def test_deregister_called_on_shutdown(self, env_vars, fake_redis):
        """关闭时应调用 registry.deregister()"""
        import data_subservice.main as mod

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)
        mock_registry.deregister = AsyncMock(return_value=True)

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
        ):
            async with mod.lifespan(mod.app):
                pass  # 启动后立即关闭

            mock_registry.deregister.assert_awaited_once_with("test-node-01")

    @pytest.mark.asyncio
    async def test_redis_closed_on_shutdown(self, env_vars, fake_redis):
        """关闭时应关闭 Redis 连接"""
        import data_subservice.main as mod

        mock_registry = AsyncMock()
        mock_registry.register = AsyncMock(return_value=True)
        mock_registry.deregister = AsyncMock(return_value=True)

        mock_aioredis = MagicMock()
        mock_aioredis.Redis = MagicMock(return_value=fake_redis)

        with (
            patch.object(mod, "aioredis", mock_aioredis),
            patch.object(mod, "ServiceRegistry", return_value=mock_registry),
            patch.object(mod, "DS_NODE_ID", "test-node-01"),
        ):
            async with mod.lifespan(mod.app):
                pass

            assert fake_redis._closed is True


# ─────────────────────────────────────────
#  5. 端点测试
# ─────────────────────────────────────────


class TestEndpoints:
    """验证 HTTP 端点"""

    def test_health_endpoint(self, env_vars):
        """/health 应返回节点信息"""
        import data_subservice.main as mod

        mod._start_time = 1000.0

        with (
            patch("data_subservice.main.DS_NODE_ID", "test-node-01"),
            patch("data_subservice.main.DS_REGION", "us-west"),
            patch("data_subservice.main.DS_CAPABILITIES", ["yfinance"]),
        ):
            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")

            assert resp.status_code == 200
            data = resp.json()
            assert data["node_id"] == "test-node-01"
            assert data["region"] == "us-west"
            assert "uptime_seconds" in data

    def test_datasource_health_endpoint(self, env_vars):
        """/ds/health 应返回数据源健康总览"""
        import data_subservice.main as mod

        mod._start_time = 1000.0

        with (
            patch("data_subservice.main.DS_NODE_ID", "test-node-01"),
            patch("data_subservice.main.DS_REGION", "us-west"),
            patch("data_subservice.main.DS_CAPABILITIES", ["yfinance", "akshare"]),
        ):
            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/ds/health")

            assert resp.status_code == 200
            data = resp.json()
            assert "sources" in data
            assert "yfinance" in data["sources"]
            assert "akshare" in data["sources"]

    def test_datasource_proxy_replaced_by_dist07_routes(self, env_vars):
        """/ds/{source}/{action} 已被 DIST-07 路由替代，返回 404"""
        with patch("data_subservice.main.DS_NODE_ID", "test-node-01"):
            from data_subservice.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/ds/yfinance/quote", json={"ticker": "AAPL"})

            # DIST-07: 旧的 501 占位端点已移除，由 routes.py 的新端点替代
            assert resp.status_code == 404
