"""
SVC-04: 数据质量监控服务 — 单元测试
====================================

验证:
  1. 字段完整性检查
  2. 价格异常检测（零价/负价/跳变）
  3. OHLC 一致性检查
  4. 时间戳新鲜度检测
  5. 质量等级计算
  6. 告警回调触发
  7. Prometheus 指标输出
"""

import time
from unittest.mock import MagicMock

import pytest

from backend.services.data_quality_monitor import (
    AnomalyType,
    DataQualityMonitor,
    QualityLevel,
)

# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def monitor():
    """创建 Futu 数据源监控器"""
    return DataQualityMonitor("futu")


@pytest.fixture
def good_quote():
    """正常行情数据"""
    return {
        "ticker": "AAPL",
        "open": 150.0,
        "high": 155.0,
        "low": 149.0,
        "close": 153.0,
        "volume": 1000000,
        "timestamp": time.time(),
    }


# ─────────────────────────────────────────
#  测试: 字段完整性
# ─────────────────────────────────────────


class TestFieldCompleteness:
    """SVC-04: 字段完整性检查"""

    def test_good_quote_passes(self, monitor, good_quote):
        """完整数据通过校验"""
        result = monitor.validate_quote(good_quote)
        assert result["valid"] is True
        assert result["anomalies"] == []
        assert result["quality"] == QualityLevel.GOOD.value

    def test_missing_required_fields(self, monitor):
        """缺少必填字段触发异常"""
        quote = {"ticker": "AAPL", "open": 150.0}  # 缺少 high/low/close/volume
        result = monitor.validate_quote(quote)
        assert result["valid"] is False
        missing_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.MISSING_FIELD.value]
        assert len(missing_anomalies) == 1
        assert set(missing_anomalies[0]["fields"]) == {"high", "low", "close", "volume"}

    def test_null_field_treated_as_missing(self, monitor):
        """None 值视为字段缺失"""
        quote = {
            "ticker": "AAPL",
            "open": 150.0,
            "high": None,
            "low": 149.0,
            "close": 153.0,
            "volume": 1000000,
            "timestamp": time.time(),
        }
        result = monitor.validate_quote(quote)
        assert result["valid"] is False
        missing = [a for a in result["anomalies"] if a["type"] == AnomalyType.MISSING_FIELD.value]
        assert "high" in missing[0]["fields"]


# ─────────────────────────────────────────
#  测试: 价格异常
# ─────────────────────────────────────────


class TestPriceAnomalies:
    """SVC-04: 价格异常检测"""

    def test_zero_price_detected(self, monitor, good_quote):
        """零价检测"""
        good_quote["close"] = 0
        result = monitor.validate_quote(good_quote)
        assert result["valid"] is False
        zero_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.ZERO_PRICE.value]
        assert len(zero_anomalies) == 1
        assert zero_anomalies[0]["severity"] == "critical"

    def test_negative_price_detected(self, monitor, good_quote):
        """负价检测"""
        good_quote["low"] = -5.0
        result = monitor.validate_quote(good_quote)
        assert result["valid"] is False
        neg_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.NEGATIVE_PRICE.value]
        assert len(neg_anomalies) == 1

    def test_price_jump_detected(self, monitor):
        """价格跳变检测"""
        # 第一条正常
        quote1 = {"ticker": "AAPL", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000, "timestamp": time.time()}
        monitor.validate_quote(quote1)

        # 第二条跳变 60%
        quote2 = {"ticker": "AAPL", "open": 165, "high": 170, "low": 160, "close": 168, "volume": 1000, "timestamp": time.time()}
        result = monitor.validate_quote(quote2)
        jump_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.PRICE_JUMP.value]
        assert len(jump_anomalies) > 0
        assert jump_anomalies[0]["jump_pct"] > 50

    def test_negative_volume_detected(self, monitor, good_quote):
        """负成交量检测"""
        good_quote["volume"] = -100
        result = monitor.validate_quote(good_quote)
        assert result["valid"] is False
        vol_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.NEGATIVE_VOLUME.value]
        assert len(vol_anomalies) == 1


# ─────────────────────────────────────────
#  测试: OHLC 一致性
# ─────────────────────────────────────────


class TestOHLCConsistency:
    """SVC-04: OHLC 逻辑一致性"""

    def test_high_less_than_low_detected(self, monitor, good_quote):
        """high < low 逻辑错误"""
        good_quote["high"] = 140.0
        good_quote["low"] = 150.0
        result = monitor.validate_quote(good_quote)
        ohlc_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.OHLC_INCONSISTENCY.value]
        assert len(ohlc_anomalies) == 1
        assert ohlc_anomalies[0]["severity"] == "critical"

    def test_valid_ohlc_no_anomaly(self, monitor, good_quote):
        """正常 OHLC 不触发异常"""
        result = monitor.validate_quote(good_quote)
        ohlc_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.OHLC_INCONSISTENCY.value]
        assert len(ohlc_anomalies) == 0


