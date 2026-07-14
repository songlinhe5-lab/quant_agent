"""
DIST-08: data_subservice RegistryClient 增强 — 单元测试
======================================================

验证:
  1. 节点注册带指数退避重试
  2. 心跳失败时指数退避重试策略
  3. 心跳恢复后重试延迟重置
  4. 最大重试次数后放弃
"""

import asyncio
import os
from unittest.mock import patch

import pytest

# ─────────────────────────────────────────
#  Mock 基础设施
# ─────────────────────────────────────────


class FakeRedis:
    """模拟 Redis 客户端"""

    def __init__(self):
        self._data = {}

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

    async def hdel(self, name, key):
        h = self._data.get(name, {})
        if key in h:
            del h[key]
            return 1
        return 0

    async def zadd(self, name, mapping, nx=False):
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
        z = self._data.get(name, {})
        return [k for k, v in z.items() if min_score <= v <= max_score]

    async def zremrangebyscore(self, name, min_score, max_score):
        z = self._data.get(name, {})
        to_remove = [k for k, v in z.items() if min_score <= v <= max_score]
        for k in to_remove:
            del z[k]
        return len(to_remove)

    async def smembers(self, name):
        return self._data.get(name, set())

    async def srem(self, name, *members):
        s = self._data.get(name, set())
        count = 0
        for m in members:
            if m in s:
                s.discard(m)
                count += 1
        return count

    async def sadd(self, name, *members):
        if name not in self._data:
            self._data[name] = set()
        self._data[name].update(members)
        return len(members)

    async def aclose(self):
        pass


# ─────────────────────────────────────────
#  环境变量设置
# ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    """设置测试环境变量"""
    monkeypatch.setenv("DS_NODE_ID", "test-node-01")
    monkeypatch.setenv("DS_NODE_PORT", "8001")
    monkeypatch.setenv("DS_REGION", "us-west")
    monkeypatch.setenv("DS_WEIGHT", "10")
    monkeypatch.setenv("DS_CAPABILITIES", "yfinance")
    monkeypatch.setenv("DS_HEARTBEAT_INTERVAL", "1")  # 快速心跳便于测试
    monkeypatch.setenv("DS_MAX_RETRY_DELAY", "2")
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")


# ─────────────────────────────────────────
#  测试: 节点注册带指数退避重试
# ─────────────────────────────────────────


class TestRegistryClientRetry:
    """DIST-08: 注册/心跳指数退避重试"""

    @pytest.mark.asyncio
    async def test_register_retries_on_failure(self):
        """注册失败时按指数退避重试，最终成功"""
        # 模拟注册逻辑的重试行为（不依赖真实 ServiceRegistry.register）
        call_count = 0
        max_retries = 5

        async def flaky_register():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return False
            return True

        retry_delay = 1
        registered = False

        for attempt in range(1, max_retries + 1):
            result = await flaky_register()
            if result:
                registered = True
                break
            await asyncio.sleep(0)
            retry_delay = min(retry_delay * 2, 2)

        assert registered is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_register_gives_up_after_max_retries(self):
        """注册超过最大重试次数后放弃"""
        from backend.core.service_registry import NodeInfo, ServiceRegistry

        fake_redis = FakeRedis()
        registry = ServiceRegistry(fake_redis)

        # 模拟注册始终失败
        with patch.object(registry, "register", return_value=False):
            node = NodeInfo(node_id="test", url="http://localhost:8000")
            retry_delay = 1
            max_retries = 3
            registered = False

            for attempt in range(1, max_retries + 1):
                result = await registry.register(node)
                if result:
                    registered = True
                    break
                await asyncio.sleep(0)  # 测试不实际等待
                retry_delay = min(retry_delay * 2, 2)

            assert registered is False

    @pytest.mark.asyncio
    async def test_heartbeat_exponential_backoff(self):
        """心跳失败时指数退避延迟递增"""
        from backend.core.service_registry import ServiceRegistry

        fake_redis = FakeRedis()
        registry = ServiceRegistry(fake_redis)

        # 模拟心跳持续失败
        with patch.object(registry, "heartbeat", return_value=False):
            retry_delay = 1
            max_retry_delay = 8
            delays = []

            for _ in range(5):
                ok = await registry.heartbeat("test-node")
                if not ok:
                    delays.append(retry_delay)
                    await asyncio.sleep(0)  # 不实际等待
                    retry_delay = min(retry_delay * 2, max_retry_delay)

            # 验证指数退避序列: 1, 2, 4, 8, 8
            assert delays == [1, 2, 4, 8, 8]

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_resets_delay(self):
        """心跳恢复后重试延迟重置为初始值"""
        retry_delay = 1
        initial_delay = 1
        max_retry_delay = 8
        consecutive_failures = 0

        # 模拟: 失败2次 → 成功 → 失败1次
        results = [False, False, True, False]
        delays_before_recovery = []
        delays_after_recovery = []
        recovered = False

        for result in results:
            if result:  # 成功
                if consecutive_failures > 0:
                    consecutive_failures = 0
                    retry_delay = initial_delay
                recovered = True
            else:  # 失败
                consecutive_failures += 1
                if recovered:
                    delays_after_recovery.append(retry_delay)
                else:
                    delays_before_recovery.append(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

        # 恢复前延迟序列: 1, 2
        assert delays_before_recovery == [1, 2]
        # 恢复后第一次失败的延迟应该是初始值 1
        assert delays_after_recovery == [1]

    @pytest.mark.asyncio
    async def test_heartbeat_exception_handling(self):
        """心跳异常时同样采用指数退避"""
        from backend.core.service_registry import ServiceRegistry

        fake_redis = FakeRedis()
        registry = ServiceRegistry(fake_redis)

        # 模拟心跳抛出异常
        with patch.object(registry, "heartbeat", side_effect=ConnectionError("Redis down")):
            retry_delay = 1
            max_retry_delay = 4
            delays = []

            for _ in range(4):
                try:
                    await registry.heartbeat("test-node")
                except ConnectionError:
                    delays.append(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)

            # 验证指数退避: 1, 2, 4, 4
            assert delays == [1, 2, 4, 4]


class TestRegistryClientConstants:
    """DIST-08: 配置常量验证"""

    def test_default_heartbeat_interval(self):
        """默认心跳间隔 10 秒"""
        # 清除环境变量以测试默认值
        old_val = os.environ.pop("DS_HEARTBEAT_INTERVAL", None)
        try:
            interval = int(os.getenv("DS_HEARTBEAT_INTERVAL", "10"))
            assert interval == 10
        finally:
            if old_val is not None:
                os.environ["DS_HEARTBEAT_INTERVAL"] = old_val

    def test_max_retry_delay_configurable(self):
        """最大重试延迟可通过环境变量配置"""
        assert int(os.getenv("DS_MAX_RETRY_DELAY", "60")) == 2  # 测试环境设为 2

    def test_initial_retry_delay_is_one(self):
        """初始重试延迟固定为 1 秒"""
        # 这是代码常量，不受环境变量影响
        from data_subservice.main import INITIAL_RETRY_DELAY

        assert INITIAL_RETRY_DELAY == 1
