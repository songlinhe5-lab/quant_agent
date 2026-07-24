"""
Strategy Version Service + Ticker Service + 更多 AlertEngine 深度覆盖测试
目标: 覆盖 strategy_version_service.py, ticker_service.py, alert_engine.py 的剩余未覆盖分支
"""

import json
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# Strategy Version Service 测试
# ─────────────────────────────────────────────


class TestStrategyVersionService:
    """Strategy Version Service 测试"""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    def test_get_version_found(self, mock_db):
        """get_version: 找到版本"""
        from backend.services.strategy_version_service import get_version

        mock_version = MagicMock()
        mock_version.id = "v1"
        mock_version.strategy_id = "test_strategy"
        mock_version.seq = 1
        mock_version.code = "print('hello')"
        mock_version.code_hash = "abc123"
        mock_version.source = "manual"
        mock_version.message = "Initial version"
        mock_version.parent_id = None
        mock_version.params_schema = None
        mock_version.created_at = None

        mock_db.query.return_value.filter.return_value.first.return_value = mock_version

        result = get_version(mock_db, "v1")
        assert result is not None
        assert result["id"] == "v1"
        assert result["code"] == "print('hello')"

    def test_get_version_not_found(self, mock_db):
        """get_version: 未找到版本"""
        from backend.services.strategy_version_service import get_version

        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = get_version(mock_db, "nonexistent")
        assert result is None

    def test_restore_version_success(self, mock_db):
        """restore_version: 成功恢复版本"""
        from backend.services.strategy_version_service import restore_version

        mock_source = MagicMock()
        mock_source.code = "print('restored')"
        mock_source.params_schema = None

        # 第一次查询返回源版本，第二次查询返回 None（新版本）
        mock_db.query.return_value.filter.return_value.first.side_effect = [mock_source, None]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        with patch("backend.services.strategy_version_service.save_version") as mock_save:
            mock_save.return_value = {"version_id": "v2", "seq": 2, "code_hash": "def456", "is_new": True}
            result = restore_version(mock_db, "test_strategy", "v1")
            assert result is not None
            mock_save.assert_called_once()

    def test_restore_version_not_found(self, mock_db):
        """restore_version: 源版本不存在"""
        from backend.services.strategy_version_service import restore_version

        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = restore_version(mock_db, "test_strategy", "nonexistent")
        assert result is None

    def test_import_drafts_no_dir(self, mock_db):
        """import_drafts: 目录不存在"""
        from backend.services.strategy_version_service import import_drafts

        result = import_drafts(mock_db, "/nonexistent/path")
        assert result == 0

    def test_import_drafts_success(self, mock_db):
        """import_drafts: 成功导入"""
        from backend.services.strategy_version_service import import_drafts

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            test_file = os.path.join(tmpdir, "test_strategy.py")
            with open(test_file, "w") as f:
                f.write("print('test')")

            # Mock 数据库查询 - 没有已存在的策略
            mock_db.query.return_value.filter.return_value.first.return_value = None

            with patch("backend.services.strategy_version_service.save_version") as mock_save:
                mock_save.return_value = {"version_id": "v1", "seq": 1, "code_hash": "abc", "is_new": True}
                result = import_drafts(mock_db, tmpdir)
                assert result == 1
                mock_save.assert_called_once()

    def test_import_drafts_skip_existing(self, mock_db):
        """import_drafts: 跳过已存在的策略"""
        from backend.services.strategy_version_service import import_drafts

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "existing_strategy.py")
            with open(test_file, "w") as f:
                f.write("print('existing')")

            # Mock 数据库查询 - 策略已存在
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

            result = import_drafts(mock_db, tmpdir)
            assert result == 0

    def test_import_drafts_skip_non_py(self, mock_db):
        """import_drafts: 跳过非 .py 文件"""
        from backend.services.strategy_version_service import import_drafts

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建非 .py 文件
            test_file = os.path.join(tmpdir, "readme.txt")
            with open(test_file, "w") as f:
                f.write("not a strategy")

            result = import_drafts(mock_db, tmpdir)
            assert result == 0


# ─────────────────────────────────────────────
# Ticker Service 测试
# ─────────────────────────────────────────────


