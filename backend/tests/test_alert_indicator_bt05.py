"""
技术指标告警测试 (ALERT-05)
============================

测试覆盖:
  - evaluate_indicator_rule: RSI/MACD/MA 规则评估
  - IndicatorEvaluator: 节流 + 缓存 + 评估流程
  - extract_indicators_from_tech_data: 指标数据提取
  - AlertEngine 集成: 指标规则评估 + 事件创建
"""

import time
from unittest.mock import AsyncMock

import pytest

from backend.core.alert_models import (
    AlertChannel,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    evaluate_indicator_rule,
)
from backend.services.indicator_evaluator import (
    INDICATOR_RULE_TYPES,
    IndicatorEvaluator,
    extract_indicators_from_tech_data,
)

# ─── Fixtures ──────────────────────────────────────────────────────


def _make_rule(
    rule_type: AlertRuleType,
    threshold: float = 0,
    metadata: dict = None,
    **kwargs,
) -> AlertRule:
    """创建测试规则"""
    return AlertRule(
        rule_id=f"test-{rule_type.value}",
        name=f"Test {rule_type.value}",
        ticker="AAPL",
        rule_type=rule_type,
        threshold=threshold,
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.IN_APP],
        cooldown_seconds=60,
        metadata=metadata or {},
        **kwargs,
    )


# ─── evaluate_indicator_rule 测试 ──────────────────────────────────


class TestEvaluateIndicatorRule:
    """指标规则评估逻辑测试"""

    # ── RSI ──

    def test_rsi_oversold_triggers(self):
        """RSI < 30 触发超卖告警"""
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        assert evaluate_indicator_rule(rule, {"rsi": 25.0}) is True
        assert evaluate_indicator_rule(rule, {"rsi": 35.0}) is False

    def test_rsi_overbought_triggers(self):
        """RSI > 70 触发超买告警"""
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=70)
        assert evaluate_indicator_rule(rule, {"rsi": 75.0}) is True
        assert evaluate_indicator_rule(rule, {"rsi": 65.0}) is False

    def test_rsi_missing_returns_false(self):
        """RSI 缺失时不触发"""
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        assert evaluate_indicator_rule(rule, {}) is False

    # ── MACD ──

    def test_macd_golden_cross_triggers(self):
        """MACD 金叉触发"""
        rule = _make_rule(AlertRuleType.MACD_CROSS, metadata={"direction": "golden"})
        current = {"macd_line": 0.5, "signal_line": 0.3}
        prev = {"macd_line": 0.2, "signal_line": 0.3}
        assert evaluate_indicator_rule(rule, current, prev) is True

    def test_macd_golden_cross_no_trigger(self):
        """MACD 未金叉"""
        rule = _make_rule(AlertRuleType.MACD_CROSS, metadata={"direction": "golden"})
        current = {"macd_line": 0.2, "signal_line": 0.3}
        prev = {"macd_line": 0.1, "signal_line": 0.3}
        assert evaluate_indicator_rule(rule, current, prev) is False

    def test_macd_death_cross_triggers(self):
        """MACD 死叉触发"""
        rule = _make_rule(AlertRuleType.MACD_CROSS, metadata={"direction": "death"})
        current = {"macd_line": 0.2, "signal_line": 0.3}
        prev = {"macd_line": 0.5, "signal_line": 0.3}
        assert evaluate_indicator_rule(rule, current, prev) is True

    def test_macd_no_prev_returns_false(self):
        """无前一次指标时不触发"""
        rule = _make_rule(AlertRuleType.MACD_CROSS, metadata={"direction": "golden"})
        current = {"macd_line": 0.5, "signal_line": 0.3}
        assert evaluate_indicator_rule(rule, current, None) is False

    # ── MA Cross ──

    def test_ma_golden_cross_triggers(self):
        """MA 金叉触发（短均上穿长均）"""
        rule = _make_rule(
            AlertRuleType.MA_CROSS,
            metadata={"direction": "golden", "short_period": 10, "long_period": 20},
        )
        current = {"ma_10": 155.0, "ma_20": 150.0}
        prev = {"ma_10": 148.0, "ma_20": 150.0}
        assert evaluate_indicator_rule(rule, current, prev) is True

    def test_ma_death_cross_triggers(self):
        """MA 死叉触发（短均下穿长均）"""
        rule = _make_rule(
            AlertRuleType.MA_CROSS,
            metadata={"direction": "death", "short_period": 10, "long_period": 20},
        )
        current = {"ma_10": 148.0, "ma_20": 150.0}
        prev = {"ma_10": 155.0, "ma_20": 150.0}
        assert evaluate_indicator_rule(rule, current, prev) is True

    def test_ma_missing_key_returns_false(self):
        """MA 键缺失时不触发"""
        rule = _make_rule(
            AlertRuleType.MA_CROSS,
            metadata={"direction": "golden", "short_period": 10, "long_period": 20},
        )
        current = {"ma_10": 155.0}  # 缺少 ma_20
        prev = {"ma_10": 148.0, "ma_20": 150.0}
        assert evaluate_indicator_rule(rule, current, prev) is False