# ─────────────────────────────────────────
#  测试: 时间戳新鲜度
# ─────────────────────────────────────────


class TestTimestampFreshness:
    """SVC-04: 时间戳新鲜度"""

    def test_stale_timestamp_detected(self, monitor, good_quote):
        """过期时间戳检测"""
        good_quote["timestamp"] = time.time() - 120  # 2 分钟前
        result = monitor.validate_quote(good_quote)
        stale_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.STALE_TIMESTAMP.value]
        assert len(stale_anomalies) == 1

    def test_fresh_timestamp_passes(self, monitor, good_quote):
        """新鲜时间戳通过"""
        good_quote["timestamp"] = time.time() - 5  # 5 秒前
        result = monitor.validate_quote(good_quote)
        stale_anomalies = [a for a in result["anomalies"] if a["type"] == AnomalyType.STALE_TIMESTAMP.value]
        assert len(stale_anomalies) == 0


# ─────────────────────────────────────────
#  测试: 质量等级
# ─────────────────────────────────────────


class TestQualityLevel:
    """SVC-04: 质量等级计算"""

    def test_good_quality(self, monitor, good_quote):
        """全正常数据为 GOOD"""
        monitor.validate_quote(good_quote)
        assert monitor.get_metrics().quality_level == QualityLevel.GOOD

    def test_degraded_quality_on_high_dirty_rate(self, monitor):
        """脏数据率超阈值降级为 DEGRADED"""
        # 制造大量异常数据
        for i in range(20):
            quote = {"ticker": f"STOCK_{i}"}  # 缺少所有必填字段
            monitor.validate_quote(quote)

        metrics = monitor.get_metrics()
        assert metrics.quality_level in [QualityLevel.DEGRADED, QualityLevel.POOR, QualityLevel.UNUSABLE]

    def test_metrics_accumulate(self, monitor, good_quote):
        """指标累积正确"""
        for _ in range(5):
            monitor.validate_quote(good_quote)

        metrics = monitor.get_metrics()
        assert metrics.total_records == 5
        assert metrics.valid_records == 5
        assert metrics.anomaly_count == 0


# ─────────────────────────────────────────
#  测试: 告警回调
# ─────────────────────────────────────────


class TestAlertCallback:
    """SVC-04: 告警回调"""

    def test_alert_triggered_on_high_dirty_rate(self, monitor):
        """脏数据率超阈值触发告警"""
        alert_fn = MagicMock()
        monitor.set_alert_callback(alert_fn)

        # 制造超过阈值的脏数据
        for i in range(30):
            quote = {"ticker": f"BAD_{i}"}  # 全缺字段
            monitor.validate_quote(quote)

        assert alert_fn.called

    def test_no_alert_when_quality_good(self, monitor, good_quote):
        """质量正常时不触发告警"""
        alert_fn = MagicMock()
        monitor.set_alert_callback(alert_fn)

        monitor.validate_quote(good_quote)
        assert not alert_fn.called


# ─────────────────────────────────────────
#  测试: Prometheus 指标
# ─────────────────────────────────────────


class TestPrometheusMetrics:
    """SVC-04: Prometheus 指标输出"""

    def test_prometheus_labels_structure(self, monitor, good_quote):
        """Prometheus 指标结构正确"""
        monitor.validate_quote(good_quote)
        labels = monitor.get_prometheus_labels()

        assert f"data_quality_total_records_{monitor.source}" in labels
        assert f"data_quality_dirty_rate_{monitor.source}" in labels
        assert f"data_quality_completeness_{monitor.source}" in labels
        assert f"data_quality_avg_latency_ms_{monitor.source}" in labels

    def test_prometheus_values_correct(self, monitor, good_quote):
        """Prometheus 指标值正确"""
        monitor.validate_quote(good_quote)
        labels = monitor.get_prometheus_labels()

        assert labels[f"data_quality_total_records_{monitor.source}"] == 1
        assert labels[f"data_quality_dirty_rate_{monitor.source}"] == 0.0
        assert labels[f"data_quality_completeness_{monitor.source}"] == 1.0


# ─────────────────────────────────────────
#  测试: 重置
# ─────────────────────────────────────────


class TestReset:
    """SVC-04: 指标重置"""

    def test_reset_clears_all_metrics(self, monitor, good_quote):
        """重置后所有指标归零"""
        monitor.validate_quote(good_quote)
        monitor.reset()

        metrics = monitor.get_metrics()
        assert metrics.total_records == 0
        assert metrics.valid_records == 0
        assert metrics.anomaly_count == 0
        assert metrics.quality_level == QualityLevel.GOOD
