"""
ALERT-01: 告警引擎 Worker — 单元测试
======================================

验证:
  1. 规则 CRUD (add/remove/update/load)
  2. 价格规则评估 (above/below/cross/pct_change)
  3. 冷却期去重
  4. 事件生成与持久化
  5. 多通道推送回调
  6. 引擎统计
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    evaluate_price_rule,
)
from backend.workers.alert_engine import AlertEngine


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


class FakeRedis:
    """模拟 Redis"""

    def __init__(self):
        self._data = {}
        self._lists = {}

    async def hset(self, name, key, value):
        if name not in self._data:
            self._data[name] = {}
        self._data[name][key] = value
        return 1

    async def hgetall(self, name):
        return self._data.get(name, {})

    async def hdel(self, name, key):
        h = self._data.get(name, {})
        if key in h:
            del h[key]
            return 1
        return 0

    async def lpush(self, name, value):
        if name not in self._lists:
            self._lists[name] = []
        self._lists[name].insert(0, value)
        return len(self._lists[name])

    async def ltrim(self, name, start, end):
        if name in self._lists:
            self._lists[name] = self._lists[name][start:end + 1]

    async def pubsub(self):
        return MagicMock()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def engine(fake_redis):
    return AlertEngine(fake_redis)


def make_rule(
    rule_id="rule-1",
    ticker="AAPL",
    rule_type=AlertRuleType.PRICE_ABOVE,
    threshold=200.0,
    cooldown=300,
    channels=None,
) -> AlertRule:
    return AlertRule(
        rule_id=rule_id,
        name=f"Test {rule_id}",
        ticker=ticker,
        rule_type=rule_type,
        threshold=threshold,
        cooldown_seconds=cooldown,
        channels=channels or [AlertChannel.IN_APP],
    )


# ─────────────────────────────────────────
#  测试: 规则评估函数
# ─────────────────────────────────────────


class TestEvaluatePriceRule:
    """ALERT-01: 规则评估逻辑"""

    def test_price_above_trigger(self):
        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        assert evaluate_price_rule(rule, 205.0) is True
        assert evaluate_price_rule(rule, 195.0) is False

    def test_price_below_trigger(self):
        rule = make_rule(rule_type=AlertRuleType.PRICE_BELOW, threshold=100)
        assert evaluate_price_rule(rule, 95.0) is True
        assert evaluate_price_rule(rule, 105.0) is False

    def test_price_cross_up(self):
        rule = make_rule(rule_type=AlertRuleType.PRICE_CROSS, threshold=150)
        assert evaluate_price_rule(rule, 155.0, prev_price=145.0) is True   # 上穿
        assert evaluate_price_rule(rule, 145.0, prev_price=155.0) is True   # 下穿
        assert evaluate_price_rule(rule, 155.0, prev_price=155.0) is False  # 未穿越

    def test_price_cross_no_prev(self):
        rule = make_rule(rule_type=AlertRuleType.PRICE_CROSS, threshold=150)
        assert evaluate_price_rule(rule, 155.0, prev_price=None) is False

    def test_pct_change_trigger(self):
        rule = make_rule(rule_type=AlertRuleType.PCT_CHANGE, threshold=5)  # 5%
        assert evaluate_price_rule(rule, 106.0, prev_price=100.0) is True   # 6% > 5%
        assert evaluate_price_rule(rule, 103.0, prev_price=100.0) is False  # 3% < 5%

    def test_volume_surge_trigger(self):
        rule = make_rule(rule_type=AlertRuleType.VOLUME_SURGE, threshold=2.0)
        rule.metadata = {"avg_volume": 1000, "current_volume": 2500}
        assert evaluate_price_rule(rule, 100.0) is True  # 2.5x > 2x

        rule.metadata["current_volume"] = 1500
        assert evaluate_price_rule(rule, 100.0) is False  # 1.5x < 2x


# ─────────────────────────────────────────
#  测试: 规则 CRUD
# ─────────────────────────────────────────


class TestRuleCRUD:
    """ALERT-01: 规则管理"""

    @pytest.mark.asyncio
    async def test_add_rule(self, engine):
        rule = make_rule()
        await engine.add_rule(rule)
        assert rule.rule_id in engine._rules
        assert len(engine.get_rules()) == 1

    @pytest.mark.asyncio
    async def test_remove_rule(self, engine):
        rule = make_rule()
        await engine.add_rule(rule)
        removed = await engine.remove_rule(rule.rule_id)
        assert removed is True
        assert rule.rule_id not in engine._rules

    @pytest.mark.asyncio
    async def test_load_rules_from_redis(self, engine, fake_redis):
        rule = make_rule()
        await fake_redis.hset("quant:alerts:rules", rule.rule_id, rule.model_dump_json())
        count = await engine.load_rules()
        assert count == 1
        assert rule.rule_id in engine._rules


# ─────────────────────────────────────────
#  测试: 行情评估
# ─────────────────────────────────────────


class TestQuoteEvaluation:
    """ALERT-01: 行情评估与触发"""

    @pytest.mark.asyncio
    async def test_price_above_triggers_alert(self, engine):
        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        await engine.add_rule(rule)

        events = await engine.evaluate_quote("AAPL", 205.0)
        assert len(events) == 1
        assert events[0].ticker == "AAPL"
        assert events[0].trigger_value == 205.0

    @pytest.mark.asyncio
    async def test_no_trigger_below_threshold(self, engine):
        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        await engine.add_rule(rule)

        events = await engine.evaluate_quote("AAPL", 195.0)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self, engine):
        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200, cooldown=300)
        await engine.add_rule(rule)

        # 第一次触发
        events1 = await engine.evaluate_quote("AAPL", 205.0)
        assert len(events1) == 1

        # 冷却期内不再触发
        events2 = await engine.evaluate_quote("AAPL", 210.0)
        assert len(events2) == 0

    @pytest.mark.asyncio
    async def test_multiple_rules_same_ticker(self, engine):
        rule1 = make_rule(rule_id="r1", rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        rule2 = make_rule(rule_id="r2", rule_type=AlertRuleType.PRICE_BELOW, threshold=100)
        await engine.add_rule(rule1)
        await engine.add_rule(rule2)

        events = await engine.evaluate_quote("AAPL", 205.0)
        assert len(events) == 1  # 只有 PRICE_ABOVE 触发

    @pytest.mark.asyncio
    async def test_no_match_different_ticker(self, engine):
        rule = make_rule(ticker="MSFT", rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        await engine.add_rule(rule)

        events = await engine.evaluate_quote("AAPL", 205.0)
        assert len(events) == 0


# ─────────────────────────────────────────
#  测试: 推送回调
# ─────────────────────────────────────────


class TestPushCallbacks:
    """ALERT-01: 多通道推送"""

    @pytest.mark.asyncio
    async def test_push_callback_invoked(self, engine):
        callback = MagicMock()
        engine.register_push(AlertChannel.IN_APP, callback)

        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        await engine.add_rule(rule)

        await engine.evaluate_quote("AAPL", 205.0)
        assert callback.called

    @pytest.mark.asyncio
    async def test_async_push_callback(self, engine):
        callback = AsyncMock()
        engine.register_push(AlertChannel.FEISHU, callback)

        rule = make_rule(
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=200,
            channels=[AlertChannel.FEISHU],
        )
        await engine.add_rule(rule)

        await engine.evaluate_quote("AAPL", 205.0)
        assert callback.called


# ─────────────────────────────────────────
#  测试: 引擎统计
# ─────────────────────────────────────────


class TestEngineStats:
    """ALERT-01: 引擎统计"""

    @pytest.mark.asyncio
    async def test_stats_after_evaluation(self, engine):
        rule = make_rule(rule_type=AlertRuleType.PRICE_ABOVE, threshold=200)
        await engine.add_rule(rule)

        await engine.evaluate_quote("AAPL", 205.0)
        await engine.evaluate_quote("AAPL", 210.0)  # 冷却中
        await engine.evaluate_quote("MSFT", 100.0)  # 无匹配规则

        stats = engine.stats
        assert stats["active_rules"] == 1
        assert stats["eval_count"] == 3
        assert stats["trigger_count"] == 1
        assert stats["tracked_tickers"] == 1  # 仅 AAPL (MSFT 无匹配规则不追踪)

    def test_initial_stats(self, engine):
        stats = engine.stats
        assert stats["running"] is False
        assert stats["active_rules"] == 0
        assert stats["eval_count"] == 0