class TestTickerService:
    """Ticker Service 测试"""

    @pytest.fixture
    def service(self):
        from backend.services.ticker_service import TickerService

        return TickerService()

    @pytest.mark.asyncio
    async def test_search_tickers_cache_hit(self, service):
        """search_tickers: 缓存命中"""
        cached_data = [{"symbol": "AAPL", "name": "Apple", "type": "stock"}]
        with patch("backend.services.ticker_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
            result = await service.search_tickers("AAPL")
            assert result["status"] == "success"
            assert result["data"] == cached_data

    @pytest.mark.asyncio
    async def test_search_tickers_db_query(self, service):
        """search_tickers: 数据库查询"""
        with patch("backend.services.ticker_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            with patch("backend.services.ticker_service.SessionLocal") as mock_session:
                mock_db = MagicMock()
                mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session.return_value.__exit__ = MagicMock(return_value=False)

                # Mock 查询结果
                mock_row = MagicMock()
                mock_row.symbol = "AAPL"
                mock_row.name = "Apple Inc"
                mock_row.type = "stock"
                mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
                    mock_row
                ]

                with patch("backend.services.ticker_service.engine") as mock_engine:
                    mock_engine.dialect.name = "sqlite"
                    result = await service.search_tickers("AAPL")
                    assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_tickers_error(self, service):
        """search_tickers: 查询异常"""
        with patch("backend.services.ticker_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(side_effect=Exception("Redis error"))
            result = await service.search_tickers("AAPL")
            assert result["status"] == "error"


# ─────────────────────────────────────────────
# AlertEngine 更多测试
# ─────────────────────────────────────────────


class TestAlertEngineMore:
    """AlertEngine 更多测试"""

    @pytest.fixture
    def engine(self):
        from backend.workers.alert_engine import AlertEngine

        mock_redis = AsyncMock()
        return AlertEngine(redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_fetch_indicators_no_market_data(self, engine):
        """_fetch_indicators: 无 market_data 服务"""
        engine._market_data = None
        result = await engine._fetch_indicators("AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_indicators_success(self, engine):
        """_fetch_indicators: 成功获取指标"""
        mock_market_data = AsyncMock()
        mock_market_data.get_tech_indicators = AsyncMock(
            return_value={
                "status": "success",
                "data": {"indicators": {"rsi": 30, "macd": {"histogram": 0.5}}},
            }
        )
        engine._market_data = mock_market_data

        with patch("backend.workers.alert_engine.extract_indicators_from_tech_data") as mock_extract:
            mock_extract.return_value = {"rsi": 30, "macd_histogram": 0.5}
            result = await engine._fetch_indicators("AAPL")
            assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_indicators_error(self, engine):
        """_fetch_indicators: 获取失败"""
        mock_market_data = AsyncMock()
        mock_market_data.get_tech_indicators = AsyncMock(return_value={"status": "error", "message": "Failed"})
        engine._market_data = mock_market_data
        result = await engine._fetch_indicators("AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_indicators_exception(self, engine):
        """_fetch_indicators: 异常"""
        mock_market_data = AsyncMock()
        mock_market_data.get_tech_indicators = AsyncMock(side_effect=Exception("Network error"))
        engine._market_data = mock_market_data
        result = await engine._fetch_indicators("AAPL")
        assert result is None

    def test_create_event_price_cross_up(self, engine):
        """_create_event: PRICE_CROSS 上穿"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r1",
            name="Cross Test",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_CROSS,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        engine._last_prices["AAPL"] = 145.0  # 之前价格低于阈值
        event = engine._create_event(rule, 155.0, time.time())  # 现在价格高于阈值
        assert "上穿" in event.message

    def test_create_event_price_cross_down(self, engine):
        """_create_event: PRICE_CROSS 下穿"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r2",
            name="Cross Test",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_CROSS,
            threshold=150.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        engine._last_prices["AAPL"] = 155.0  # 之前价格高于阈值
        event = engine._create_event(rule, 145.0, time.time())  # 现在价格低于阈值
        assert "下穿" in event.message

    def test_create_event_pct_change(self, engine):
        """_create_event: PCT_CHANGE"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r3",
            name="PCT Test",
            ticker="TSLA",
            rule_type=AlertRuleType.PCT_CHANGE,
            threshold=5.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        event = engine._create_event(rule, 200.0, time.time())
        assert "涨跌幅" in event.message

    def test_create_event_volume_surge(self, engine):
        """_create_event: VOLUME_SURGE"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r4",
            name="Volume Test",
            ticker="NVDA",
            rule_type=AlertRuleType.VOLUME_SURGE,
            threshold=2.0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        event = engine._create_event(rule, 500.0, time.time())
        assert "成交量突增" in event.message

    def test_create_indicator_event_ma_cross(self, engine):
        """_create_indicator_event: MA_CROSS"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r5",
            name="MA Cross",
            ticker="AAPL",
            rule_type=AlertRuleType.MA_CROSS,
            threshold=0,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
            metadata={"short_period": 5, "long_period": 20, "direction": "golden"},
        )
        indicators = {"ma_5": 150.0, "ma_20": 145.0}
        event = engine._create_indicator_event(rule, "AAPL", indicators, time.time())
        assert "MA5/MA20" in event.message
        assert "上穿" in event.message

    def test_create_indicator_event_default(self, engine):
        """_create_indicator_event: 默认分支"""
        from backend.core.alert_models import AlertChannel, AlertRule, AlertRuleType, AlertSeverity

        rule = AlertRule(
            rule_id="r6",
            name="RSI Threshold",
            ticker="AAPL",
            rule_type=AlertRuleType.RSI_THRESHOLD,  # 使用 RSI_THRESHOLD 类型
            threshold=30,
            severity=AlertSeverity.WARNING,
            channels=[AlertChannel.IN_APP],
        )
        indicators = {"rsi": 25}
        event = engine._create_indicator_event(rule, "AAPL", indicators, time.time())
        # RSI_THRESHOLD 会走默认分支
        assert "指标告警触发" in event.message or "RSI" in event.message
