"""
AlertEngine + RiskEngine + RiskSector + SystemMonitor 深度覆盖测试
目标: 覆盖 alert_engine.py, risk_engine.py, risk_sector.py, system_monitor_service.py 的未覆盖分支
"""

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# AlertEngine 测试
# ─────────────────────────────────────────────


class TestAlertEngineRuleManagement:
    """AlertEngine 规则管理测试"""

    @pytest.fixture
    def engine(self):
        from backend.workers.alert_engine import AlertEngine

        mock_redis = AsyncMock()
        return AlertEngine(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_load_rules_with_parse_failure(self, engine):
        """load_rules: 包含解析失败的规则"""
        valid_rule = {
            "rule_id": "r1",
            "name": "Test Rule",
            "ticker": "AAPL",
            "rule_type": "price_above",
            "threshold": 150.0,
            "enabled": True,
            "channels": ["in_app"],
        }
        engine._redis.hgetall = AsyncMock(
            return_value={
                "r1": json.dumps(valid_rule),
                "r2": "invalid json {{{",  # 解析失败
            }
        )
        count = await engine.load_rules()
        assert count == 1
        assert "r1" in engine._rules

    @pytest.mark.asyncio
    async def test_load_rules_disabled_rule(self, engine):
        """load_rules: 禁用的规则不加载"""
        disabled_rule = {
            "rule_id": "r1",
            "name": "Disabled Rule",
            "ticker": "AAPL",
            "rule_type": "price_above",
            "threshold": 150.0,
            "enabled": False,
            "channels": ["in_app"],
        }
        engine._redis.hgetall = AsyncMock(return_value={"r1": json.dumps(disabled_rule)})
        count = await engine.load_rules()
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_rule(self, engine):
        """add_rule: 添加规则到引擎和 Redis"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="test_rule",
            name="Test",
            ticker="TSLA",
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=200.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        await engine.add_rule(rule)
        assert "test_rule" in engine._rules
        engine._redis.hset.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_rule(self, engine):
        """remove_rule: 移除规则"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="to_remove",
            name="Remove Me",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_BELOW,
            threshold=100.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        engine._rules["to_remove"] = rule
        engine._redis.hdel = AsyncMock(return_value=1)
        result = await engine.remove_rule("to_remove")
        assert result is True
        assert "to_remove" not in engine._rules

    @pytest.mark.asyncio
    async def test_remove_rule_not_found(self, engine):
        """remove_rule: 规则不存在"""
        engine._redis.hdel = AsyncMock(return_value=0)
        result = await engine.remove_rule("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_rule(self, engine):
        """update_rule: 更新规则"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="update_me",
            name="Original",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        engine._rules["update_me"] = rule
        rule.name = "Updated"
        await engine.update_rule(rule)
        assert engine._rules["update_me"].name == "Updated"
        engine._redis.hset.assert_called_once()

    def test_get_rules(self, engine):
        """get_rules: 获取所有规则"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r1",
            name="Rule 1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        engine._rules["r1"] = rule
        rules = engine.get_rules()
        assert len(rules) == 1
        assert rules[0].rule_id == "r1"

    def test_register_push(self, engine):
        """register_push: 注册推送通道回调"""
        from backend.core.alert_models import AlertChannel

        callback = MagicMock()
        engine.register_push(AlertChannel.TELEGRAM, callback)
        assert AlertChannel.TELEGRAM in engine._push_callbacks

    def test_stats_property(self, engine):
        """stats: 引擎统计"""
        stats = engine.stats
        assert stats["running"] is False
        assert stats["active_rules"] == 0
        assert stats["eval_count"] == 0
        assert stats["trigger_count"] == 0


class TestAlertEngineEvaluate:
    """AlertEngine 行情评估测试"""

    @pytest.fixture
    def engine(self):
        from backend.workers.alert_engine import AlertEngine

        mock_redis = AsyncMock()
        return AlertEngine(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_evaluate_quote_price_above_trigger(self, engine):
        """evaluate_quote: 价格突破上限触发告警"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r1",
            name="Price Above",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
            cooldown_seconds=60,
            last_triggered_at=0,  # 从未触发
        )
        engine._rules["r1"] = rule
        engine._redis.hset = AsyncMock()
        engine._redis.lpush = AsyncMock()
        engine._redis.ltrim = AsyncMock()

        events = await engine.evaluate_quote("AAPL", 155.0)
        assert len(events) == 1
        assert events[0].ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_evaluate_quote_price_below_trigger(self, engine):
        """evaluate_quote: 价格跌破下限触发告警"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r2",
            name="Price Below",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_BELOW,
            threshold=100.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
            cooldown_seconds=60,
            last_triggered_at=0,
        )
        engine._rules["r2"] = rule
        engine._redis.hset = AsyncMock()
        engine._redis.lpush = AsyncMock()
        engine._redis.ltrim = AsyncMock()

        events = await engine.evaluate_quote("AAPL", 95.0)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_evaluate_quote_volume_surge(self, engine):
        """evaluate_quote: 成交量突增触发告警"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r3",
            name="Volume Surge",
            ticker="TSLA",
            rule_type=AlertRuleType.VOLUME_SURGE,
            threshold=2.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
            cooldown_seconds=60,
            last_triggered_at=0,
            metadata={},
        )
        engine._rules["r3"] = rule
        engine._redis.hset = AsyncMock()
        engine._redis.lpush = AsyncMock()
        engine._redis.ltrim = AsyncMock()

        # 先设置一个基准价格
        engine._last_prices["TSLA"] = 200.0
        events = await engine.evaluate_quote("TSLA", 200.0, volume=1000000)
        # volume_surge 需要历史成交量数据，这里可能不会触发
        # 但 metadata 应该被注入
        assert rule.metadata.get("current_volume") == 1000000

    @pytest.mark.asyncio
    async def test_evaluate_quote_cooldown(self, engine):
        """evaluate_quote: 冷却期内不触发"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r4",
            name="Cooldown Test",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
            cooldown_seconds=3600,
            last_triggered_at=time.time(),  # 刚刚触发过
        )
        engine._rules["r4"] = rule
        events = await engine.evaluate_quote("AAPL", 155.0)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_evaluate_quote_no_matching_rules(self, engine):
        """evaluate_quote: 无匹配规则"""
        events = await engine.evaluate_quote("UNKNOWN", 100.0)
        assert len(events) == 0


class TestAlertEngineDispatch:
    """AlertEngine 推送分发测试"""

    @pytest.fixture
    def engine(self):
        from backend.workers.alert_engine import AlertEngine

        mock_redis = AsyncMock()
        return AlertEngine(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_dispatch_event_with_dispatcher(self, engine):
        """_dispatch_event: 使用 AlertDispatcher 推送"""
        from backend.core.alert_models import AlertChannel, AlertEvent, AlertRuleType, AlertSeverity

        mock_dispatcher = AsyncMock()
        engine._dispatcher = mock_dispatcher

        event = AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id="r1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            severity=AlertSeverity.WARNING,
            message="Test",
            trigger_value=155.0,
            threshold=150.0,
            channels=[AlertChannel.IN_APP],
            triggered_at=time.time(),
            source="test",
        )
        await engine._dispatch_event(event, [AlertChannel.IN_APP])
        mock_dispatcher.dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_event_dispatcher_error(self, engine):
        """_dispatch_event: Dispatcher 调用失败"""
        from backend.core.alert_models import AlertChannel, AlertEvent, AlertRuleType, AlertSeverity

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.side_effect = Exception("Dispatcher error")
        engine._dispatcher = mock_dispatcher

        event = AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id="r1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            severity=AlertSeverity.WARNING,
            message="Test",
            trigger_value=155.0,
            threshold=150.0,
            channels=[AlertChannel.IN_APP],
            triggered_at=time.time(),
            source="test",
        )
        # 不应该抛出异常
        await engine._dispatch_event(event, [AlertChannel.IN_APP])

    @pytest.mark.asyncio
    async def test_dispatch_event_callback_mode(self, engine):
        """_dispatch_event: 降级为旧回调模式"""
        from backend.core.alert_models import AlertChannel, AlertEvent, AlertRuleType, AlertSeverity

        callback = AsyncMock()
        engine._push_callbacks[AlertChannel.TELEGRAM] = callback

        event = AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id="r1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            severity=AlertSeverity.WARNING,
            message="Test",
            trigger_value=155.0,
            threshold=150.0,
            channels=[AlertChannel.TELEGRAM],
            triggered_at=time.time(),
            source="test",
        )
        await engine._dispatch_event(event, [AlertChannel.TELEGRAM])
        callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_dispatch_event_callback_error(self, engine):
        """_dispatch_event: 回调执行失败"""
        from backend.core.alert_models import AlertChannel, AlertEvent, AlertRuleType, AlertSeverity

        callback = AsyncMock(side_effect=Exception("Callback error"))
        engine._push_callbacks[AlertChannel.TELEGRAM] = callback

        event = AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id="r1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            severity=AlertSeverity.WARNING,
            message="Test",
            trigger_value=155.0,
            threshold=150.0,
            channels=[AlertChannel.TELEGRAM],
            triggered_at=time.time(),
            source="test",
        )
        # 不应该抛出异常
        await engine._dispatch_event(event, [AlertChannel.TELEGRAM])


