"""
RL-14 · 冷却信号识别 + 工具缓存/失败计数回归

覆盖:
  1. detect_cooldown 对新协议(error_category/retry_after)、error 子对象、关键词兜底的识别
  2. 4 次同名调用 → 1 次真实请求（tool_result_cache 经 registry 生效）
  3. 冷却响应不计入本地失败计数（上游熔断之上不再叠加本地熔断）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_agent.cooldown import detect_cooldown
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
    """构造最小 registry：注入 mock 限流与真实 failure_tracker。"""
    from hermes_agent.middleware import FailureTracker

    reg = object.__new__(ToolRegistry)
    reg.tools = {tool.name: tool}
    reg.result_cache = ToolResultCache(redis_client=FakeRedis())
    reg.rate_limiter = MagicMock()
    reg.rate_limiter.acquire = AsyncMock()
    reg.failure_tracker = FailureTracker(threshold=3)
    reg._pipeline = reg._build_pipeline()
    return reg


class TestDetectCooldown:
    def test_new_protocol_top_level(self):
        sig = detect_cooldown(
            {"status": "error", "error_category": "circuit_open", "retry_after": 20, "message": "熔断"}
        )
        assert sig is not None
        assert sig.category == "circuit_open"
        assert sig.retry_after == 20
        assert "20s" in sig.hint

    def test_error_subobject(self):
        sig = detect_cooldown(
            {
                "status": "error",
                "error": {
                    "code": "CIRCUIT_OPEN",
                    "category": "circuit_open",
                    "retry_after": 12.5,
                },
            }
        )
        assert sig is not None
        assert sig.retry_after == 12.5

    def test_rate_limit_status_fallback(self):
        sig = detect_cooldown({"status": "rate_limited", "message": "退避中"})
        assert sig is not None
        assert sig.category == "rate_limit"

    def test_keyword_fallback(self):
        """未升级结构化字段的旧响应：按关键词兜底识别。"""
        sig = detect_cooldown({"status": "error", "message": "Futu 熔断中，请稍后"})
        assert sig is not None

    def test_normal_result_not_cooldown(self):
        assert detect_cooldown({"status": "success", "data": {"price": 1.0}}) is None
        assert detect_cooldown({"status": "error", "message": "参数错误: ticker 为空"}) is None
        assert detect_cooldown(None) is None


@pytest.mark.asyncio
async def test_four_identical_calls_one_real_request():
    """4 次同名同参调用 → 工具真实 run 仅 1 次，其余命中缓存。"""

    class QuoteTool:
        name = "dummy_quote_cache_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        calls = 0

        async def run(self, **kwargs):
            QuoteTool.calls += 1
            return {"status": "success", "data": {"n": QuoteTool.calls}}

    QuoteTool.calls = 0
    reg = _make_registry(QuoteTool())

    results = [await reg.execute(QuoteTool.name, ticker="US.AAPL", action="QUOTE") for _ in range(4)]

    assert QuoteTool.calls == 1, f"真实请求应为 1 次，实际 {QuoteTool.calls}"
    assert results[0].get("_cache_hit") is None
    for r in results[1:]:
        assert r.get("_cache_hit") is True
    # 全部返回同一份数据（首次结果）
    assert all(r["data"]["n"] == 1 for r in results)


@pytest.mark.asyncio
async def test_cooldown_not_counted_as_tool_failure():
    """上游熔断响应不累计本地失败计数：冷却期结束后调用不被本地熔断拦截。"""

    class FlakyTool:
        name = "dummy_flaky_tool"
        description = "test"
        parameters = {"type": "object", "properties": {}}
        mode = "cooldown"
        calls = 0

        async def run(self, **kwargs):
            FlakyTool.calls += 1
            if FlakyTool.mode == "cooldown":
                return {
                    "status": "error",
                    "error_category": "circuit_open",
                    "retry_after": 20,
                    "message": "数据源 futu 处于熔断状态",
                }
            return {"status": "success", "data": {"ok": True}}

    FlakyTool.calls = 0
    FlakyTool.mode = "cooldown"
    reg = _make_registry(FlakyTool())

    # 连续 4 次冷却响应（超过本地熔断阈值 3）
    for _ in range(4):
        out = await reg.execute(FlakyTool.name, ticker="HK.00772")
        assert out.get("_cooldown") == "circuit_open"
        assert out.get("retryable") is False

    # 上游恢复后：本地不得仍处于熔断（否则即为"二次放大"）
    FlakyTool.mode = "ok"
    out = await reg.execute(FlakyTool.name, ticker="HK.00772")
    assert out.get("status") == "success", f"上游已恢复却被本地熔断拦截: {out}"
    assert out.get("data", {}).get("ok") is True
