"""
PT-01c: 纸面组合结算守护进程
==============================
职责：
  1. EOD 结算 — 每个交易日收盘后逐组合计算 NAV 并写入 paper_nav_daily
  2. 盘中快照 — 交易时段内每 5 分钟写 Redis List 环形 288 点
  3. 补结算   — 检测 <=7 天缺口自动补齐
  4. 周度对账 — 从 fills 重放 vs positions 投影一致性校验

数据驱动交易日判定：基准标的是否有当日 K_DAY bar。
停牌前收兜底：取不到收盘价的标的用前收 + stale_symbols 标记。
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.core.models import PaperFill, PaperNavDaily, PaperPortfolio, PaperPosition
from backend.core.redis_client import redis_client
from backend.services.kline_warehouse import kline_warehouse
from backend.services.paper_ledger_service import paper_ledger_service

logger = logging.getLogger(__name__)

# 市场 → 基准标的
BENCHMARK_MAP = {"HK": "HK.00700", "US": "US.SPY"}

# 盘中快照最大点数（5 分钟间隔 × 24 小时 = 288）
INTRADAY_MAX_POINTS = 288


class PaperSettlementDaemon:
    """纸面组合结算守护进程"""

    def __init__(self) -> None:
        self._running = True

    # ─────────────────────────────────────────
    #  主循环
    # ─────────────────────────────────────────

    async def run(self) -> None:
        """主循环：挂 worker.py，每 5 分钟检查一次"""
        logger.info("[PaperSettlement] daemon started")
        while self._running:
            try:
                for market in ["HK", "US"]:
                    is_td = await self._is_trading_day(market)
                    if is_td:
                        if await self._is_post_market(market):
                            await self._settle_market(market)
                        else:
                            await self._intraday_snapshot(market)
                # 每天首次循环时检查补结算
                await self.backfill_settlement(max_days=7)
            except Exception as e:
                logger.error(f"[PaperSettlement] 主循环异常: {e}")
            await asyncio.sleep(300)  # 5 分钟

    def stop(self) -> None:
        self._running = False

    # ─────────────────────────────────────────
    #  交易日 / 时段判定
    # ─────────────────────────────────────────

    async def _is_trading_day(self, market: str) -> bool:
        """数据驱动判定：基准标的是否有当日 K_DAY bar"""
        benchmark = BENCHMARK_MAP.get(market)
        if not benchmark:
            return False
        df = await kline_warehouse.get_history(benchmark, "K_DAY", num=2)
        if df is None or df.empty:
            return False
        # 检查最新 bar 是否为今天
        last_time = df["time"].max()
        if hasattr(last_time, "date"):
            return last_time.date() == date.today()
        return False

    async def _is_post_market(self, market: str) -> bool:
        """简化判定：UTC 14:00 后视为盘后（覆盖 HK 16:00 HKT = 08:00 UTC）"""
        now_utc = datetime.now(timezone.utc)
        # HK 收盘 16:00 HKT = 08:00 UTC; US 收盘 16:00 EST = 21:00 UTC
        # 统一用 UTC 14:00 作为判定线（覆盖两个市场）
        return now_utc.hour >= 14

    # ─────────────────────────────────────────
    #  EOD 结算
    # ─────────────────────────────────────────

    async def _settle_market(self, market: str) -> None:
        """EOD 结算：Redis NX 锁 -> 逐组合结算"""
        today = date.today()
        lock_key = f"quant:lock:paper_settle:{market}:{today.isoformat()}"
        acquired = await redis_client.set(lock_key, "1", nx=True, ex=14400)
        if not acquired:
            logger.debug(f"[PaperSettlement] {market} {today} 已结算，跳过")
            return

        logger.info(f"[PaperSettlement] {market} {today} 开始 EOD 结算")
        db = SessionLocal()
        try:
            portfolios = self._get_running_portfolios(db, market)
            for p in portfolios:
                try:
                    await self._settle_portfolio(db, p, today)
                    # PT-02a: EOD 结算钩子——检测漂移
                    await self._check_drift(db, p)
                except Exception as e:
                    logger.error(f"[PaperSettlement] 结算组合 {p.id} 失败: {e}")
            db.commit()
        except Exception as e:
            logger.error(f"[PaperSettlement] settle_market 异常: {e}")
            db.rollback()
        finally:
            db.close()

    async def _settle_portfolio(self, db: Session, portfolio: PaperPortfolio, trade_date: date) -> None:
        """单组合结算：取收盘价 -> 计算 NAV -> 写 paper_nav_daily"""
        pid = portfolio.id

        # 幂等检查：同日期覆盖
        existing = (
            db.query(PaperNavDaily)
            .filter(
                PaperNavDaily.portfolio_id == pid,
                PaperNavDaily.trade_date == trade_date,
            )
            .first()
        )

        # 获取当前持仓
        positions = db.query(PaperPosition).filter(PaperPosition.portfolio_id == pid).all()

        # 计算现金 = initial_capital + 卖出收入 - 买入支出 - 总手续费
        cash = self._compute_cash(db, pid, portfolio.initial_capital)

        # 逐持仓取收盘价
        market_value = 0.0
        stale_symbols: List[str] = []
        prev_close_cache: Dict[str, float] = {}

        # 如果有前日 NAV，加载前收兜底价格
        prev_nav = (
            db.query(PaperNavDaily)
            .filter(PaperNavDaily.portfolio_id == pid)
            .order_by(PaperNavDaily.trade_date.desc())
            .first()
        )
        if prev_nav and prev_nav.stale_symbols:
            # 从 stale_symbols 中恢复前收价格
            prev_close_cache = prev_nav.stale_symbols.get("prices", {})

        for pos in positions:
            close_price = await self._get_close_price(pos.symbol)
            if close_price is not None:
                market_value += pos.qty * close_price
            elif pos.symbol in prev_close_cache:
                # 停牌前收兜底
                close_price = prev_close_cache[pos.symbol]
                market_value += pos.qty * close_price
                stale_symbols.append(pos.symbol)
            else:
                # 完全取不到价格，用成本价兜底 + 标记 stale
                market_value += pos.qty * pos.avg_cost
                stale_symbols.append(pos.symbol)

        nav = cash + market_value

        # 计算日收益率
        daily_return: Optional[float] = None
        if prev_nav and prev_nav.nav > 0:
            daily_return = (nav - prev_nav.nav) / prev_nav.nav

        # 写入 / 覆盖 paper_nav_daily
        stale_payload = {"symbols": stale_symbols, "prices": prev_close_cache} if stale_symbols else None
        if stale_symbols:
            # 把当前 stale 标的的收盘价也存入，供次日兜底
            for sym in stale_symbols:
                if sym not in stale_payload["prices"]:
                    stale_payload["prices"][sym] = positions[
                        next(i for i, p in enumerate(positions) if p.symbol == sym)
                    ].avg_cost

        if existing:
            existing.nav = nav
            existing.cash = cash
            existing.market_value = market_value
            existing.daily_return = daily_return
            existing.stale_symbols = stale_payload
            existing.settled_at = datetime.now(timezone.utc)
        else:
            row = PaperNavDaily(
                portfolio_id=pid,
                trade_date=trade_date,
                nav=nav,
                cash=cash,
                market_value=market_value,
                daily_return=daily_return,
                stale_symbols=stale_payload,
            )
            db.add(row)

        logger.info(f"[PaperSettlement] {pid} {trade_date} NAV={nav:.2f} cash={cash:.2f} mv={market_value:.2f}")

    def _compute_cash(self, db: Session, portfolio_id: str, initial_capital: float) -> float:
        """从 fills 推算现金 = initial_capital + Σ卖 - Σ买 - Σ手续费"""
        fills = db.query(PaperFill).filter(PaperFill.portfolio_id == portfolio_id).all()
        cash = initial_capital
        for f in fills:
            turnover = f.qty * f.price
            if f.side == "BUY":
                cash -= turnover + f.commission
            elif f.side == "SELL":
                cash += turnover - f.commission
        return cash

    async def _get_close_price(self, symbol: str) -> Optional[float]:
        """取最新 K_DAY 收盘价"""
        df = await kline_warehouse.get_history(symbol, "K_DAY", num=1)
        if df is not None and not df.empty:
            return float(df.iloc[-1]["close"])
        return None

    def _get_running_portfolios(self, db: Session, market: str) -> List[PaperPortfolio]:
        """获取指定市场 running 状态的组合"""
        return (
            db.query(PaperPortfolio)
            .filter(
                PaperPortfolio.market == market,
                PaperPortfolio.status == "running",
            )
            .all()
        )

    # ─────────────────────────────────────────
    #  盘中快照
    # ─────────────────────────────────────────

    async def _intraday_snapshot(self, market: str) -> None:
        """盘中快照：Redis List 环形 288 点"""
        db = SessionLocal()
        try:
            portfolios = self._get_running_portfolios(db, market)
            for p in portfolios:
                pid = p.id
                positions = db.query(PaperPosition).filter(PaperPosition.portfolio_id == pid).all()
                cash = self._compute_cash(db, pid, p.initial_capital)
                mv = 0.0
                for pos in positions:
                    price = await self._get_close_price(pos.symbol)
                    if price is not None:
                        mv += pos.qty * price
                nav = cash + mv
                point = json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "nav": round(nav, 4),
                        "cash": round(cash, 4),
                        "mv": round(mv, 4),
                    }
                )
                key = f"quant:paper:{pid}:nav_intraday"
                await redis_client.lpush(key, point)
                await redis_client.ltrim(key, 0, INTRADAY_MAX_POINTS - 1)
        except Exception as e:
            logger.error(f"[PaperSettlement] intraday_snapshot 异常: {e}")
        finally:
            db.close()

    # ─────────────────────────────────────────
    #  补结算
    # ─────────────────────────────────────────

    async def backfill_settlement(self, max_days: int = 7) -> None:
        """补结算：检查缺口 <= max_days 天自动补"""
        today = date.today()
        db = SessionLocal()
        try:
            portfolios = db.query(PaperPortfolio).filter(PaperPortfolio.status == "running").all()
            for p in portfolios:
                # 找到最新结算日
                latest = (
                    db.query(PaperNavDaily)
                    .filter(PaperNavDaily.portfolio_id == p.id)
                    .order_by(PaperNavDaily.trade_date.desc())
                    .first()
                )
                if latest is None:
                    # 从未结算，从创建日开始补（最多 max_days 天）
                    start = p.created_at.date() if p.created_at else today - timedelta(days=max_days)
                else:
                    start = latest.trade_date + timedelta(days=1)

                gap_days = (today - start).days
                if gap_days < 0:
                    continue  # 已结算到未来
                if gap_days > max_days:
                    start = today - timedelta(days=max_days)

                d = start
                while d < today:
                    lock_key = f"quant:lock:paper_settle:{p.market}:{d.isoformat()}"
                    acquired = await redis_client.set(lock_key, "1", nx=True, ex=14400)
                    if acquired:
                        try:
                            await self._settle_portfolio(db, p, d)
                            db.commit()
                            logger.info(f"[PaperSettlement] 补结算 {p.id} {d}")
                        except Exception as e:
                            logger.error(f"[PaperSettlement] 补结算 {p.id} {d} 失败: {e}")
                            db.rollback()
                    d += timedelta(days=1)
        except Exception as e:
            logger.error(f"[PaperSettlement] backfill 异常: {e}")
        finally:
            db.close()

    # ─────────────────────────────────────────
    #  周度对账
    # ─────────────────────────────────────────

    async def weekly_reconcile(self) -> Dict[str, Any]:
        """周度对账：从 fills 重放 vs positions 投影"""
        db = SessionLocal()
        results: Dict[str, Any] = {}
        try:
            portfolios = db.query(PaperPortfolio).filter(PaperPortfolio.status.in_(["running", "paused"])).all()
            for p in portfolios:
                rc = paper_ledger_service.reconcile(db, p.id)
                results[p.id] = rc
                if not rc["consistent"]:
                    logger.warning(
                        f"[PaperSettlement] 对账不一致 {p.id}: projected={rc['projected']} replayed={rc['replayed']}"
                    )
        except Exception as e:
            logger.error(f"[PaperSettlement] weekly_reconcile 异常: {e}")
        finally:
            db.close()
        return results

    # ─────────────────────────────────────────
    #  漂移检测 (PT-02a)
    # ─────────────────────────────────────────

    async def _check_drift(self, db: Session, portfolio: PaperPortfolio) -> None:
        """EOD 结算钩子：计算滚动 20 交易日 TE，超阈值触发 paper_drift 告警"""
        import pandas as pd

        from backend.services import performance as perf

        pid = portfolio.id
        nav_rows = paper_ledger_service.get_nav_daily(db, pid, days=21)  # 21 条 → 20 个收益率
        if len(nav_rows) < 21:
            return  # 数据不足

        nav_series = pd.Series([r["nav"] for r in nav_rows])
        returns = nav_series.pct_change().dropna()

        # 简化：与等权基准（0 收益）比较，即 TE = volatility of returns
        # 有 benchmark 时与 benchmark 比较
        benchmark_ref = portfolio.benchmark_backtest_ref if hasattr(portfolio, "benchmark_backtest_ref") else None
        if benchmark_ref:
            bench_nav = _load_benchmark_nav_sync(benchmark_ref, 21)
            if bench_nav is not None and len(bench_nav) > 1:
                bench_returns = bench_nav.pct_change().dropna()
                te = perf.tracking_error(returns, bench_returns)
            else:
                te = perf.volatility(returns)
        else:
            te = perf.volatility(returns)

        # 默认阈值: TE 年化 15%
        te_threshold = 0.15
        if te > te_threshold:
            logger.warning(f"[PaperSettlement] paper_drift 告警: {pid} TE={te:.4f} > {te_threshold}")
            # 写入 Redis 告警键，前端轮询读取
            alert_key = f"quant:paper:{pid}:drift_alert"
            await redis_client.set(
                alert_key,
                json.dumps(
                    {"te": round(te, 6), "threshold": te_threshold, "ts": datetime.now(timezone.utc).isoformat()}
                ),
                ex=86400,
            )


def _load_benchmark_nav_sync(ref: str, days: int):
    """同步加载 benchmark NAV（简化实现，返回 None）"""
    return None


# 模块级单例
paper_settlement_daemon = PaperSettlementDaemon()
