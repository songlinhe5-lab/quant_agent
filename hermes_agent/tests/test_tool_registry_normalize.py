"""
回归测试：ToolRegistry.execute 归一化 — 缓存命中路径不得绕过归一化。

线上错误：
    AttributeError: 'str' object has no attribute 'get'

复现链：
1. 部分工具 run() 返回 str/list（如 get_insider_transactions 返回紧凑文本省 token）。
2. 首次调用：execute() 非缓存路径将结果归一化为 {"data": <raw>, "status": "success"}，正常。
3. result_cache 缓存的是**工具原始返回值**（str 原样存入）。
4. 同参数再次调用（多轮对话反复请求同一标的）命中缓存 → 直接 return cached（str）
   → 下游 final_res.get("status") 抛 "'str' object has no attribute 'get'"。

修复：缓存命中路径同样走 _normalize_output 归一化。
"""

import pytest

from hermes_agent.tool_registry import ToolRegistry
from hermes_agent.tool_result_cache import ToolResultCache


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


def _make_registry(tool) -> ToolRegistry:
    """构造最小 registry：注入 mock 限流与真实 failure_tracker（复用 RL-14 测试模式）。"""
    from unittest.mock import MagicMock

    from hermes_agent.middleware import FailureTracker

    reg = object.__new__(ToolRegistry)
    reg.tools = {tool.name: tool}
    reg.result_cache = ToolResultCache(redis_client=FakeRedis())
    reg.rate_limiter = MagicMock()
    reg.rate_limiter.acquire = MagicMock()
    reg.failure_tracker = FailureTracker(threshold=3)
    reg._pipeline = reg._build_pipeline()
    return reg


@pytest.mark.asyncio
async def test_str_result_normalized_on_first_execute():
    """str 结果（缓存 miss）归一化为带 status 的 dict。"""

    class StrTool:
        name = "test_str_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}

        async def run(self, **kwargs) -> str:
            return "【AAPL 近期高管内幕交易记录】\n- 2026-08-25 | 买家1 | BUY +1000 股"

    reg = _make_registry(StrTool())
    out = await reg.execute(StrTool.name, ticker="AAPL")
    assert isinstance(out, dict)
    assert out["status"] == "success"
    assert "AAPL 近期高管内幕交易记录" in out["data"]


@pytest.mark.asyncio
async def test_str_result_cache_hit_still_normalized():
    """回归：同参数二次调用命中缓存时，返回的必须是 dict（修复前返回原始 str → .get 炸）。"""

    class StrTool:
        name = "test_str_cache_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def run(self, **kwargs) -> str:
            StrTool.calls += 1
            return f"insider text #{StrTool.calls}"

    StrTool.calls = 0
    reg = _make_registry(StrTool())

    results = [await reg.execute(StrTool.name, ticker="AAPL") for _ in range(3)]
    assert StrTool.calls == 1, "第 2、3 次应命中缓存"
    for r in results:
        assert isinstance(r, dict), f"缓存命中返回非 dict: {type(r)}"
        assert r["status"] == "success"
        assert "insider text #1" in r["data"]


@pytest.mark.asyncio
async def test_list_result_cache_hit_normalized():
    """list 结果缓存命中同样归一化为 dict。"""

    class ListTool:
        name = "test_list_cache_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def run(self, **kwargs) -> list:
            ListTool.calls += 1
            return [{"date": "2026-08-25", "action": "BUY"}]

    ListTool.calls = 0
    reg = _make_registry(ListTool())

    results = [await reg.execute(ListTool.name, ticker="AAPL") for _ in range(2)]
    assert ListTool.calls == 1
    for r in results:
        assert isinstance(r, dict)
        assert r["status"] == "success"
        assert isinstance(r["data"], list)


@pytest.mark.asyncio
async def test_dict_result_cache_hit_preserved():
    """dict 结果缓存命中保持原样（含 _cache_hit 标记），不破坏既有行为。"""

    class DictTool:
        name = "test_dict_cache_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def run(self, **kwargs) -> dict:
            DictTool.calls += 1
            return {"status": "success", "data": {"price": 150.0}}

    DictTool.calls = 0
    reg = _make_registry(DictTool())

    r1 = await reg.execute(DictTool.name, ticker="AAPL")
    r2 = await reg.execute(DictTool.name, ticker="AAPL")
    assert DictTool.calls == 1
    assert r1.get("_cache_hit") is None
    assert r2.get("_cache_hit") is True
    assert r2["data"]["price"] == 150.0
