"""
TRADE-01 · 期权筛选服务

基于期权定价引擎，提供高级筛选功能：
- IV Rank / IV Percentile 筛选
- Greeks 筛选 (Delta/Gamma/Vega)
- 波动率微笑分析
- IV Skew 分析
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.services.options_engine import (
    compute_option_chain_greeks,
    iv_percentile,
    iv_rank,
    vol_smile_analysis,
)

logger = logging.getLogger(__name__)


class OptionFilter(BaseModel):
    """期权筛选条件"""

    ticker: str
    iv_rank_min: Optional[float] = Field(None, ge=0, le=100)
    iv_rank_max: Optional[float] = Field(None, ge=0, le=100)
    delta_min: Optional[float] = Field(None, ge=-1, le=1)
    delta_max: Optional[float] = Field(None, ge=-1, le=1)
    min_volume: Optional[int] = Field(None, ge=0)
    min_open_interest: Optional[int] = Field(None, ge=0)
    moneyness_min: Optional[float] = Field(None, ge=0)
    moneyness_max: Optional[float] = Field(None, ge=0)
    option_type: Optional[str] = Field(None, pattern="^(call|put|both)$")
    expiry: Optional[str] = None


class OptionsScreener:
    """期权筛选器"""

    async def screen_options(
        self,
        ticker: str,
        filters: OptionFilter,
        options_data: List[Dict[str, Any]],
        spot_price: float,
        risk_free_rate: float = 0.05,
        iv_history: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        按条件筛选期权。

        Args:
            ticker: 标的代码
            filters: 筛选条件
            options_data: 期权链原始数据
            spot_price: 标的现价
            risk_free_rate: 无风险利率
            iv_history: 历史 IV 列表 (用于 IV Rank 计算)

        Returns:
            筛选结果
        """
        # 1. 计算所有期权的 Greeks 和 IV
        enriched = compute_option_chain_greeks(spot_price, risk_free_rate, options_data)

        # 2. 应用筛选条件
        results = []
        for opt in enriched:
            # Option type 筛选
            if filters.option_type and filters.option_type != "both":
                if opt["option_type"] != filters.option_type:
                    continue

            # Expiry 筛选
            if filters.expiry and opt["expiry"] != filters.expiry:
                continue

            # IV Rank 筛选 (需要 iv_history)
            if iv_history and opt["iv"] is not None:
                current_iv_pct = opt["iv"]
                rank = iv_rank(current_iv_pct / 100, iv_history)
                pctile = iv_percentile(current_iv_pct / 100, iv_history)
                opt["iv_rank"] = round(rank, 2)
                opt["iv_percentile"] = round(pctile, 2)

                if filters.iv_rank_min is not None and rank < filters.iv_rank_min:
                    continue
                if filters.iv_rank_max is not None and rank > filters.iv_rank_max:
                    continue
            else:
                opt["iv_rank"] = None
                opt["iv_percentile"] = None

            # Delta 筛选
            delta = opt["greeks"]["delta"]
            if filters.delta_min is not None and delta < filters.delta_min:
                continue
            if filters.delta_max is not None and delta > filters.delta_max:
                continue

            # Volume 筛选
            if filters.min_volume is not None and opt["volume"] < filters.min_volume:
                continue

            # Open Interest 筛选
            if filters.min_open_interest is not None and opt["open_interest"] < filters.min_open_interest:
                continue

            # Moneyness 筛选
            moneyness = opt["moneyness"]
            if filters.moneyness_min is not None and moneyness < filters.moneyness_min:
                continue
            if filters.moneyness_max is not None and moneyness > filters.moneyness_max:
                continue

            results.append(opt)

        # 3. 按 IV 排序 (高 IV 优先)
        results.sort(key=lambda x: x.get("iv") or 0, reverse=True)

        return {
            "ticker": ticker,
            "spot_price": spot_price,
            "total_options": len(options_data),
            "matched": len(results),
            "options": results[:50],  # 最多返回 50 条
        }

    async def get_iv_rank_analysis(
        self,
        ticker: str,
        current_iv: float,
        iv_history: List[float],
    ) -> Dict[str, Any]:
        """
        IV Rank 详细分析。

        Args:
            ticker: 标的代码
            current_iv: 当前 ATM IV
            iv_history: 过去 N 天 IV 历史

        Returns:
            IV Rank 分析报告
        """
        rank = iv_rank(current_iv, iv_history)
        pctile = iv_percentile(current_iv, iv_history)

        # 历史统计
        if iv_history:
            avg_iv = sum(iv_history) / len(iv_history)
            min_iv = min(iv_history)
            max_iv = max(iv_history)
            std_iv = (sum((iv - avg_iv) ** 2 for iv in iv_history) / len(iv_history)) ** 0.5
            z_score = (current_iv - avg_iv) / std_iv if std_iv > 0 else 0
        else:
            avg_iv = min_iv = max_iv = std_iv = z_score = 0

        return {
            "ticker": ticker,
            "current_iv": round(current_iv * 100, 2),
            "iv_rank": round(rank, 2),
            "iv_percentile": round(pctile, 2),
            "iv_stats": {
                "avg": round(avg_iv * 100, 2),
                "min": round(min_iv * 100, 2),
                "max": round(max_iv * 100, 2),
                "std": round(std_iv * 100, 2),
                "z_score": round(z_score, 2),
            },
            "history_length": len(iv_history),
            "signal": self._iv_signal(rank, pctile),
        }

    def _iv_signal(self, rank: float, pctile: float) -> str:
        """基于 IV Rank/Percentile 生成交易信号"""
        if rank > 80 and pctile > 80:
            return "HIGH_IV_SELL"  # IV 极高，适合卖方策略
        elif rank < 20 and pctile < 20:
            return "LOW_IV_BUY"  # IV 极低，适合买方策略
        elif rank > 50:
            return "MODERATE_HIGH"
        else:
            return "MODERATE_LOW"

    async def analyze_vol_smile(
        self,
        ticker: str,
        options_data: List[Dict[str, Any]],
        spot_price: float,
        risk_free_rate: float = 0.05,
    ) -> Dict[str, Any]:
        """
        波动率微笑分析。

        Args:
            ticker: 标的代码
            options_data: 期权链数据
            spot_price: 标的现价
            risk_free_rate: 无风险利率

        Returns:
            微笑曲线分析
        """
        # 先计算所有期权的 IV
        enriched = compute_option_chain_greeks(spot_price, risk_free_rate, options_data)

        # 筛选有 IV 的期权
        valid = [o for o in enriched if o.get("iv") is not None and o["iv"] > 0]

        # 转换为 vol_smile_analysis 需要的格式
        smile_data = [
            {
                "strike": o["strike"],
                "option_type": o["option_type"],
                "iv": o["iv"] / 100,  # 转回小数
                "volume": o["volume"],
                "open_interest": o["open_interest"],
            }
            for o in valid
        ]

        result = vol_smile_analysis(smile_data)
        result["ticker"] = ticker
        result["spot_price"] = spot_price
        result["total_analyzed"] = len(valid)

        return result


# 全局单例
options_screener = OptionsScreener()
