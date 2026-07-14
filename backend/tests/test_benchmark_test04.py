"""
性能基准测试 (TEST-04)
=======================

pytest-benchmark: K线聚合 / 技术指标 / 告警评估 / 指标评估器 baseline，
防止性能回归。

用法:
  # 安装依赖
  pip install pytest-benchmark

  # 运行基准
  pytest backend/tests/test_benchmark_test04.py --benchmark-only

  # 对比基准
  pytest backend/tests/test_benchmark_test04.py --benchmark-only --benchmark-compare

  # 输出 JSON
  pytest backend/tests/test_benchmark_test04.py --benchmark-only --benchmark-json=benchmark.json

目标 (P95):
  - 技术指标计算 (250 bars): < 50ms
  - 告警规则评估 (1000 rules): < 10ms
  - 指标评估器 (100 tickers): < 20ms
  - K线序列化 (1000 bars): < 5ms
"""

import numpy as np
import pandas as pd
import pytest

from backend.core.alert_models import (
    AlertChannel,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    evaluate_indicator_rule,
    evaluate_price_rule,
)
from backend.services.indicator_evaluator import (
    IndicatorEvaluator,
    extract_indicators_from_tech_data,
)

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def sample_kline_df() -> pd.DataFrame:
    """生成 250 个交易日的模拟 K 线数据"""
    np.random.seed(42)
    n = 250
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base_price = 150.0
    returns = np.random.normal(0.001, 0.02, n)
    close = base_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.randint(1_000_000, 50_000_000, n).astype(float)

    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


@pytest.fixture
def sample_tech_data() -> dict:
    """模拟 get_tech_indicators 返回"""
    return {
        "status": "success",
        "data": {
            "trend": [
                {
                    "RSI_14": 55.3,
                    "MACD_12_26_9": 0.45,
                    "MACDs_12_26_9": 0.32,
                    "MACDh_12_26_9": 0.13,
                    "SMA_10": 152.3,
                    "SMA_20": 148.7,
                    "SMA_50": 145.1,
                    "K_9_3_3": 65.0,
                    "D_9_3_3": 58.0,
                    "J_9_3_3": 79.0,
                    "ATRr_14": 2.5,
                }
            ]
        },
    }


@pytest.fixture
def many_rules() -> list:
    """生成 1000 条告警规则（混合类型）"""
    rules = []
    rule_types = [
        AlertRuleType.PRICE_ABOVE,
        AlertRuleType.PRICE_BELOW,
        AlertRuleType.PCT_CHANGE,
        AlertRuleType.VOLUME_SURGE,
    ]
    for i in range(1000):
        rt = rule_types[i % len(rule_types)]
        rules.append(
            AlertRule(
                rule_id=f"bench-rule-{i}",
                name=f"Benchmark Rule {i}",
                ticker="AAPL",
                rule_type=rt,
                threshold=150.0 + (i % 50),
                severity=AlertSeverity.WARNING,
                channels=[AlertChannel.IN_APP],
                cooldown_seconds=60,
                metadata={},
            )
        )
    return rules


@pytest.fixture
def indicator_rules() -> list:
    """生成 100 条指标类规则"""
    rules = []
    rule_types = [
        AlertRuleType.RSI_THRESHOLD,
        AlertRuleType.MACD_CROSS,
        AlertRuleType.MA_CROSS,
    ]
    for i in range(100):
        rt = rule_types[i % len(rule_types)]
        metadata = {}
        if rt == AlertRuleType.MACD_CROSS:
            metadata = {"direction": "golden"}
        elif rt == AlertRuleType.MA_CROSS:
            metadata = {"direction": "golden", "short_period": 10, "long_period": 20}
        rules.append(
            AlertRule(
                rule_id=f"bench-ind-{i}",
                name=f"Benchmark Indicator {i}",
                ticker="AAPL",
                rule_type=rt,
                threshold=30.0 if rt == AlertRuleType.RSI_THRESHOLD else 0,
                severity=AlertSeverity.WARNING,
                channels=[AlertChannel.IN_APP],
                cooldown_seconds=60,
                metadata=metadata,
            )
        )
    return rules


# ─── BENCH-01: 技术指标计算 ─────────────────────────────────────────