class TestAlertEngineLifecycle:
    """AlertEngine 生命周期测试"""

    @pytest.fixture
    def engine(self):
        from backend.workers.alert_engine import AlertEngine

        mock_redis = AsyncMock()
        return AlertEngine(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_start_and_stop(self, engine):
        """start/stop: 启动和停止引擎"""
        engine._redis.hgetall = AsyncMock(return_value={})
        await engine.start()
        assert engine._running is True
        assert engine._task is not None

        await engine.stop()
        assert engine._running is False


# ─────────────────────────────────────────────
# RiskEngine 测试
# ─────────────────────────────────────────────


class TestRiskEngine:
    """RiskEngine 测试"""

    @pytest.fixture
    def risk_engine(self):
        from backend.services.risk_engine import RiskEngine

        return RiskEngine()

    @pytest.mark.asyncio
    async def test_get_portfolio_risk_cache_hit(self, risk_engine):
        """get_portfolio_risk: Redis 缓存命中"""
        cached_data = {"status": "success", "accounts": {}}
        with patch("backend.services.risk_engine.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
            result = await risk_engine.get_portfolio_risk(days=7)
            assert result == cached_data

    @pytest.mark.asyncio
    async def test_get_portfolio_risk_both_accounts_fail(self, risk_engine):
        """get_portfolio_risk: HK 和 US 账户均失败"""
        with patch("backend.services.risk_engine.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            with patch("backend.services.risk_engine.futu_service") as mock_futu:
                mock_futu.get_account_info = AsyncMock(side_effect=Exception("Connection failed"))
                result = await risk_engine.get_portfolio_risk(days=7)
                # 返回 empty 状态而非 error
                assert result["status"] in ("error", "empty")

    @pytest.mark.asyncio
    async def test_get_portfolio_risk_hk_success(self, risk_engine):
        """get_portfolio_risk: HK 账户成功"""
        hk_account = {
            "status": "success",
            "total_assets": 1000000,
            "cash": 500000,
            "market_val": 500000,
            "positions": [
                {"code": "00700", "name": "腾讯", "qty": 100, "price": 300, "pl_val": 1000, "market_val": 30000}
            ],
            "currency": "HKD",
        }
        with patch("backend.services.risk_engine.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            with patch("backend.services.risk_engine.futu_service") as mock_futu:
                mock_futu.get_account_info = AsyncMock(side_effect=[hk_account, Exception("US failed")])

                with patch.object(risk_engine, "_calc_risk_metrics", new_callable=AsyncMock) as mock_risk:
                    mock_risk.return_value = ({}, {})
                    with patch.object(risk_engine, "_get_nav_snapshots", new_callable=AsyncMock) as mock_nav:
                        mock_nav.return_value = []
                        result = await risk_engine.get_portfolio_risk(days=7)
                        assert result["status"] == "success"
                        assert "HK" in result["accounts"]

    def test_calc_kpi(self, risk_engine):
        """_calc_kpi: 计算 KPI 指标"""
        positions = [
            {"pl_val": 1000, "market_val": 50000},
            {"pl_val": -500, "market_val": 30000},
        ]
        kpi = risk_engine._calc_kpi(1000000, 500000, 500000, positions, "HKD")
        assert kpi["nav"] == 1000000
        assert kpi["today_pl"] == 500
        assert "HK$" in kpi["nav_fmt"]

    def test_calc_kpi_usd(self, risk_engine):
        """_calc_kpi: USD 货币"""
        kpi = risk_engine._calc_kpi(100000, 50000, 50000, [], "USD")
        assert "$" in kpi["nav_fmt"]
        assert "HK$" not in kpi["nav_fmt"]

    def test_calc_exposure(self, risk_engine):
        """_calc_exposure: 计算敞口"""
        positions = [
            {"code": "00700", "market_val": 30000},
            {"code": "09988", "market_val": 20000},
        ]
        exposure = risk_engine._calc_exposure(1000000, 500000, 50000, positions)
        # 返回的是列表格式
        assert isinstance(exposure, list)
        assert len(exposure) > 0


# ─────────────────────────────────────────────
# RiskSector 测试
# ─────────────────────────────────────────────


class TestRiskSector:
    """SectorAnalyzer 测试"""

    @pytest.fixture
    def analyzer(self):
        from backend.services.risk_sector import SectorAnalyzer

        return SectorAnalyzer()

    @pytest.mark.asyncio
    async def test_get_sector_map_empty_positions(self, analyzer):
        """_get_sector_map: 空持仓"""
        result = await analyzer._get_sector_map([], "HK")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_sector_map_cache_hit(self, analyzer):
        """_get_sector_map: Redis 缓存命中"""
        positions = [{"code": "00700"}, {"code": "09988"}]
        cached_map = {"00700": "科技", "09988": "电商"}
        with patch("backend.services.risk_sector.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached_map))
            result = await analyzer._get_sector_map(positions, "HK")
            assert result == cached_map

    @pytest.mark.asyncio
    async def test_get_sector_map_futu_success(self, analyzer):
        """_get_sector_map: Futu 获取成功"""
        positions = [{"code": "00700"}]
        futu_data = {
            "status": "success",
            "data": [{"code": "00700", "industry": "科技"}],
        }
        with patch("backend.services.risk_sector.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            # futu_service 是在函数内部导入的
            with patch("backend.services.futu_service.futu_service") as mock_futu:
                mock_futu.get_stock_basicinfo = AsyncMock(return_value=futu_data)
                result = await analyzer._get_sector_map(positions, "HK")
                assert result.get("00700") == "科技"

    @pytest.mark.asyncio
    async def test_get_sector_map_unknown_fallback(self, analyzer):
        """_get_sector_map: 未知行业兜底"""
        positions = [{"code": "UNKNOWN"}]
        with patch("backend.services.risk_sector.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            # futu_service 是在函数内部导入的
            with patch("backend.services.futu_service.futu_service") as mock_futu:
                mock_futu.get_stock_basicinfo = AsyncMock(return_value={"status": "error"})
                result = await analyzer._get_sector_map(positions, "HK")
                assert result.get("UNKNOWN") == "未知"


# ─────────────────────────────────────────────
# SystemMonitorService 测试
# ─────────────────────────────────────────────


class TestSystemMonitorService:
    """SystemMonitorService 测试"""

    @pytest.fixture
    def monitor(self):
        from backend.services.system_monitor_service import SystemMonitorService

        return SystemMonitorService()

    def test_save_performance_log_success(self, monitor):
        """_save_performance_log: 成功保存日志"""
        with patch("backend.services.system_monitor_service.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            monitor._save_performance_log("test_type", 100.5, "/api/test", "test details")
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()

    def test_save_performance_log_error(self, monitor):
        """_save_performance_log: 保存失败"""
        with patch("backend.services.system_monitor_service.SessionLocal") as mock_session:
            mock_session.side_effect = Exception("DB error")
            # 不应该抛出异常
            monitor._save_performance_log("test_type", 100.5)
