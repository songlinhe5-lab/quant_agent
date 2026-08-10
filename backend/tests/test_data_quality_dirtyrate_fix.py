"""
SVC-04 回归: 脏数据率语义修复
===========================

修复前 dirty_rate = anomaly_count / total_records, 单条记录若触发多条异常
(如零价×4 + 负量) 会使 dirty_rate > 1.0 (300%), 污染 DQ-04 Grafana 面板。
修复后 dirty_rate = 含异常记录数 / 总记录数, 恒 <= 1.0。
"""

import time

from prometheus_client import REGISTRY

from backend.services.data_quality.monitor import DataQualityMonitor


def _quote(ticker, **over):
    base = {
        "ticker": ticker,
        "open": 150.0,
        "high": 155.0,
        "low": 149.0,
        "close": 153.0,
        "volume": 1000000,
        "timestamp": time.time(),
    }
    base.update(over)
    return base


def test_dirty_rate_bounded_one():
    m = DataQualityMonitor("fix_bounded")
    # 1 条正常 + 1 条多异常脏数据
    m.validate_quote(_quote("AAPL"))
    m.validate_quote(_quote("TSLA", open=0, high=0, low=0, close=0, volume=-5))
    assert m.get_metrics().dirty_records == 1
    assert m.get_metrics().total_records == 2
    assert m.get_metrics().dirty_rate == 0.5  # 1/2, 而非 5/2=250%
    assert m.get_metrics().dirty_rate <= 1.0


def test_dirty_rate_all_clean():
    m = DataQualityMonitor("fix_clean")
    for i in range(10):
        m.validate_quote(_quote(f"S{i}"))
    assert m.get_metrics().dirty_rate == 0.0
    assert REGISTRY.get_sample_value("quant_data_quality_dirty_rate", {"source": "fix_clean"}) == 0.0


def test_dirty_rate_all_dirty():
    m = DataQualityMonitor("fix_alldirty")
    for i in range(4):
        m.validate_quote(_quote(f"Z{i}", close=0))
    assert m.get_metrics().dirty_rate == 1.0
    assert REGISTRY.get_sample_value("quant_data_quality_dirty_rate", {"source": "fix_alldirty"}) == 1.0
    assert REGISTRY.get_sample_value("quant_data_quality_total_records", {"source": "fix_alldirty"}) == 4.0