class TestTechIndicatorBenchmark:
    """技术指标计算性能基准"""

    def test_ma_rolling_250bars(self, benchmark, sample_kline_df):
        """MA 均线计算 (250 bars, 5 条均线)"""
        close = sample_kline_df["Close"]
        periods = [5, 10, 20, 50, 200]

        def compute():
            return {p: close.rolling(window=p).mean() for p in periods}

        result = benchmark(compute)
        assert all(len(v.dropna()) > 0 for v in result.values())

    def test_rsi_ewm_250bars(self, benchmark, sample_kline_df):
        """RSI 计算 (250 bars)"""
        close = sample_kline_df["Close"]

        def compute():
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            rs = gain.ewm(alpha=1 / 14, adjust=False).mean() / loss.ewm(alpha=1 / 14, adjust=False).mean()
            return 100 - (100 / (1 + rs))

        result = benchmark(compute)
        assert len(result.dropna()) > 0

    def test_macd_250bars(self, benchmark, sample_kline_df):
        """MACD 计算 (250 bars)"""
        close = sample_kline_df["Close"]

        def compute():
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            hist = macd - signal
            return macd, signal, hist

        macd, signal, hist = benchmark(compute)
        assert len(macd.dropna()) > 0

    def test_bollinger_250bars(self, benchmark, sample_kline_df):
        """布林带计算 (250 bars)"""
        close = sample_kline_df["Close"]

        def compute():
            mid = close.rolling(window=20).mean()
            std = close.rolling(window=20).std()
            upper = mid + 2 * std
            lower = mid - 2 * std
            return upper, mid, lower

        upper, mid, lower = benchmark(compute)
        assert len(mid.dropna()) > 0


# ─── BENCH-02: 告警规则评估 ─────────────────────────────────────────


class TestAlertEvaluationBenchmark:
    """告警规则评估性能基准"""

    def test_price_rule_1000rules(self, benchmark, many_rules):
        """价格规则评估 1000 条"""
        price = 175.0
        prev_price = 170.0

        def evaluate_all():
            return [evaluate_price_rule(r, price, prev_price) for r in many_rules]

        results = benchmark(evaluate_all)
        assert isinstance(results, list)
        assert len(results) == 1000

    def test_indicator_rule_100rules(self, benchmark, indicator_rules, sample_tech_data):
        """指标规则评估 100 条"""
        indicators = extract_indicators_from_tech_data(sample_tech_data)
        prev_indicators = {k: v * 0.98 for k, v in indicators.items()}

        def evaluate_all():
            return [evaluate_indicator_rule(r, indicators, prev_indicators) for r in indicator_rules]

        results = benchmark(evaluate_all)
        assert isinstance(results, list)
        assert len(results) == 100


# ─── BENCH-03: 指标评估器 ───────────────────────────────────────────


class TestIndicatorEvaluatorBenchmark:
    """IndicatorEvaluator 性能基准"""

    def test_extract_indicators_100x(self, benchmark, sample_tech_data):
        """指标数据提取 100 次"""

        def extract_100():
            for _ in range(100):
                extract_indicators_from_tech_data(sample_tech_data)

        benchmark(extract_100)

    def test_evaluator_100_tickers(self, benchmark, indicator_rules):
        """IndicatorEvaluator 100 个 ticker 评估"""
        evaluator = IndicatorEvaluator(throttle_minutes=0)
        indicators = {
            "rsi": 55.3,
            "macd_line": 0.45,
            "signal_line": 0.32,
            "ma_10": 152.3,
            "ma_20": 148.7,
        }

        def evaluate_100():
            for i in range(100):
                ticker = f"TICK{i}"
                evaluator.update_indicators(ticker, indicators)
                evaluator.evaluate_rules(ticker, indicator_rules[:10], indicators)

        benchmark(evaluate_100)


# ─── BENCH-04: K线序列化 ────────────────────────────────────────────


class TestKlineSerializationBenchmark:
    """K线数据序列化性能基准"""

    def test_kline_to_json_1000bars(self, benchmark, sample_kline_df):
        """1000 条 K 线 → JSON 序列化"""
        import json

        records = sample_kline_df.reset_index().to_dict(orient="records")
        # 扩展到 1000 条 + 转换 Timestamp 为字符串
        records = records * 4
        for r in records:
            if "index" in r and hasattr(r["index"], "isoformat"):
                r["index"] = r["index"].isoformat()

        def serialize():
            return json.dumps(records)

        result = benchmark(serialize)
        assert len(result) > 0

    def test_kline_to_parquet_1000bars(self, benchmark, sample_kline_df, tmp_path):
        """1000 条 K 线 → Parquet 写入"""
        df = pd.concat([sample_kline_df] * 4, ignore_index=True)
        path = str(tmp_path / "bench_kline.parquet")

        def write_parquet():
            df.to_parquet(path, engine="pyarrow")

        benchmark(write_parquet)

    def test_kline_from_parquet_1000bars(self, benchmark, sample_kline_df, tmp_path):
        """1000 条 K 线 ← Parquet 读取"""
        df = pd.concat([sample_kline_df] * 4, ignore_index=True)
        path = str(tmp_path / "bench_kline.parquet")
        df.to_parquet(path, engine="pyarrow")

        def read_parquet():
            return pd.read_parquet(path, engine="pyarrow")

        result = benchmark(read_parquet)
        assert len(result) == 1000
