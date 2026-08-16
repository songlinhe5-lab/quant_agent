"""
期权领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「期权」语义的封装：get_option_chain /
get_warrant_chain。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class OptionDataService:
    """期权领域业务适配器。"""

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权链 + OCC 合约代码。"""
        self._validate_ticker(ticker)
        return await self._facade.get_option_chain(
            ticker, expiration_date=expiration_date, prefer_sources=prefer_sources
        )

    async def get_warrant_chain(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """窝轮链（Futu 专属能力）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_warrant_chain(ticker, prefer_sources=prefer_sources)

    # ── F3: 期权策略 + 期权波动率（G4 支撑）─────────────────────────────
    async def get_option_strategy(
        self,
        ticker: str,
        strategy_type: str = "STRANGLE",
        spread: int = 5,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权策略组合（入参必须为正股/ETF/指数，非期权 code）。"""
        self._validate_ticker(ticker)
        return await self._facade._dispatch(
            "OPTION_STRATEGY",
            {"ticker": ticker, "strategy_type": strategy_type, "spread": spread},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )

    async def get_option_volatility(
        self,
        ticker: str,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权波动率（入参必须为期权合约代码，非正股）。"""
        self._validate_ticker(ticker)
        return await self._facade._dispatch(
            "OPTION_VOLATILITY",
            {"ticker": ticker},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )

    # ── G4: 期权损益实验室（产品级聚合，依赖 F3 OPTION_STRATEGY）──────────
    async def get_option_strategy_lab(
        self,
        ticker: str,
        strategy_type: str = "STRANGLE",
        spread: int = 5,
        underlying_price: Optional[float] = None,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """G4：期权损益实验室。

        拉取 F3 真实期权策略组合（OPTION_STRATEGY），对真实组合腿做**纯代数**
        损益曲线推演（到期损益 = Σ每腿内在价值 − 真实权利金），再派生盈亏平衡点 /
        最大盈亏 / 真实 Greeks 敞口。

        ⚠️ 红线：损益必须来自真实组合腿的代数推演，严禁用 Black-Scholes 近似凑数。
        若组合数据缺失权利金或行权价，则对应字段给 None + note，绝不臆造。
        """
        self._validate_ticker(ticker)
        res = await self._facade._dispatch(
            "OPTION_STRATEGY",
            {"ticker": ticker, "strategy_type": strategy_type, "spread": spread},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )
        if res.is_error:
            return res

        data = res.data
        if not isinstance(data, dict):
            return res

        legs_raw = data.get("data") or []
        if not isinstance(legs_raw, list) or len(legs_raw) == 0:
            data["lab"] = {"available": False, "note": "期权策略组合为空，无法构建损益实验室"}
            return res

        # ── 防御式解析真实组合腿（不硬编码 Futu 列名）──
        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _detect(keys, *hints):
            for h in hints:
                for k in keys:
                    if h in str(k).lower():
                        return k
            return None

        keys = list(legs_raw[0].keys())
        strike_col = _detect(keys, "strike", "行权")
        type_col = _detect(keys, "option_type", "type", "call_or_put", "方向")
        prem_col = _detect(keys, "premium", "price", "last", "权利金", "cost")
        side_col = _detect(keys, "position", "side", "买卖", "方向")
        greeks = {g: _detect(keys, g) for g in ("delta", "gamma", "vega", "theta")}

        legs = []
        for r in legs_raw:
            strike = _f(r.get(strike_col)) if strike_col else None
            otype = str(r.get(type_col) or r.get("option_type") or "").upper()
            prem = _f(r.get(prem_col)) if prem_col else None
            # 持仓方向：默认多头（买入腿，支付权利金）；若数据显式标注则尊重
            side = str(r.get(side_col) or "BUY").upper()
            sign = -1.0 if ("SELL" in side or "SHORT" in side or side == "2" or side == "-1") else 1.0
            leg = {
                "strike": strike,
                "option_type": "CALL"
                if "C" in otype or "CALL" in otype
                else ("PUT" if "P" in otype or "PUT" in otype else None),
                "premium": prem,
                "side": "BUY" if sign > 0 else "SELL",
                "greeks": {g: _f(r.get(c)) if c else None for g, c in greeks.items()},
                "raw": r,
            }
            legs.append(leg)

        # 校验：必须能解析出行权价与权利金，否则无法构建损益曲线（红线：不臆造）
        valid_legs = [
            leg
            for leg in legs
            if leg["strike"] is not None and leg["premium"] is not None and leg["option_type"] in ("CALL", "PUT")
        ]
        if len(valid_legs) == 0:
            data["lab"] = {
                "available": False,
                "note": "组合腿缺少可解析的行权价/权利金/类型字段，无法构建损益曲线",
                "detected_columns": {"strike": strike_col, "type": type_col, "premium": prem_col},
            }
            return res

        # ── 构建情景网格（基于真实行权价区间，不再外推定价）──
        strikes = [leg["strike"] for leg in valid_legs]
        lo, hi = min(strikes), max(strikes)
        span = (hi - lo) or (lo * 0.1 if lo else 10.0)
        center = underlying_price if underlying_price else (lo + hi) / 2
        grid_lo = center - span * 1.5
        grid_hi = center + span * 1.5
        steps = 60
        grid = [round(grid_lo + (grid_hi - grid_lo) * i / steps, 4) for i in range(steps + 1)]

        def _intrinsic(otype, S, K):
            if otype == "CALL":
                return max(S - K, 0.0)
            return max(K - S, 0.0)

        def _pnl_at(S):
            total = 0.0
            for leg in valid_legs:
                intrinsic = _intrinsic(leg["option_type"], S, leg["strike"])
                if leg["side"] == "BUY":
                    # 买入腿：期初付权利金，到期内在价值 − 权利金
                    total += intrinsic - leg["premium"]
                else:
                    # 卖出腿：期初收权利金，到期义务 = 权利金 − 内在价值
                    total += leg["premium"] - intrinsic
            return round(total, 4)

        curve = [{"underlying": S, "pnl": _pnl_at(S)} for S in grid]

        # 盈亏平衡点（pnl 由负转正/由正转负的穿越点）
        break_evens = []
        for i in range(1, len(curve)):
            a, b = curve[i - 1], curve[i]
            if a["pnl"] == 0 or (a["pnl"] < 0 < b["pnl"]) or (a["pnl"] > 0 > b["pnl"]):
                be = a["underlying"] if a["pnl"] == 0 else round((a["underlying"] + b["underlying"]) / 2, 4)
                break_evens.append(be)

        pnls = [c["pnl"] for c in curve]
        max_profit = round(max(pnls), 4)
        max_loss = round(min(pnls), 4)

        # 真实 Greeks 敞口（各腿求和；缺失字段跳过而非补零）
        gex = {}
        for g in ("delta", "gamma", "vega", "theta"):
            vals = [leg["greeks"].get(g) for leg in valid_legs if leg["greeks"].get(g) is not None]
            gex[g] = round(sum(vals), 6) if vals else None

        data["lab"] = {
            "available": True,
            "strategy_type": data.get("strategy_type"),
            "underlying_price": underlying_price,
            "legs": [{k: v for k, v in leg.items() if k != "raw"} for leg in valid_legs],
            "payoff_curve": curve,
            "break_even": break_evens,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "greeks_exposure": gex,
            "notes": [
                "损益曲线为到期日纯代数推演（基于真实组合腿行权价/权利金），非定价近似",
                "Greeks 敞口为各腿真实值求和，缺失字段不补零",
            ],
        }
        return res

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")


# 领域单例
option_data_service = OptionDataService()
