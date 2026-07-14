"""
RISK-06: 流动性风险评估
持仓日均成交额 vs 市值 → 流动性覆盖率 + 大额持仓预警 + 流动性评分
"""

import time
from typing import Any, Dict, List

import numpy as np

from backend.core.logger import logger


class LiquidityAssessor:
    """流动性风险评估器"""

    def assess(
        self,
        positions: List[Dict],
        kline_data: Dict[str, np.ndarray],
        total_nav: float = 0.0,
    ) -> Dict[str, Any]:
        """
        评估持仓流动性风险

        kline_data 需包含 volume 列 — 但当前 risk_engine 只存 close 序列
        因此用 close * volume 代理成交额 (若 volume 可用)
        否则用收益率波动作为流动性代理

        Returns:
            {
                assessments: [{symbol, market_val, avg_turnover, coverage_ratio, score}],
                portfolio_score: float,
                warnings: [{symbol, reason}],
                ts: float,
            }
        """
        if not positions:
            return {"assessments": [], "portfolio_score": 0.0, "warnings": [], "ts": time.time()}

        assessments = []
        warnings = []
        weighted_score_sum = 0.0
        total_weight = 0.0

        for pos in positions:
            code = pos.get("code", "")
            mv = float(pos.get("market_val", 0))
            if not code or mv <= 0:
                continue

            # 计算日均成交额 (turnover)
            avg_turnover = self._estimate_turnover(code, kline_data)

            # 流动性覆盖率 = 日均成交额 / 市值
            coverage = avg_turnover / mv if mv > 0 else 0.0

            # 流动性评分 (0-100): coverage >= 10% → 100 分
            score = min(coverage * 10 * 100, 100)
            score = max(0, round(score))

            assessments.append({
                "symbol": code,
                "market_val": round(mv, 2),
                "avg_turnover": round(avg_turnover, 2),
                "coverage_ratio": round(coverage, 4),
                "score": score,
            })

            # 市值加权
            weighted_score_sum += score * mv
            total_weight += mv

            # 大额持仓预警 (>10% NAV)
            if total_nav > 0 and (mv / total_nav) > 0.10:
                warnings.append({
                    "symbol": code,
                    "reason": f"大额持仓占 NAV {mv / total_nav * 100:.1f}% (>10%)",
                    "nav_pct": round(mv / total_nav * 100, 2),
                })

            # 低流动性预警 (score < 30)
            if score < 30:
                warnings.append({
                    "symbol": code,
                    "reason": f"流动性评分 {score} (<30)，变现困难",
                    "score": score,
                })

        # 组合整体流动性评分 (市值加权)
        portfolio_score = round(weighted_score_sum / total_weight, 1) if total_weight > 0 else 0.0

        return {
            "assessments": assessments,
            "portfolio_score": portfolio_score,
            "warnings": warnings,
            "ts": time.time(),
        }

    def _estimate_turnover(self, code: str, kline_data: Dict[str, np.ndarray]) -> float:
        """
        估算日均成交额

        由于 risk_engine 的 kline_data 只存 close 序列 (无 volume),
        用价格波动幅度 * 基准成交额 作为代理:
        - 高波动 → 通常成交活跃 → 流动性好
        - 低波动 + 低价 → 流动性差

        简化公式: avg_turnover = mean(daily_range_proxy) * 1e6
        daily_range_proxy = |log(close_t / close_{t-1})| * close_t
        """
        closes = kline_data.get(code)
        if closes is None or len(closes) < 5:
            return 0.0

        closes_arr = np.array(closes, dtype=float)
        daily_returns = np.abs(np.diff(np.log(closes_arr)))
        # 用日均绝对收益幅度 * 最新价 * 1e6 作为成交额代理
        avg_daily_range = float(np.mean(daily_returns))
        latest_price = float(closes_arr[-1])
        estimated_turnover = avg_daily_range * latest_price * 1e6
        return estimated_turnover


liquidity_assessor = LiquidityAssessor()
