"""metrics 单元测试 — 验证 FMP Prometheus 指标 helper 行为。"""

from data_subservice._internal import metrics


def _gauge_value(metric):
    """从 prometheus_client Metric 取出第一个 sample 的数值。"""
    return metric.collect()[0].samples[0].value


def _counter_value(metric):
    """Counter 也通过 collect -> samples -> value 读取累计值。"""
    return metric.collect()[0].samples[0].value


class TestMetricsHelpers:
    def test_set_process_thread_metrics(self):
        metrics.set_process_thread_metrics(747, 2000)
        assert _gauge_value(metrics.PROCESS_THREADS) == 747
        assert _gauge_value(metrics.PROCESS_THREAD_WARN) == 2000

    def test_observe_credit_consume_with_delta(self):
        before = _counter_value(metrics.FMP_CREDIT_SPENT_TOTAL)
        metrics.observe_credit_consume(50, 950, 1000)
        after = _counter_value(metrics.FMP_CREDIT_SPENT_TOTAL)
        assert after - before == 50
        assert _gauge_value(metrics.FMP_CREDIT_REMAINING) == 950
        assert _gauge_value(metrics.FMP_CREDIT_LIMIT) == 1000

    def test_observe_credit_consume_zero_delta_skips_counter(self):
        before = _counter_value(metrics.FMP_CREDIT_SPENT_TOTAL)
        metrics.observe_credit_consume(0, 900, 1000)
        after = _counter_value(metrics.FMP_CREDIT_SPENT_TOTAL)
        # delta<=0 时 Counter 不 inc，值不变（但 gauges 仍刷新）
        assert after == before
        assert _gauge_value(metrics.FMP_CREDIT_REMAINING) == 900

    def test_set_credit_gauges(self):
        metrics.set_credit_gauges(12345, 888, 1000)
        assert _gauge_value(metrics.FMP_CREDIT_REMAINING) == 888
        assert _gauge_value(metrics.FMP_CREDIT_LIMIT) == 1000

    def test_registry_is_collector_registry(self):
        from prometheus_client import CollectorRegistry

        assert isinstance(metrics.registry, CollectorRegistry)
