"""
Test: CallMetricsStore — 今日调用聚合计数 Redis 持久化
=======================================================
验证：
  - 键空间 quant:metrics:{source}:calls:{date}，按自然日分桶
  - 业务/探针分字段，不互相污染
  - 403/402 落到 rl_ip_blocked/rl_quota_exhausted，不计入 rl_rate_limit
  - get_today 从 Redis 哈希复原聚合指标；Redis 不可用时返回 None（回退内存口径）
  - 禁用开关下不触达 Redis
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.datasource import call_metrics_store
from backend.services.datasource.call_metrics_store import CallMetricsStore


def _fake_redis() -> MagicMock:
    redis = MagicMock()
    redis.hincrby = AsyncMock()
    redis.expire = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    return redis


@pytest.fixture
def fake_redis():
    return _fake_redis()


async def test_record_business_keys_and_fields(fake_redis):
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        await store.record_business("yfinance", "success")
        await store.record_business("yfinance", "rate_limited", category="rate_limit")
        await store.record_business("yfinance", "rate_limited", category="ip_blocked")
        await store.record_business("yfinance", "rate_limited", category="quota_exhausted")
        await store.record_business("yfinance", "error")

    # 仅一个自然日桶
    keys = {c.args[0] for c in fake_redis.hincrby.call_args_list}
    assert len(keys) == 1
    key = next(iter(keys))
    assert re.fullmatch(r"quant:metrics:yfinance:calls:\d{4}-\d{2}-\d{2}", key), key

    fields = {c.args[1] for c in fake_redis.hincrby.call_args_list}
    assert fields == {
        "calls",
        "success",
        "rl_rate_limit",
        "rl_ip_blocked",
        "rl_quota_exhausted",
        "errors",
    }
    # 每次写入刷新 TTL（35 天）
    fake_redis.expire.assert_called()
    ttl = fake_redis.expire.call_args.args[1]
    assert ttl == 35 * 86400


async def test_category_split_403_402_not_rate_limit(fake_redis):
    """403/402 不计入 rl_rate_limit（退避口径），但仍是限流类计数的一部分。"""
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        await store.record_business("finnhub", "rate_limited", category="ip_blocked")
        await store.record_business("finnhub", "rate_limited", category="quota_exhausted")
        await store.record_business("finnhub", "rate_limited", category="rate_limit")

    calls = {(c.args[1], c.args[2]) for c in fake_redis.hincrby.call_args_list}
    assert ("rl_rate_limit", 1) in calls
    assert ("rl_ip_blocked", 1) in calls
    assert ("rl_quota_exhausted", 1) in calls
    # 业务总调用次数 = 3
    assert ("calls", 1) in calls


async def test_probe_separated_from_business(fake_redis):
    """探针单独分字段，不污染业务 calls/success/errors。"""
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        await store.record_business("yfinance", "success")
        await store.record_probe("yfinance", success=True)
        await store.record_probe("yfinance", success=False)

    fields = {c.args[1] for c in fake_redis.hincrby.call_args_list}
    assert "probe_calls" in fields and "probe_success" in fields and "probe_errors" in fields
    # 业务字段未被探针污染
    business_calls = [c.args[2] for c in fake_redis.hincrby.call_args_list if c.args[1] == "calls"]
    assert business_calls == [1]  # 仅真实 fetch 的 1 次


async def test_get_today_reassembles(fake_redis):
    fake_redis.hgetall = AsyncMock(
        return_value={
            "calls": "10",
            "success": "7",
            "errors": "1",
            "rl_rate_limit": "1",
            "rl_quota_exhausted": "1",
            "rl_ip_blocked": "0",
            "probe_calls": "3",
            "probe_success": "2",
            "probe_errors": "1",
        }
    )
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        snap = await store.get_today("yfinance")

    assert snap is not None
    assert snap["calls"] == 10
    assert snap["success"] == 7
    assert snap["rate_limit_count"] == 2  # 1+1+0
    assert snap["rl_breakdown"] == {"rate_limit": 1, "quota_exhausted": 1, "ip_blocked": 0}
    assert snap["success_rate"] == pytest.approx(0.7)
    assert snap["probe_calls"] == 3
    assert snap["metric_source"] == "redis"


async def test_get_today_returns_none_on_empty_and_on_error(fake_redis):
    # 空桶 → 回退
    fake_redis.hgetall = AsyncMock(return_value={})
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        assert await store.get_today("yfinance") is None

    # Redis 异常 → 回退（不抛）
    fake_redis.hgetall = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=True)
        assert await store.get_today("yfinance") is None


async def test_disabled_does_not_touch_redis(fake_redis):
    with patch.object(call_metrics_store, "redis_client", fake_redis):
        store = CallMetricsStore(enabled=False)
        await store.record_business("yfinance", "success")
        await store.record_probe("yfinance", success=True)
        assert await store.get_today("yfinance") is None
    fake_redis.hincrby.assert_not_called()
    fake_redis.expire.assert_not_called()
