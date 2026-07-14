"""
BE-12 · ToolResultCache 单元测试

Mock Redis Hash：命中 / 未命中 / 错误不缓存 / TTL 配置 / Registry 集成。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_agent.tool_result_cache import (
    ToolResultCache,
    cache_key,
    should_cache_result,
    stable_args_hash,
    ttl_for_tool,
)


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def pipeline(self):
        return FakePipeline(self)

    async def hgetall(self, key):
        return dict(self.store.get(key, {}))


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.ops = []

    def hset(self, key, mapping=None):
        self.ops.append(("hset", key, mapping or {}))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                _, key, mapping = op
                self.redis.store[key] = dict(mapping)
            elif op[0] == "expire":
                _, key, ttl = op
                self.redis.ttls[key] = ttl
        return [True] * len(self.ops)


class TestCacheKeyHelpers:
    def test_stable_hash_deterministic(self):
        a = stable_args_hash("get_broker_market_data", {"ticker": "US.AAPL", "action": "QUOTE"})
        b = stable_args_hash("get_broker_market_data", {"action": "QUOTE", "ticker": "US.AAPL"})
        assert a == b
        assert len(a) == 64

    def test_cache_key_format(self):
        key = cache_key("web_search", {"query": "AAPL"})
        assert key.startswith("tool:cache:web_search:")

    def test_should_not_cache_errors(self):
        assert should_cache_result({"status": "error", "message": "x"}) is False
        assert should_cache_result({"status": "rate_limited"}) is False
        assert should_cache_result({"status": "success", "data": {"p": 1}}) is True

    def test_ttl_env_override(self, monkeypatch):
        monkeypatch.setenv("TOOL_CACHE_TTL_GET_BROKER_MARKET_DATA", "42")
        assert ttl_for_tool("get_broker_market_data") == 42
        monkeypatch.delenv("TOOL_CACHE_TTL_GET_BROKER_MARKET_DATA")
        assert ttl_for_tool("get_broker_market_data") == 60


@pytest.mark.asyncio
async def test_cache_roundtrip():
    redis = FakeRedis()
    cache = ToolResultCache(redis_client=redis)
    args = {"ticker": "US.AAPL", "action": "QUOTE"}
    payload = {"status": "success", "data": {"price": 190.0}}

    assert await cache.get("get_broker_market_data", args) is None
    assert await cache.set("get_broker_market_data", args, payload) is True
    key = cache_key("get_broker_market_data", args)
    assert key in redis.store
    assert redis.ttls[key] == 60

    hit = await cache.get("get_broker_market_data", args)
    assert hit["data"]["price"] == 190.0
    assert hit["_cache_hit"] is True
    assert cache.stats()["hits"] == 1


@pytest.mark.asyncio
async def test_error_not_cached():
    redis = FakeRedis()
    cache = ToolResultCache(redis_client=redis)
    ok = await cache.set(
        "get_broker_market_data",
        {"ticker": "X"},
        {"status": "error", "message": "dead"},
    )
    assert ok is False
    assert redis.store == {}


@pytest.mark.asyncio
async def test_disabled_cache(monkeypatch):
    monkeypatch.setenv("TOOL_CACHE_ENABLED", "false")
    redis = FakeRedis()
    cache = ToolResultCache(redis_client=redis)
    await cache.set("web_search", {"query": "a"}, {"status": "success", "data": []})
    assert redis.store == {}
    assert await cache.get("web_search", {"query": "a"}) is None


@pytest.mark.asyncio
async def test_registry_execute_uses_cache():
    """Registry 第二次相同调用应命中缓存，不二次 run。"""
    from hermes_agent.tool_registry import ToolRegistry

    redis = FakeRedis()
    cache = ToolResultCache(redis_client=redis)

    class DummyTool:
        name = "dummy_quote_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def run(self, **kwargs):
            DummyTool.calls += 1
            return {"status": "success", "data": {"n": DummyTool.calls}}

    # 构造空 registry，绕过全量工具加载副作用：直接塞工具
    reg = object.__new__(ToolRegistry)
    reg.tools = {"dummy_quote_tool": DummyTool()}
    reg.result_cache = cache
    reg.rate_limiter = MagicMock()
    reg.rate_limiter.acquire = AsyncMock()

    DummyTool.calls = 0
    r1 = await reg.execute("dummy_quote_tool", ticker="US.AAPL")
    r2 = await reg.execute("dummy_quote_tool", ticker="US.AAPL")
    assert r1["data"]["n"] == 1
    assert r2["_cache_hit"] is True
    assert DummyTool.calls == 1
