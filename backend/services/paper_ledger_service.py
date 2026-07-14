"""
PT-01a: 纸面组合账本服务
========================
PG 流水账本 SSOT：paper_fills 只增不改，paper_positions 是流水的投影。
核心函数：record_fill / rebuild_positions / reconcile / create_portfolio。
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.models import PaperFill, PaperNavDaily, PaperPortfolio, PaperPosition


class PaperLedgerService:
    """纸面组合账本服务（同步 Session，与 strategy_version_service 同模式）"""

    # ─────────────────────────────────────────
    #  组合生命周期
    # ─────────────────────────────────────────

    def create_portfolio(
        self,
        db: Session,
        name: str,
        strategy_name: str,
        code_hash: str,
        market: str,
        initial_capital: float = 100000.0,
        params: Optional[Dict[str, Any]] = None,
        strategy_version_id: Optional[str] = None,
        benchmark_backtest_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建纸面组合主档"""
        pid = str(uuid.uuid4())
        portfolio = PaperPortfolio(
            id=pid,
            name=name,
            strategy_name=strategy_name,
            code_hash=code_hash,
            market=market,
            initial_capital=initial_capital,
            params=params or {},
            strategy_version_id=strategy_version_id,
            benchmark_backtest_ref=benchmark_backtest_ref,
            status="running",
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        return self._portfolio_to_dict(portfolio)

    def get_portfolio(self, db: Session, portfolio_id: str) -> Optional[Dict[str, Any]]:
        """获取单个组合详情"""
        p = db.query(PaperPortfolio).filter(PaperPortfolio.id == portfolio_id).first()
        return self._portfolio_to_dict(p) if p else None

    def list_portfolios(self, db: Session, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出组合"""
        q = db.query(PaperPortfolio)
        if status:
            q = q.filter(PaperPortfolio.status == status)
        return [self._portfolio_to_dict(p) for p in q.order_by(PaperPortfolio.created_at.desc()).all()]

    def update_status(self, db: Session, portfolio_id: str, new_status: str) -> bool:
        """更新组合状态（pause / resume / close）"""
        p = db.query(PaperPortfolio).filter(PaperPortfolio.id == portfolio_id).first()
        if not p:
            return False
        p.status = new_status
        if new_status == "closed":
            p.closed_at = datetime.utcnow()
        db.commit()
        return True

    # ─────────────────────────────────────────
    #  记账核心
    # ─────────────────────────────────────────

    def record_fill(
        self,
        db: Session,
        portfolio_id: str,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        dt: Optional[datetime] = None,
        commission: float = 0.0,
        slippage: float = 0.0,
        intent_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        记录一笔成交：
        1. 分配 fill_seq（组合内单调递增）
        2. 写入 paper_fills
        3. 更新 paper_positions 投影
        """
        if dt is None:
            dt = datetime.utcnow()

        # 分配 fill_seq: SELECT MAX(fill_seq) + 1
        max_seq = db.query(sa_func.max(PaperFill.fill_seq)).filter(PaperFill.portfolio_id == portfolio_id).scalar()
        next_seq = (max_seq or 0) + 1

        fill = PaperFill(
            id=str(uuid.uuid4()),
            portfolio_id=portfolio_id,
            fill_seq=next_seq,
            dt=dt,
            symbol=symbol,
            side=side.upper(),
            qty=qty,
            price=price,
            commission=commission,
            slippage=slippage,
            intent_tag=intent_tag,
        )
        db.add(fill)

        # 更新持仓投影
        self._update_position(db, portfolio_id, symbol, side.upper(), qty, price, next_seq)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise  # fill_seq 冲突（理论上不应发生，因有 MAX+1 保护）

        return {
            "fill_id": fill.id,
            "fill_seq": next_seq,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "side": side.upper(),
            "qty": qty,
            "price": price,
        }

    def _update_position(
        self,
        db: Session,
        portfolio_id: str,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        fill_seq: int,
    ) -> None:
        """更新 paper_positions 投影（买入加仓/卖出减仓）"""
        pos = (
            db.query(PaperPosition)
            .filter(PaperPosition.portfolio_id == portfolio_id, PaperPosition.symbol == symbol)
            .first()
        )

        if side == "BUY":
            if pos is None:
                pos = PaperPosition(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                    qty=qty,
                    avg_cost=price,
                    last_fill_seq=fill_seq,
                )
                db.add(pos)
            else:
                # 加权平均成本
                total_cost = pos.avg_cost * pos.qty + price * qty
                pos.qty += qty
                pos.avg_cost = total_cost / pos.qty if pos.qty > 0 else 0.0
                pos.last_fill_seq = fill_seq
        elif side == "SELL":
            if pos is not None:
                pos.qty -= qty
                pos.last_fill_seq = fill_seq
                if pos.qty <= 0:
                    # 清仓：删除持仓记录
                    db.delete(pos)

    # ─────────────────────────────────────────
    #  重放与对账
    # ─────────────────────────────────────────

    def rebuild_positions(self, db: Session, portfolio_id: str) -> Dict[str, Dict[str, Any]]:
        """
        从 paper_fills 全量重放，返回 positions dict。
        返回格式: {symbol: {qty, avg_cost, last_fill_seq}}
        """
        fills = (
            db.query(PaperFill).filter(PaperFill.portfolio_id == portfolio_id).order_by(PaperFill.fill_seq.asc()).all()
        )

        positions: Dict[str, Dict[str, Any]] = {}
        for fill in fills:
            sym = fill.symbol
            if sym not in positions:
                positions[sym] = {"qty": 0, "avg_cost": 0.0, "last_fill_seq": 0}

            p = positions[sym]
            if fill.side == "BUY":
                total_cost = p["avg_cost"] * p["qty"] + fill.price * fill.qty
                p["qty"] += fill.qty
                p["avg_cost"] = total_cost / p["qty"] if p["qty"] > 0 else 0.0
            elif fill.side == "SELL":
                p["qty"] -= fill.qty
                if p["qty"] <= 0:
                    del positions[sym]
                    continue

            p["last_fill_seq"] = fill.fill_seq

        return positions

    def reconcile(self, db: Session, portfolio_id: str) -> Dict[str, Any]:
        """
        对账：比较重放结果 vs paper_positions 投影。
        返回 {consistent: bool, projected: {...}, replayed: {...}}
        """
        # 投影
        projected_rows = db.query(PaperPosition).filter(PaperPosition.portfolio_id == portfolio_id).all()
        projected = {
            p.symbol: {"qty": p.qty, "avg_cost": p.avg_cost, "last_fill_seq": p.last_fill_seq} for p in projected_rows
        }

        # 重放
        replayed = self.rebuild_positions(db, portfolio_id)

        # 比较
        consistent = True
        all_symbols = set(projected.keys()) | set(replayed.keys())
        for sym in all_symbols:
            pj = projected.get(sym, {"qty": 0, "avg_cost": 0.0})
            rp = replayed.get(sym, {"qty": 0, "avg_cost": 0.0})
            if pj["qty"] != rp["qty"] or abs(pj["avg_cost"] - rp["avg_cost"]) > 1e-6:
                consistent = False
                break

        return {
            "consistent": consistent,
            "projected": projected,
            "replayed": replayed,
        }

    # ─────────────────────────────────────────
    #  查询
    # ─────────────────────────────────────────

    def get_fills(self, db: Session, portfolio_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """成交流水分页"""
        fills = (
            db.query(PaperFill)
            .filter(PaperFill.portfolio_id == portfolio_id)
            .order_by(PaperFill.fill_seq.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": f.id,
                "portfolio_id": f.portfolio_id,
                "fill_seq": f.fill_seq,
                "dt": f.dt.isoformat() if f.dt else None,
                "symbol": f.symbol,
                "side": f.side,
                "qty": f.qty,
                "price": f.price,
                "commission": f.commission,
                "slippage": f.slippage,
                "intent_tag": f.intent_tag,
            }
            for f in fills
        ]

    def get_positions(self, db: Session, portfolio_id: str) -> List[Dict[str, Any]]:
        """当前持仓"""
        positions = db.query(PaperPosition).filter(PaperPosition.portfolio_id == portfolio_id).all()
        return [
            {
                "portfolio_id": p.portfolio_id,
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_cost": p.avg_cost,
                "last_fill_seq": p.last_fill_seq,
            }
            for p in positions
        ]

    def get_nav_daily(self, db: Session, portfolio_id: str, days: int = 30) -> List[Dict[str, Any]]:
        """日终净值序列"""
        rows = (
            db.query(PaperNavDaily)
            .filter(PaperNavDaily.portfolio_id == portfolio_id)
            .order_by(PaperNavDaily.trade_date.desc())
            .limit(days)
            .all()
        )
        return [
            {
                "portfolio_id": r.portfolio_id,
                "trade_date": r.trade_date.isoformat() if r.trade_date else None,
                "nav": r.nav,
                "cash": r.cash,
                "market_value": r.market_value,
                "daily_return": r.daily_return,
                "stale_symbols": r.stale_symbols,
            }
            for r in reversed(rows)
        ]

    # ─────────────────────────────────────────
    #  辅助
    # ─────────────────────────────────────────

    @staticmethod
    def _portfolio_to_dict(p: Optional[PaperPortfolio]) -> Dict[str, Any]:
        if p is None:
            return {}
        return {
            "id": p.id,
            "name": p.name,
            "strategy_name": p.strategy_name,
            "strategy_version_id": p.strategy_version_id,
            "code_hash": p.code_hash,
            "params": p.params,
            "market": p.market,
            "initial_capital": p.initial_capital,
            "benchmark_backtest_ref": p.benchmark_backtest_ref,
            "bot_id": p.bot_id,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        }


# 模块级单例（与 strategy_version_service 同模式）
paper_ledger_service = PaperLedgerService()
