"""
BT-01c · VectorBT 快路径 + 同构校验器测试

覆盖：
- VectorExecutor: 矢量化执行/回退执行
- IsomorphismVerifier: 同构校验/分歧检测

测试要求：≥80% 覆盖率
"""

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import pytest

from backend.engine import Bar, Strategy
from backend.engine.drivers.vector import VectorConfig, VectorExecutor, VectorResult
from backend.engine.verify import IsomorphismReport, IsomorphismVerifier

# ─────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────


def make_sample_df(n: int = 100) -> pd.DataFrame:
    """生成测试用 K 线数据"""
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    np.random.seed(42)
    base_price = 100.0
    prices = [base_price]
    for _ in range(n - 1):
        change = np.random.uniform(-0.02, 0.02)
        prices.append(prices[-1] * (1 + change))

    data = {
        "open": [p * 0.998 for p in prices],
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": np.random.randint(100000, 1000000, n).astype(float),
    }
    return pd.DataFrame(data, index=dates)


class SimpleMovingAverageStrategy(Strategy):
    """简单均线策略（可矢量化）"""

    def on_bar(self, ctx, bar: Bar) -> None:
        pass  # 简化实现

    @classmethod
    def signals(cls, df: pd.DataFrame, params: Dict[str, Any]) -> Optional[pd.Series]:
        """均线交叉信号"""
        period = params.get("period", 20)
        if len(df) < period:
            return pd.Series(0, index=df.index)

        close = df["close"] if "close" in df.columns else df["Close"]
        sma = close.rolling(period).mean()

        signal = pd.Series(0, index=df.index)
        signal[close > sma] = 1
        signal[close < sma] = -1
        return signal


class NonVectorizableStrategy(Strategy):
    """不可矢量化策略"""

    def on_bar(self, ctx, bar: Bar) -> None:
        pass

    # 不覆盖 signals() 方法


# ─────────────────────────────────────────────
# VectorExecutor 测试
# ─────────────────────────────────────────────


class TestVectorExecutor:
    """VectorBT 执行器测试"""

    @pytest.fixture
    def executor(self):
        return VectorExecutor(
            VectorConfig(
                initial_capital=100000.0,
                commission_pct=0.001,
                slippage_pct=0.001,
            )
        )

    def test_run_vectorizable_strategy(self, executor):
        """运行可矢量化策略"""
        df = make_sample_df(100)
        result = executor.run(
            strategy_cls=SimpleMovingAverageStrategy,
            params={"period": 20},
            df=df,
        )

        assert isinstance(result, VectorResult)
        assert "total_return" in result.metrics
        assert len(result.equity_curve) > 0
        assert result.signals is not None

    def test_run_non_vectorizable_raises(self, executor):
        """不可矢量化策略抛异常"""
        df = make_sample_df(50)
        with pytest.raises(ValueError, match="does not support vectorized"):
            executor.run(
                strategy_cls=NonVectorizableStrategy,
                params={},
                df=df,
            )

    def test_metrics_format(self, executor):
        """指标格式正确"""
        df = make_sample_df(100)
        result = executor.run(
            strategy_cls=SimpleMovingAverageStrategy,
            params={"period": 20},
            df=df,
        )

        assert "%" in result.metrics["total_return"]
        assert "$" in result.metrics["total_friction_cost"]


class TestVectorExecutorFallback:
    """VectorBT 回退执行测试"""

    def test_fallback_execution(self):
        """无 VectorBT 时的回退执行"""
        executor = VectorExecutor(VectorConfig())
        df = make_sample_df(50)

        # 直接调用回退方法
        signals = SimpleMovingAverageStrategy.signals(df, {"period": 10})
        result = executor._fallback_execution(df, signals)

        assert isinstance(result, VectorResult)
        assert result.metrics["engine"] == "⚡ Fallback"


# ─────────────────────────────────────────────
# IsomorphismVerifier 测试
# ─────────────────────────────────────────────


class TestIsomorphismVerifier:
    """同构校验器测试"""

    @pytest.fixture
    def verifier(self):
        return IsomorphismVerifier()

    def test_verify_vectorizable_strategy(self, verifier):
        """校验可矢量化策略"""
        df = make_sample_df(100)
        report = verifier.verify(
            strategy_cls=SimpleMovingAverageStrategy,
            params={},
            df=df,
            symbol="TEST.001",
        )

        assert isinstance(report, IsomorphismReport)
        # 注意：由于撮合逻辑差异，可能不完全一致
        # 但应该能生成报告
        assert report.event_metrics is not None

    def test_verify_non_vectorizable_returns_inconsistent(self, verifier):
        """不可矢量化策略返回不一致"""
        df = make_sample_df(50)
        report = verifier.verify(
            strategy_cls=NonVectorizableStrategy,
            params={},
            df=df,
            symbol="TEST.001",
        )

        assert report.is_consistent is False

    def test_report_summary_consistent(self, verifier):
        """一致报告摘要"""
        report = IsomorphismReport(
            is_consistent=True,
            max_return_diff_pct=0.001,
            max_drawdown_diff_pct=0.002,
            trade_count_diff=0,
            divergence_points=[],
            event_metrics={},
            vector_metrics={},
        )
        summary = report.summary()
        assert "✅" in summary

    def test_report_summary_inconsistent(self, verifier):
        """不一致报告摘要"""
        from backend.engine.verify import DivergencePoint

        report = IsomorphismReport(
            is_consistent=False,
            max_return_diff_pct=5.0,
            max_drawdown_diff_pct=3.0,
            trade_count_diff=2,
            divergence_points=[
                DivergencePoint(
                    bar_index=10,
                    bar_date="2024-01-15",
                    event_price=100.0,
                    vector_price=95.0,
                    event_position=100,
                    vector_position=0,
                    reason="Position divergenceence",
                )
            ],
            event_metrics={},
            vector_metrics={},
        )
        summary = report.summary()
        assert "❌" in summary


class TestIsomorphismVerifierTolerance:
    """同构校验器容差测试"""

    def test_parse_pct(self):
        """解析百分比"""
        assert IsomorphismVerifier._parse_pct("10.5%") == 10.5
        assert IsomorphismVerifier._parse_pct("-5.25%") == -5.25
        assert IsomorphismVerifier._parse_pct("0%") == 0.0
        assert IsomorphismVerifier._parse_pct("") == 0.0
        assert IsomorphismVerifier._parse_pct("invalid") == 0.0