# ─── IndicatorEvaluator 测试 ───────────────────────────────────────


class TestIndicatorEvaluator:
    """IndicatorEvaluator 节流 + 缓存测试"""

    def test_should_evaluate_first_time(self):
        """首次评估应通过"""
        evaluator = IndicatorEvaluator(throttle_minutes=15)
        assert evaluator.should_evaluate("AAPL") is True

    def test_should_evaluate_throttled(self):
        """节流期内不应评估"""
        evaluator = IndicatorEvaluator(throttle_minutes=15)
        evaluator.mark_evaluated("AAPL")
        assert evaluator.should_evaluate("AAPL") is False

    def test_should_evaluate_after_throttle(self):
        """节流期后应评估"""
        evaluator = IndicatorEvaluator(throttle_minutes=0)  # 0 分钟 = 不节流
        evaluator.mark_evaluated("AAPL")
        assert evaluator.should_evaluate("AAPL") is True

    def test_should_evaluate_force(self):
        """强制评估忽略节流"""
        evaluator = IndicatorEvaluator(throttle_minutes=15)
        evaluator.mark_evaluated("AAPL")
        assert evaluator.should_evaluate("AAPL", force=True) is True

    def test_update_indicators_sliding_window(self):
        """指标缓存滑动窗口"""
        evaluator = IndicatorEvaluator()
        evaluator.update_indicators("AAPL", {"rsi": 50})
        assert evaluator.get_current_indicators("AAPL") == {"rsi": 50}
        assert evaluator.get_prev_indicators("AAPL") is None

        evaluator.update_indicators("AAPL", {"rsi": 60})
        assert evaluator.get_current_indicators("AAPL") == {"rsi": 60}
        assert evaluator.get_prev_indicators("AAPL") == {"rsi": 50}

    def test_evaluate_rules_triggers(self):
        """evaluate_rules 正确返回触发结果"""
        evaluator = IndicatorEvaluator()
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        results = evaluator.evaluate_rules("AAPL", [rule], {"rsi": 25})
        assert len(results) == 1
        assert results[0] == (rule, True)

    def test_evaluate_rules_no_trigger(self):
        """evaluate_rules 正确返回未触发结果"""
        evaluator = IndicatorEvaluator()
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        results = evaluator.evaluate_rules("AAPL", [rule], {"rsi": 50})
        assert len(results) == 1
        assert results[0] == (rule, False)

    def test_clear_cache(self):
        """清除缓存"""
        evaluator = IndicatorEvaluator()
        evaluator.update_indicators("AAPL", {"rsi": 50})
        evaluator.mark_evaluated("AAPL")
        evaluator.clear_cache("AAPL")
        assert evaluator.get_current_indicators("AAPL") is None
        assert evaluator.should_evaluate("AAPL") is True

    def test_clear_all_cache(self):
        """清除全部缓存"""
        evaluator = IndicatorEvaluator()
        evaluator.update_indicators("AAPL", {"rsi": 50})
        evaluator.update_indicators("TSLA", {"rsi": 60})
        evaluator.clear_cache()
        assert evaluator.get_current_indicators("AAPL") is None
        assert evaluator.get_current_indicators("TSLA") is None


# ─── extract_indicators_from_tech_data 测试 ────────────────────────


class TestExtractIndicators:
    """指标数据提取测试"""

    def test_extract_rsi(self):
        """提取 RSI"""
        tech_data = {"data": {"trend": [{"RSI_14": 65.3}]}}
        result = extract_indicators_from_tech_data(tech_data)
        assert result["rsi"] == 65.3

    def test_extract_macd(self):
        """提取 MACD"""
        tech_data = {"data": {"trend": [{"MACD_12_26_9": 0.5, "MACDs_12_26_9": 0.3, "MACDh_12_26_9": 0.2}]}}
        result = extract_indicators_from_tech_data(tech_data)
        assert result["macd_line"] == 0.5
        assert result["signal_line"] == 0.3
        assert result["macd_hist"] == 0.2

    def test_extract_ma(self):
        """提取 MA"""
        tech_data = {"data": {"trend": [{"SMA_10": 150.5, "SMA_20": 145.2}]}}
        result = extract_indicators_from_tech_data(tech_data)
        assert result["ma_10"] == 150.5
        assert result["ma_20"] == 145.2

    def test_extract_empty_data(self):
        """空数据返回空字典"""
        assert extract_indicators_from_tech_data({}) == {}
        assert extract_indicators_from_tech_data({"data": {}}) == {}
        assert extract_indicators_from_tech_data({"data": {"trend": []}}) == {}

    def test_extract_kdj(self):
        """提取 KDJ"""
        tech_data = {"data": {"trend": [{"K_9_3_3": 70, "D_9_3_3": 60, "J_9_3_3": 90}]}}
        result = extract_indicators_from_tech_data(tech_data)
        assert result["k"] == 70
        assert result["d"] == 60
        assert result["j"] == 90


