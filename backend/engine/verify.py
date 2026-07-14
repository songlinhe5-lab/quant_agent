"""
BT-01c · 同构校验器（Isomorphism Verifier）

验证事件驱动与矢量化两条路径的结果一致性。
这是防止「网格搜索选出的参数在事件语义下失效」的唯一防线。

设计文档：docs/15. 回测实盘同构引擎设计.md §四.2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from backend.engine.drivers.backtest import BacktestConfig, BacktestDriver, BacktestResult
from backend.engine.drivers.vector import VectorConfig, VectorExecutor, VectorResult
from backend.engine.strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass
class DivergencePoint:
    """分歧点信息"""

    bar_index: int
    bar_date: str
    event_price: float
    vector_price: float
    event_position: int
    vector_position: int
    reason: str


@dataclass
class IsomorphismReport:
    """同构校验报告"""

    is_consistent: bool
    max_return_diff_pct: float  # 最大收益差异百分比
    max_drawdown_diff_pct: float  # 最大回撤差异百分比
    trade_count_diff: int  # 交易数量差异
    divergence_points: List[DivergencePoint]  # 分歧点列表
    event_metrics: Dict[str, Any]
    vector_metrics: Dict[str, Any]

    def summary(self) -> str:
        """生成摘要"""
        if self.is_consistent:
            return f"✅ 同构校验通过：收益差异 {self.max_return_diff_pct:.4f}%, 回撤差异 {self.max_drawdown_diff_pct:.4f}%"
        else:
            reasons = [d.reason for d in self.divergence_points[:3]]
            return f"❌ 同构校验失败：{', '.join(reasons)}"


class IsomorphismVerifier:
    """同构校验器

    对同一策略分别运行事件驱动和矢量化路径，比较结果一致性。
    """

    # 容差阈值
    RETURN_TOLERANCE_PCT = 0.01  # 收益差异容差 0.01%
    DRAWDOWN_TOLERANCE_PCT = 0.01  # 回撤差异容差 0.01%
    TRADE_COUNT_TOLERANCE = 0  # 交易数量必须完全一致

    def __init__(
        self,
        backtest_config: Optional[BacktestConfig] = None,
        vector_config: Optional[VectorConfig] = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfig()
        self.vector_config = vector_config or VectorConfig(
            initial_capital=self.backtest_config.initial_capital,
            commission_pct=self.backtest_config.commission_pct,
            slippage_pct=self.backtest_config.slippage_pct,
        )

    def verify(
        self,
        strategy_cls: Type[Strategy],
        params: Dict[str, Any],
        df: pd.DataFrame,
        symbol: str,
        source_code: Optional[str] = None,
    ) -> IsomorphismReport:
        """执行同构校验

        Args:
            strategy_cls: 策略类
            params: 策略参数
            df: K 线数据
            symbol: 标的代码
            source_code: 策略源码

        Returns:
            IsomorphismReport
        """
        # 检查策略是否支持矢量化
        if not strategy_cls.is_vectorizable():
            return IsomorphismReport(
                is_consistent=False,
                max_return_diff_pct=float("inf"),
                max_drawdown_diff_pct=float("inf"),
                trade_count_diff=-1,
                divergence_points=[],
                event_metrics={},
                vector_metrics={},
            )

        # 运行事件驱动路径
        event_driver = BacktestDriver(self.backtest_config)
        event_result = event_driver.run(
            strategy_cls=strategy_cls,
            params=params,
            df=df,
            symbol=symbol,
            source_code=source_code,
        )

        # 运行矢量化路径
        vector_executor = VectorExecutor(self.vector_config)
        try:
            vector_result = vector_executor.run(
                strategy_cls=strategy_cls,
                params=params,
                df=df,
            )
        except ValueError as e:
            logger.error(f"Vector execution failed: {e}")
            return IsomorphismReport(
                is_consistent=False,
                max_return_diff_pct=float("inf"),
                max_drawdown_diff_pct=float("inf"),
                trade_count_diff=-1,
                divergence_points=[DivergencePoint(
                    bar_index=0,
                    bar_date="N/A",
                    event_price=0,
                    vector_price=0,
                    event_position=0,
                    vector_position=0,
                    reason=f"Vector execution failed: {e}",
                )],
                event_metrics=event_result.metrics,
                vector_metrics={},
            )

        # 比较结果
        return self._compare_results(event_result, vector_result)

    def _compare_results(
        self,
        event: BacktestResult,
        vector: VectorResult,
    ) -> IsomorphismReport:
        """比较两条路径的结果"""
        divergence_points: List[DivergencePoint] = []

        # 解析指标
        event_return = self._parse_pct(event.metrics.get("total_return", "0%"))
        vector_return = self._parse_pct(vector.metrics.get("total_return", "0%"))
        return_diff = abs(event_return - vector_return)

        event_dd = abs(self._parse_pct(event.metrics.get("max_drawdown", "0%")))
        vector_dd = abs(self._parse_pct(vector.metrics.get("max_drawdown", "0%")))
        dd_diff = abs(event_dd - vector_dd)

        # 比较交易数量
        event_trades = len([t for t in event.trades if t.get("action") in ("BUY", "SELL")])
        vector_trades = len(vector.trades)
        trade_diff = abs(event_trades - vector_trades)

        # 检查一致性
        is_consistent = (
            return_diff <= self.RETURN_TOLERANCE_PCT
            and dd_diff <= self.DRAWDOWN_TOLERANCE_PCT
            and trade_diff <= self.TRADE_COUNT_TOLERANCE
        )

        # 如果不一致，尝试找到分歧点
        if not is_consistent:
            divergence_points = self._find_divergence_points(event, vector)

        return IsomorphismReport(
            is_consistent=is_consistent,
            max_return_diff_pct=return_diff,
            max_drawdown_diff_pct=dd_diff,
            trade_count_diff=trade_diff,
            divergence_points=divergence_points,
            event_metrics=event.metrics,
            vector_metrics=vector.metrics,
        )

    def _find_divergence_points(
        self,
        event: BacktestResult,
        vector: VectorResult,
    ) -> List[DivergencePoint]:
        """尝试找到分歧点"""
        points = []

        # 比较权益曲线
        event_equity = {e["date"]: e["equity"] for e in event.equity_curve}
        vector_equity = {e["date"]: e["equity"] for e in vector.equity_curve}

        common_dates = set(event_equity.keys()) & set(vector_equity.keys())
        for i, date in enumerate(sorted(common_dates)):
            eq_diff = abs(event_equity[date] - vector_equity[date])
            if eq_diff > 1.0:  # 差异超过 1 元
                points.append(DivergencePoint(
                    bar_index=i,
                    bar_date=date,
                    event_price=event_equity[date],
                    vector_price=vector_equity[date],
                    event_position=0,  # 简化
                    vector_position=0,
                    reason=f"Equity divergenceence at {date}: {eq_diff:.2f}",
                ))
                if len(points) >= 5:  # 最多记录 5 个分歧点
                    break

        return points

    @staticmethod
    def _parse_pct(s: str) -> float:
        """解析百分比字符串"""
        if not s:
            return 0.0
        s = s.strip().rstrip("%")
        try:
            return float(s)
        except ValueError:
            return 0.0
