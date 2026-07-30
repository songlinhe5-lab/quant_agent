"""单测：domain/algo_analytics.AlgoAnalytics

覆盖：滑点 / VWAP 偏离 / 参与率 / Implementation Shortfall / 时间分布 /
完整执行报告结构 与 执行质量评估分级。
"""

import pytest

from backend.domain.algo_analytics import AlgoAnalytics


def test_compute_slippage_buy_favorable():
    # 买入实际价低于基准 -> 正滑点（有利）
    assert AlgoAnalytics.compute_slippage(actual_avg_price=99.0, benchmark_price=100.0, side="BUY") == 100.0


def test_compute_slippage_buy_unfavorable():
    assert AlgoAnalytics.compute_slippage(actual_avg_price=101.0, benchmark_price=100.0, side="BUY") == -100.0


def test_compute_slippage_sell_favorable():
    # 卖出实际价高于基准 -> 正滑点（有利）
    assert AlgoAnalytics.compute_slippage(actual_avg_price=101.0, benchmark_price=100.0, side="SELL") == 100.0


def test_compute_slippage_side_case_insensitive():
    assert AlgoAnalytics.compute_slippage(actual_avg_price=99.0, benchmark_price=100.0, side="buy") == 100.0


def test_compute_slippage_invalid_inputs():
    assert AlgoAnalytics.compute_slippage(0, 100.0, "BUY") == 0.0
    assert AlgoAnalytics.compute_slippage(100.0, 0, "BUY") == 0.0


def test_vwap_deviation():
    assert AlgoAnalytics.vwap_deviation(actual_vwap=99.0, market_vwap=100.0) == 100.0
    assert AlgoAnalytics.vwap_deviation(100.0, 0) == 0.0


def test_participation_rate():
    assert AlgoAnalytics.participation_rate(filled_qty=500, market_volume=10000) == 0.05
    assert AlgoAnalytics.participation_rate(500, 0) == 0.0


def test_implementation_shortfall():
    # 买入：实际成本高于纸面 -> 正缺口
    assert AlgoAnalytics.implementation_shortfall(actual_cost=1010.0, paper_cost=1000.0, side="BUY") == 100.0
    # 卖出：纸面收入高于实际 -> 正缺口
    assert AlgoAnalytics.implementation_shortfall(actual_cost=990.0, paper_cost=1000.0, side="SELL") == 100.0
    # paper_cost <= 0 防御
    assert AlgoAnalytics.implementation_shortfall(100.0, 0, "BUY") == 0.0


def test_time_distribution_empty():
    assert AlgoAnalytics.time_distribution([], 60) == []


def test_time_distribution_buckets():
    fills = [
        {"timestamp": 0, "qty": 100, "price": 10.0},  # bucket 0
        {"timestamp": 120, "qty": 100, "price": 12.0},  # bucket 0
        {"timestamp": 300, "qty": 200, "price": 20.0},  # bucket 1
    ]
    dist = AlgoAnalytics.time_distribution(fills, total_duration_minutes=10)
    # duration 10min -> 3 个 5min 桶
    assert len(dist) == 3
    assert dist[0]["qty"] == 200
    assert dist[0]["avg_price"] == 11.0
    assert dist[0]["pct_of_total"] == pytest.approx(50.0)
    assert dist[1]["qty"] == 200
    assert dist[1]["pct_of_total"] == pytest.approx(50.0)
    assert dist[2]["qty"] == 0  # 空桶
    assert dist[0]["time_range"] == "0-5min"


def test_execution_report_structure_and_assessment():
    report = AlgoAnalytics.execution_report(
        algo_id="algo-1",
        algo_type="VWAP",
        symbol="AAPL",
        side="BUY",
        target_qty=1000,
        filled_qty=1000,
        total_cost=99_000.0,
        benchmark_price=100.0,
        market_volume=1_000_000,
        market_vwap=100.0,
        fills=[{"timestamp": 0, "qty": 500, "price": 99.0}, {"timestamp": 300, "qty": 500, "price": 99.0}],
        duration_minutes=10,
    )
    assert report["algo_id"] == "algo-1"
    assert report["summary"]["completion_pct"] == 100.0
    assert report["summary"]["actual_avg_price"] == 99.0
    # 滑点 = (100-99)/100*10000 = 100 bps -> EXCELLENT
    assert report["quality_metrics"]["slippage_bps"] == 100.0
    assert report["quality_metrics"]["participation_rate"] == pytest.approx(0.1)
    assert report["assessment"] == "EXCELLENT"
    assert len(report["time_distribution"]) == 3


def test_assess_execution_tiers():
    assert AlgoAnalytics._assess_execution(10, 0, 0) == "EXCELLENT"
    assert AlgoAnalytics._assess_execution(2, 0, 0) == "GOOD"
    assert AlgoAnalytics._assess_execution(-2, 0, 0) == "ACCEPTABLE"
    assert AlgoAnalytics._assess_execution(-10, 0, 0) == "POOR"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