# ─── INDICATOR_RULE_TYPES 测试 ─────────────────────────────────────


class TestIndicatorRuleTypes:
    """指标规则类型集合测试"""

    def test_indicator_rule_types_contains_expected(self):
        """INDICATOR_RULE_TYPES 包含预期类型"""
        assert AlertRuleType.RSI_THRESHOLD in INDICATOR_RULE_TYPES
        assert AlertRuleType.MACD_CROSS in INDICATOR_RULE_TYPES
        assert AlertRuleType.MA_CROSS in INDICATOR_RULE_TYPES

    def test_indicator_rule_types_excludes_price_rules(self):
        """INDICATOR_RULE_TYPES 不包含价格规则"""
        assert AlertRuleType.PRICE_ABOVE not in INDICATOR_RULE_TYPES
        assert AlertRuleType.PRICE_BELOW not in INDICATOR_RULE_TYPES
        assert AlertRuleType.PRICE_CROSS not in INDICATOR_RULE_TYPES


# ─── AlertEngine 集成测试 ─────────────────────────────────────────


class TestAlertEngineIndicatorIntegration:
    """AlertEngine 指标评估集成测试"""

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        redis.hset = AsyncMock()
        redis.lpush = AsyncMock()
        redis.ltrim = AsyncMock()
        redis.hdel = AsyncMock()
        return redis

    @pytest.fixture
    def mock_market_data(self):
        md = AsyncMock()
        md.get_tech_indicators = AsyncMock(return_value={
            "status": "success",
            "data": {"trend": [{"RSI_14": 25.0, "MACD_12_26_9": 0.5, "MACDs_12_26_9": 0.3}]},
        })
        return md

    @pytest.mark.asyncio
    async def test_evaluate_quote_with_indicator_rules(self, mock_redis, mock_market_data):
        """evaluate_quote 触发指标规则"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis, market_data_service=mock_market_data)

        # 添加 RSI 规则
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        await engine.add_rule(rule)

        # 评估行情
        events = await engine.evaluate_quote("AAPL", 150.0)

        # 验证触发
        assert len(events) == 1
        assert events[0].rule_type == AlertRuleType.RSI_THRESHOLD
        assert "RSI" in events[0].message
        assert events[0].source == "indicator"

    @pytest.mark.asyncio
    async def test_evaluate_quote_throttled(self, mock_redis, mock_market_data):
        """指标评估受节流控制"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis, market_data_service=mock_market_data)
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        await engine.add_rule(rule)

        # 第一次评估
        events1 = await engine.evaluate_quote("AAPL", 150.0)
        assert len(events1) == 1

        # 第二次评估应被节流
        events2 = await engine.evaluate_quote("AAPL", 150.0)
        assert len(events2) == 0

    @pytest.mark.asyncio
    async def test_evaluate_quote_no_market_data(self, mock_redis):
        """无 market_data 时指标评估跳过"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis, market_data_service=None)
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        await engine.add_rule(rule)

        events = await engine.evaluate_quote("AAPL", 150.0)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_create_indicator_event_rsi(self, mock_redis):
        """创建 RSI 指标事件"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis)
        rule = _make_rule(AlertRuleType.RSI_THRESHOLD, threshold=30)
        event = engine._create_indicator_event(rule, "AAPL", {"rsi": 25.0}, time.time())

        assert event.rule_type == AlertRuleType.RSI_THRESHOLD
        assert "超卖" in event.message
        assert event.trigger_value == 25.0
        assert event.source == "indicator"

    @pytest.mark.asyncio
    async def test_create_indicator_event_macd(self, mock_redis):
        """创建 MACD 指标事件"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis)
        rule = _make_rule(AlertRuleType.MACD_CROSS, metadata={"direction": "golden"})
        event = engine._create_indicator_event(
            rule, "AAPL", {"macd_line": 0.5, "signal_line": 0.3}, time.time()
        )

        assert "金叉" in event.message
        assert event.source == "indicator"

    @pytest.mark.asyncio
    async def test_create_indicator_event_ma(self, mock_redis):
        """创建 MA 指标事件"""
        from backend.workers.alert_engine import AlertEngine

        engine = AlertEngine(mock_redis)
        rule = _make_rule(
            AlertRuleType.MA_CROSS,
            metadata={"direction": "golden", "short_period": 10, "long_period": 20},
        )
        event = engine._create_indicator_event(
            rule, "AAPL", {"ma_10": 155.0, "ma_20": 150.0}, time.time()
        )

        assert "上穿" in event.message
        assert event.source == "indicator"
