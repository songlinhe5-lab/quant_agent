"""
TRADE-02 · 算法执行分析

执行质量评估:
- 滑点计算 (实际成交 vs 基准)
- VWAP 偏离度
- 市场参与率
- 执行报告生成
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlgoAnalytics:
    """算法拆单执行分析"""

    @staticmethod
    def compute_slippage(
        actual_avg_price: float,
        benchmark_price: float,
        side: str,
    ) -> float:
        """
        计算执行滑点 (basis points)。

        Args:
            actual_avg_price: 实际成交均价
            benchmark_price: 基准价格 (决策时刻价格 / VWAP)
            side: "BUY" 或 "SELL"

        Returns:
            滑点 (bps), 正数表示有利执行, 负数表示不利执行
        """
        if actual_avg_price <= 0 or benchmark_price <= 0:
            return 0.0

        if side.upper() == "BUY":
            # 买入: 实际价格低于基准 = 有利
            slippage = (benchmark_price - actual_avg_price) / benchmark_price * 10000
        else:
            # 卖出: 实际价格高于基准 = 有利
            slippage = (actual_avg_price - benchmark_price) / benchmark_price * 10000

        return round(slippage, 2)

    @staticmethod
    def vwap_deviation(actual_vwap: float, market_vwap: float) -> float:
        """
        计算 VWAP 偏离度 (bps)。

        Args:
            actual_vwap: 算法实际成交 VWAP
            market_vwap: 市场 VWAP (基准)

        Returns:
            偏离度 (bps), 正数表示优于市场 VWAP
        """
        if actual_vwap <= 0 or market_vwap <= 0:
            return 0.0

        return round((market_vwap - actual_vwap) / market_vwap * 10000, 2)

    @staticmethod
    def participation_rate(filled_qty: int, market_volume: int) -> float:
        """
        计算市场参与率。

        Args:
            filled_qty: 算法已成交量
            market_volume: 同期市场总成交量

        Returns:
            参与率 (0-1)
        """
        if market_volume <= 0:
            return 0.0

        return round(filled_qty / market_volume, 4)

    @staticmethod
    def implementation_shortfall(
        actual_cost: float,
        paper_cost: float,
        side: str,
    ) -> float:
        """
        计算 Implementation Shortfall (执行缺口)。

        Args:
            actual_cost: 实际执行成本 (总成交金额)
            paper_cost: 纸面组合成本 (决策时刻价格 × 目标数量)
            side: "BUY" 或 "SELL"

        Returns:
            Implementation Shortfall (bps)
        """
        if paper_cost <= 0:
            return 0.0

        if side.upper() == "BUY":
            # 买入: 实际成本 - 纸面成本
            is_bps = (actual_cost - paper_cost) / paper_cost * 10000
        else:
            # 卖出: 纸面收入 - 实际收入
            is_bps = (paper_cost - actual_cost) / paper_cost * 10000

        return round(is_bps, 2)

    @staticmethod
    def time_distribution(
        fills: List[Dict[str, Any]],
        total_duration_minutes: int,
    ) -> List[Dict[str, Any]]:
        """
        计算成交的时间分布 (按 5 分钟桶聚合)。

        Args:
            fills: 成交记录列表 [{timestamp, qty, price}, ...]
            total_duration_minutes: 算法总执行时长

        Returns:
            时间分布 [{bucket, qty, avg_price, pct_of_total}, ...]
        """
        if not fills:
            return []

        # 按 5 分钟桶聚合
        bucket_size = 5  # 分钟
        n_buckets = max(1, total_duration_minutes // bucket_size + 1)

        buckets: Dict[int, Dict[str, Any]] = {}
        total_qty = 0

        for fill in fills:
            ts = fill.get("timestamp", 0)
            bucket_idx = min(int(ts // (bucket_size * 60)), n_buckets - 1)

            if bucket_idx not in buckets:
                buckets[bucket_idx] = {"qty": 0, "cost": 0.0}

            qty = fill.get("qty", 0)
            price = fill.get("price", 0)
            buckets[bucket_idx]["qty"] += qty
            buckets[bucket_idx]["cost"] += qty * price
            total_qty += qty

        result = []
        for i in range(n_buckets):
            data = buckets.get(i, {"qty": 0, "cost": 0.0})
            qty = data["qty"]
            avg_price = data["cost"] / qty if qty > 0 else 0
            pct = qty / total_qty if total_qty > 0 else 0

            result.append(
                {
                    "bucket": i,
                    "time_range": f"{i * bucket_size}-{(i + 1) * bucket_size}min",
                    "qty": qty,
                    "avg_price": round(avg_price, 2),
                    "pct_of_total": round(pct * 100, 2),
                }
            )

        return result

    @classmethod
    def execution_report(
        cls,
        algo_id: str,
        algo_type: str,
        symbol: str,
        side: str,
        target_qty: int,
        filled_qty: int,
        total_cost: float,
        benchmark_price: float,
        market_volume: int = 0,
        market_vwap: float = 0,
        fills: Optional[List[Dict[str, Any]]] = None,
        duration_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        生成完整的执行分析报告。

        Args:
            algo_id: 算法 ID
            algo_type: 算法类型 (TWAP/VWAP/POV/IS)
            symbol: 标的代码
            side: 方向
            target_qty: 目标数量
            filled_qty: 已成交数量
            total_cost: 总成交金额
            benchmark_price: 基准价格
            market_volume: 同期市场成交量
            market_vwap: 市场 VWAP
            fills: 成交记录列表
            duration_minutes: 执行时长

        Returns:
            执行分析报告
        """
        actual_avg = total_cost / filled_qty if filled_qty > 0 else 0

        # 滑点
        slippage_bps = cls.compute_slippage(actual_avg, benchmark_price, side)

        # VWAP 偏离
        vwap_dev = cls.vwap_deviation(actual_avg, market_vwap) if market_vwap > 0 else 0

        # 参与率
        participation = cls.participation_rate(filled_qty, market_volume)

        # Implementation Shortfall
        paper_cost = benchmark_price * target_qty
        is_bps = cls.implementation_shortfall(total_cost, paper_cost, side)

        # 时间分布
        time_dist = cls.time_distribution(fills or [], duration_minutes)

        # 执行效率
        completion_pct = (filled_qty / target_qty * 100) if target_qty > 0 else 0

        return {
            "algo_id": algo_id,
            "algo_type": algo_type,
            "symbol": symbol,
            "side": side,
            "summary": {
                "target_qty": target_qty,
                "filled_qty": filled_qty,
                "completion_pct": round(completion_pct, 2),
                "actual_avg_price": round(actual_avg, 2),
                "benchmark_price": round(benchmark_price, 2),
                "total_cost": round(total_cost, 2),
            },
            "quality_metrics": {
                "slippage_bps": slippage_bps,
                "vwap_deviation_bps": vwap_dev,
                "implementation_shortfall_bps": is_bps,
                "participation_rate": round(participation * 100, 2),
            },
            "time_distribution": time_dist,
            "assessment": cls._assess_execution(slippage_bps, vwap_dev, participation),
        }

    @staticmethod
    def _assess_execution(
        slippage_bps: float,
        vwap_dev: float,
        participation: float,
    ) -> str:
        """评估执行质量"""
        if slippage_bps > 5:
            return "EXCELLENT"  # 执行非常有利
        elif slippage_bps > 0:
            return "GOOD"  # 执行略优于基准
        elif slippage_bps > -5:
            return "ACCEPTABLE"  # 轻微不利
        else:
            return "POOR"  # 执行质量差


# 全局单例
algo_analytics = AlgoAnalytics()
