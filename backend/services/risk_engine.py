"""
Risk Engine - 组合风控计算引擎
基于真实 Futu 账户数据和 K 线计算风控指标
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import numpy as np
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.core.logger import logger
from backend.core.models import NavSnapshot
from backend.core.redis_client import redis_client
from backend.services.futu_service import futu_service


class RiskEngine:
    """组合风控计算引擎 (单例)"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RiskEngine, cls).__new__(cls)
        return cls._instance

    async def get_portfolio_risk(self, days: int = 1) -> Dict[str, Any]:
        """
        返回分账户独立风控面板数据:
        - accounts: { HK: {...}, US: {...} } 每个账户独立计算所有指标
        - nav_snapshots: 分账户 NAV 快照 (从 DB 读取历史，days 参数控制时间范围)
        """
        # 1. 尝试读取 Redis 缓存 (30s TTL，按 days 区分缓存)
        cache_key = f"quant:risk:portfolio:{days}d"
        cached = await redis_client.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

        # 2. 并发获取 HK + US 两个市场的账户数据
        hk_res, us_res = await asyncio.gather(
            futu_service.get_account_info("HK"),
            futu_service.get_account_info("US"),
            return_exceptions=True,
        )

        # 容错: 处理异常
        if isinstance(hk_res, Exception):
            logger.warning(f"[RiskEngine] HK 账户获取异常: {hk_res}")
            hk_res = {"status": "error", "message": str(hk_res)}
        if isinstance(us_res, Exception):
            logger.warning(f"[RiskEngine] US 账户获取异常: {us_res}")
            us_res = {"status": "error", "message": str(us_res)}

        # 3. 分账户独立计算所有指标
        accounts = {}
        has_any = False

        for market, acc_res in [("HK", hk_res), ("US", us_res)]:
            if not (isinstance(acc_res, dict) and acc_res.get("status") == "success"):
                continue

            has_any = True
            acc_total = float(acc_res.get("total_assets", 0))
            acc_cash = float(acc_res.get("cash", 0))
            acc_market_val = float(acc_res.get("market_val", 0))
            positions = acc_res.get("positions", [])
            currency = acc_res.get("currency", "HKD" if market == "HK" else "USD")

            # 给每个持仓打上市场标签
            for p in positions:
                p["market"] = market

            # 独立计算该账户的 KPI / 敞口 / 风控指标
            kpi = self._calc_kpi(acc_total, acc_cash, acc_market_val, positions, currency)
            exposure = self._calc_exposure(acc_total, acc_cash, acc_market_val, positions)
            risk_metrics = await self._calc_risk_metrics(positions)

            # 分账户 NAV 快照 (从 DB 读取历史数据)
            nav_snapshots = await self._get_nav_snapshots(market, days)
            max_dd = self._calc_max_dd_from_snapshots(nav_snapshots)

            risk_radar = self._build_risk_radar(risk_metrics, max_dd)
            risk_factors = self._build_risk_factors(risk_metrics, max_dd)

            accounts[market] = {
                "kpi": kpi,
                "exposure": exposure,
                "risk_radar": risk_radar,
                "risk_factors": risk_factors,
                "nav_snapshots": nav_snapshots,
                "positions": positions,
                "currency": currency,
                "position_count": len(positions),
            }

        if not has_any:
            return self._fallback_data("HK 和 US 账户均获取失败")

        result = {
            "status": "success",
            "accounts": accounts,
            "ts": time.time(),
        }

        # 写入 Redis 缓存 (30s TTL)
        try:
            await redis_client.set(cache_key, json.dumps(result), ex=30)
        except Exception as e:
            logger.warning(f"[RiskEngine] Redis 缓存写入失败: {e}")

        return result

    def _calc_kpi(
        self, total_assets: float, cash: float, market_val: float, positions: List[Dict],
        currency: str = "HKD",
    ) -> Dict[str, Any]:
        """计算 KPI 指标 (分账户独立)"""
        # 今日 P&L (从持仓盈亏累加)
        today_pl = sum(float(p.get("pl_val", 0)) for p in positions)

        # 杠杆利用率
        leverage = (market_val / total_assets * 100) if total_assets > 0 else 0

        # 货币符号
        sym = "HK$" if currency == "HKD" else "$"

        return {
            "nav": total_assets,
            "nav_fmt": f"{sym}{total_assets:,.2f}",
            "today_pl": today_pl,
            "today_pl_fmt": f"{sym}{'+' if today_pl >= 0 else ''}{today_pl:,.2f}",
            "today_pl_pct": (today_pl / total_assets * 100) if total_assets > 0 else 0,
            "cash": cash,
            "cash_fmt": f"{sym}{cash:,.2f}",
            "leverage": leverage,
            "leverage_fmt": f"{leverage:.1f}%",
            "currency": currency,
        }

    def _calc_exposure(
        self, total_assets: float, cash: float, market_val: float, positions: List[Dict]
    ) -> List[Dict[str, Any]]:
        """计算敞口分布"""
        long_val = sum(float(p.get("market_val", 0)) for p in positions if "LONG" in str(p.get("position_side", "")).upper())
        short_val = sum(float(p.get("market_val", 0)) for p in positions if "SHORT" in str(p.get("position_side", "")).upper())

        long_pct = (long_val / total_assets * 100) if total_assets > 0 else 0
        short_pct = (short_val / total_assets * 100) if total_assets > 0 else 0
        cash_pct = (cash / total_assets * 100) if total_assets > 0 else 0

        return [
            {"name": "多头", "value": long_val, "pct": round(long_pct, 1), "color": "#34d399", "lightColor": "#059669"},
            {"name": "空头", "value": short_val, "pct": round(short_pct, 1), "color": "#f87171", "lightColor": "#dc2626"},
            {"name": "现金", "value": cash, "pct": round(cash_pct, 1), "color": "#f59e0b", "lightColor": "#d97706"},
        ]

    async def _calc_risk_metrics(self, positions: List[Dict]) -> Dict[str, Any]:
        """基于持仓 K 线计算风控指标"""
        if not positions:
            return {"vol": 0, "var_95": 0, "beta": 0, "sharpe": 0}

        # 获取每只持仓的 60 日 K 线
        kline_data = {}
        for pos in positions:
            ticker = pos.get("code", "")
            if not ticker:
                continue
            try:
                hist = await futu_service.get_history(ticker, ktype="K_DAY", num=60)
                if hist.get("status") == "success" and hist.get("data"):
                    closes = [float(k["close"]) for k in hist["data"] if k.get("close")]
                    if len(closes) >= 10:
                        kline_data[ticker] = closes
            except Exception as e:
                logger.warning(f"[RiskEngine] 获取 {ticker} K线失败: {e}")

        if not kline_data:
            return {"vol": 0, "var_95": 0, "beta": 0, "sharpe": 0}

        # 计算每只股票的日收益率
        returns_dict = {}
        for ticker, closes in kline_data.items():
            returns = np.diff(np.log(closes))  # 对数收益率
            returns_dict[ticker] = returns

        # 按市值加权计算组合收益率
        total_market_val = sum(float(p.get("market_val", 0)) for p in positions if p.get("code") in kline_data)
        if total_market_val == 0:
            return {"vol": 0, "var_95": 0, "beta": 0, "sharpe": 0}

        # 对齐收益率序列 (取最短长度)
        min_len = min(len(r) for r in returns_dict.values())
        aligned_returns = {t: r[-min_len:] for t, r in returns_dict.items()}

        # 加权组合收益率
        portfolio_returns = np.zeros(min_len)
        for ticker, returns in aligned_returns.items():
            weight = next(
                (float(p.get("market_val", 0)) / total_market_val for p in positions if p.get("code") == ticker),
                0,
            )
            portfolio_returns += returns * weight

        # 波动率 (年化)
        vol = float(np.std(portfolio_returns) * np.sqrt(252))

        # VaR (95%, 历史模拟法)
        var_95 = float(np.percentile(portfolio_returns, 5))

        # Beta (vs 基准，简化处理：假设基准收益率为 0)
        # TODO: 获取真实基准指数 K 线
        beta = 0.85  # 临时占位

        # Sharpe (无风险利率假设 4%)
        risk_free_rate = 0.04
        annual_return = float(np.mean(portfolio_returns) * 252)
        sharpe = (annual_return - risk_free_rate) / vol if vol > 0 else 0

        return {
            "vol": vol,
            "var_95": var_95,
            "beta": beta,
            "sharpe": sharpe,
        }

    async def _get_nav_snapshots(self, market: str = "HK", days: int = 1) -> List[Dict[str, Any]]:
        """
        获取分账户 NAV 快照序列
        - days=1: 从 Redis 读取最近 24h (快速)
        - days>1: 从数据库读取历史数据 (持久化)
        """
        if days <= 1:
            # 从 Redis 读取最近 24h
            key = f"quant:risk:nav_snapshots:{market}"
            try:
                raw_list = await redis_client.lrange(key, 0, 287)
                snapshots = []
                for item in raw_list:
                    try:
                        data = json.loads(item)
                        snapshots.append({"ts": data["ts"], "nav": data["nav"]})
                    except Exception:
                        continue
                return snapshots
            except Exception as e:
                logger.warning(f"[RiskEngine] Redis 获取 {market} NAV 快照失败: {e}")
                return []
        else:
            # 从数据库读取历史数据
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=days)
                async with AsyncSessionLocal() as db:
                    stmt = (
                        select(NavSnapshot)
                        .where(NavSnapshot.market == market, NavSnapshot.created_at >= cutoff)
                        .order_by(NavSnapshot.created_at.desc())
                        .limit(2000)  # 最多返回 2000 条 (约 7 天)
                    )
                    result = await db.execute(stmt)
                    rows = result.scalars().all()

                snapshots = [
                    {"ts": row.created_at.timestamp(), "nav": row.nav}
                    for row in reversed(rows)  # 按时间正序返回
                ]
                return snapshots
            except Exception as e:
                logger.warning(f"[RiskEngine] DB 获取 {market} NAV 快照失败: {e}")
                return []

    def _calc_max_dd_from_snapshots(self, snapshots: List[Dict[str, Any]]) -> float:
        """从 NAV 快照计算最大回撤"""
        if len(snapshots) < 2:
            return 0.0

        navs = [s["nav"] for s in snapshots]
        peak = navs[0]
        max_dd = 0.0

        for nav in navs:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return -max_dd * 100  # 返回百分比

    def _build_risk_radar(self, metrics: Dict[str, Any], max_dd: float) -> List[Dict[str, float]]:
        """构建六维风险雷达"""
        # 归一化到 0-100 分
        beta_score = min(abs(metrics.get("beta", 0)) * 100, 100)
        vol_score = min(metrics.get("vol", 0) * 100, 100)
        liq_score = 72  # TODO: 基于持仓流动性计算
        corr_score = 58  # TODO: 基于相关性矩阵计算
        mom_score = 81  # TODO: 基于动量因子计算
        dd_score = min(abs(max_dd) * 5, 100)  # -20% → 100 分

        return [
            {"axis": "Beta", "current": round(beta_score, 0), "limit": 100},
            {"axis": "Vol", "current": round(vol_score, 0), "limit": 70},
            {"axis": "Liq", "current": round(liq_score, 0), "limit": 60},
            {"axis": "Corr", "current": round(corr_score, 0), "limit": 80},
            {"axis": "Mom", "current": round(mom_score, 0), "limit": 75},
            {"axis": "DD", "current": round(dd_score, 0), "limit": 80},
        ]

    def _build_risk_factors(self, metrics: Dict[str, Any], max_dd: float) -> List[Dict[str, Any]]:
        """构建因子监控"""
        beta = metrics.get("beta", 0)
        var_95 = metrics.get("var_95", 0)
        sharpe = metrics.get("sharpe", 0)

        # 状态判断
        def status(val: float, thresholds: tuple) -> str:
            if val <= thresholds[0]:
                return "safe"
            elif val <= thresholds[1]:
                return "warn"
            else:
                return "crit"

        return [
            {
                "label": "Market Beta",
                "value": round(beta, 2),
                "threshold": 1.0,
                "unit": "",
                "status": "safe" if abs(beta) < 1.0 else "warn",
            },
            {
                "label": "VaR (95%)",
                "value": round(var_95 * 10000, 0),  # 转换为金额
                "threshold": -3000,
                "unit": "$",
                "status": status(abs(var_95 * 10000), (2000, 3000)),
            },
            {
                "label": "Sharpe",
                "value": round(sharpe, 2),
                "threshold": 1.5,
                "unit": "",
                "status": "good" if sharpe > 1.5 else "warn" if sharpe > 1.0 else "crit",
            },
            {
                "label": "Max DD",
                "value": round(max_dd, 2),
                "threshold": -15.0,
                "unit": "%",
                "status": "safe" if max_dd > -10 else "warn" if max_dd > -15 else "crit",
            },
        ]

    def _fallback_data(self, reason: str) -> Dict[str, Any]:
        """降级数据"""
        return {
            "status": "error",
            "message": reason,
            "kpi": {
                "nav": 0,
                "nav_fmt": "$0.00",
                "today_pl": 0,
                "today_pl_fmt": "$0.00",
                "today_pl_pct": 0,
                "cash": 0,
                "cash_fmt": "$0.00",
                "leverage": 0,
                "leverage_fmt": "0.0%",
            },
            "exposure": [],
            "risk_radar": [],
            "risk_factors": [],
            "nav_snapshots": [],
            "positions": [],
            "ts": time.time(),
        }


# 全局单例
risk_engine = RiskEngine()
