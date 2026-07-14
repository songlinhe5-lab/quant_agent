"""
RISK-04: 压力测试
历史情景回放 (2008/2020/2022) + 假设情景 (利率/波动率/汇率)
"""

import time
from typing import Any, Dict, List, Optional

import numpy as np

from backend.core.logger import logger

# 历史情景定义: 名称 → (开始日期, 结束日期, 描述, 基准冲击)
HISTORICAL_SCENARIOS = {
    "2008_crash": {
        "start": "2008-09-01",
        "end": "2009-03-01",
        "desc": "2008 全球金融危机",
        "shock": -0.35,  # 组合平均跌幅约 35%
    },
    "2020_covid": {
        "start": "2020-02-01",
        "end": "2020-04-01",
        "desc": "2020 新冠疫情冲击",
        "shock": -0.20,
    },
    "2022_hike": {
        "start": "2022-01-01",
        "end": "2022-06-30",
        "desc": "2022 激进加息周期",
        "shock": -0.15,
    },
}

# 假设情景定义
HYPOTHETICAL_SCENARIOS = {
    "rate_plus_1": {
        "desc": "利率上升 1%",
        "sector_impact": {
            "科技": -0.08, "金融": 0.03, "房地产": -0.12,
            "公用事业": -0.06, "医疗": -0.03, "默认": -0.05,
        },
    },
    "vol_double": {
        "desc": "波动率翻倍",
        "multiplier": 2.0,
    },
    "fx_depreciation": {
        "desc": "汇率贬值 5% (HKD/USD)",
        "fx_shock": -0.05,
        "affected_market": "HK",
    },
}


class StressTester:
    """压力测试器"""

    def run_stress(
        self,
        positions: List[Dict],
        kline_data: Dict[str, np.ndarray],
        scenario: str,
        market: str = "HK",
        sector_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        执行压力测试

        Returns:
            {
                scenario: str, desc: str,
                nav_before, nav_after, change_pct, change_amount,
                top_losers: [{symbol, loss_pct}],
                ts: float,
            }
        """
        if not positions:
            return self._empty_result(scenario)

        sector_map = sector_map or {}
        total_nav = sum(float(p.get("market_val", 0)) for p in positions)
        if total_nav <= 0:
            return self._empty_result(scenario)

        # 路由到对应情景
        if scenario in HISTORICAL_SCENARIOS:
            return self._run_historical(positions, kline_data, scenario, total_nav)
        elif scenario in HYPOTHETICAL_SCENARIOS:
            return self._run_hypothetical(positions, kline_data, scenario, total_nav, market, sector_map)
        else:
            return self._empty_result(scenario, f"未知情景: {scenario}")

    def _run_historical(
        self,
        positions: List[Dict],
        kline_data: Dict[str, np.ndarray],
        scenario: str,
        total_nav: float,
    ) -> Dict[str, Any]:
        """历史情景回放"""
        scen = HISTORICAL_SCENARIOS[scenario]
        shock = scen["shock"]

        # 如果有真实 K 线数据，用实际收益率模拟
        # 否则用统一冲击
        position_impacts = []
        for pos in positions:
            code = pos.get("code", "")
            mv = float(pos.get("market_val", 0))
            if code in kline_data and len(kline_data[code]) >= 20:
                # 用最近 60 日波动率 * 历史冲击系数 估算
                closes = np.array(kline_data[code], dtype=float)
                returns = np.diff(np.log(closes))
                vol = float(np.std(returns))
                # 冲击按波动率缩放 (高波动标的跌更多)
                impact = shock * (1 + vol * 10)
            else:
                impact = shock

            loss = mv * impact
            position_impacts.append({
                "symbol": code,
                "market_val": mv,
                "loss": loss,
                "loss_pct": impact * 100,
            })

        total_loss = sum(pi["loss"] for pi in position_impacts)
        nav_after = total_nav + total_loss

        # Top 5 亏损
        position_impacts.sort(key=lambda x: x["loss"])
        top_losers = [
            {"symbol": pi["symbol"], "loss_pct": round(pi["loss_pct"], 2)}
            for pi in position_impacts[:5]
        ]

        return {
            "scenario": scenario,
            "desc": scen["desc"],
            "type": "historical",
            "nav_before": round(total_nav, 2),
            "nav_after": round(nav_after, 2),
            "change_amount": round(total_loss, 2),
            "change_pct": round(total_loss / total_nav * 100, 2),
            "top_losers": top_losers,
            "ts": time.time(),
        }

    def _run_hypothetical(
        self,
        positions: List[Dict],
        kline_data: Dict[str, np.ndarray],
        scenario: str,
        total_nav: float,
        market: str,
        sector_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """假设情景"""
        scen = HYPOTHETICAL_SCENARIOS[scenario]
        position_impacts = []

        for pos in positions:
            code = pos.get("code", "")
            mv = float(pos.get("market_val", 0))

            if scenario == "rate_plus_1":
                sector = sector_map.get(code, "默认")
                impact = scen["sector_impact"].get(sector, scen["sector_impact"]["默认"])

            elif scenario == "vol_double":
                if code in kline_data and len(kline_data[code]) >= 10:
                    closes = np.array(kline_data[code], dtype=float)
                    returns = np.diff(np.log(closes))
                    vol = float(np.std(returns))
                    # 波动率翻倍 → 预期亏损 = vol * multiplier
                    impact = -vol * scen["multiplier"] * 5  # 5 日冲击
                else:
                    impact = -0.05  # 默认 5% 冲击

            elif scenario == "fx_depreciation":
                if market == scen.get("affected_market", ""):
                    impact = scen["fx_shock"]
                else:
                    impact = 0.0  # 非受影响市场
            else:
                impact = 0.0

            loss = mv * impact
            position_impacts.append({
                "symbol": code,
                "market_val": mv,
                "loss": loss,
                "loss_pct": impact * 100,
            })

        total_loss = sum(pi["loss"] for pi in position_impacts)
        nav_after = total_nav + total_loss

        position_impacts.sort(key=lambda x: x["loss"])
        top_losers = [
            {"symbol": pi["symbol"], "loss_pct": round(pi["loss_pct"], 2)}
            for pi in position_impacts[:5]
        ]

        return {
            "scenario": scenario,
            "desc": scen["desc"],
            "type": "hypothetical",
            "nav_before": round(total_nav, 2),
            "nav_after": round(nav_after, 2),
            "change_amount": round(total_loss, 2),
            "change_pct": round(total_loss / total_nav * 100, 2) if total_nav > 0 else 0,
            "top_losers": top_losers,
            "ts": time.time(),
        }

    def _empty_result(self, scenario: str, desc: str = "") -> Dict[str, Any]:
        return {
            "scenario": scenario,
            "desc": desc or "无持仓",
            "type": "unknown" if desc else "empty",
            "nav_before": 0,
            "nav_after": 0,
            "change_amount": 0,
            "change_pct": 0,
            "top_losers": [],
            "ts": time.time(),
        }

    @staticmethod
    def list_scenarios() -> Dict[str, Any]:
        """列出所有可用情景"""
        return {
            "historical": [
                {"id": k, "desc": v["desc"], "start": v["start"], "end": v["end"]}
                for k, v in HISTORICAL_SCENARIOS.items()
            ],
            "hypothetical": [
                {"id": k, "desc": v["desc"]}
                for k, v in HYPOTHETICAL_SCENARIOS.items()
            ],
        }


stress_tester = StressTester()
