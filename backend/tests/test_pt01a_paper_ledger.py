"""
PT-01a: 纸面组合账本服务测试
"""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from backend.core.models import (
    PaperFill,
    PaperNavDaily,
    PaperPortfolio,
    PaperPosition,
)
from backend.services.paper_ledger_service import PaperLedgerService


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock(spec=Session)
    db.query.return_value = MagicMock()
    return db


@pytest.fixture
def svc():
    return PaperLedgerService()


# ─────────────────────────────────────────
#  ORM 模型测试
# ─────────────────────────────────────────


class TestORMModels:
    def test_paper_portfolio_tablename(self):
        assert PaperPortfolio.__tablename__ == "paper_portfolios"

    def test_paper_fill_tablename(self):
        assert PaperFill.__tablename__ == "paper_fills"

    def test_paper_position_tablename(self):
        assert PaperPosition.__tablename__ == "paper_positions"

    def test_paper_nav_daily_tablename(self):
        assert PaperNavDaily.__tablename__ == "paper_nav_daily"


# ─────────────────────────────────────────
#  create_portfolio
# ─────────────────────────────────────────


class TestCreatePortfolio:
    def test_create_portfolio_basic(self, mock_db, svc):
        """创建组合应返回完整字典"""
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None

        result = svc.create_portfolio(
            db=mock_db,
            name="测试组合",
            strategy_name="MACross",
            code_hash="a" * 64,
            market="HK",
            initial_capital=200000.0,
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        assert result["name"] == "测试组合"
        assert result["strategy_name"] == "MACross"
        assert result["market"] == "HK"
        assert result["initial_capital"] == 200000.0
        assert result["status"] == "running"

    def test_create_portfolio_with_version(self, mock_db, svc):
        """创建组合可绑定策略版本"""
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None

        result = svc.create_portfolio(
            db=mock_db,
            name="V1组合",
            strategy_name="MACross",
            code_hash="b" * 64,
            market="US",
            strategy_version_id="ver-001",
        )

        assert result["strategy_version_id"] == "ver-001"


# ─────────────────────────────────────────
#  record_fill + fill_seq 递增
# ─────────────────────────────────────────


class TestRecordFill:
    def test_first_fill_seq_is_1(self, mock_db, svc):
        """第一笔成交 fill_seq = 1"""
        # MAX(fill_seq) 返回 None（无历史成交）
        mock_db.query.return_value.filter.return_value.scalar.return_value = None
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.return_value = None

        result = svc.record_fill(
            db=mock_db,
            portfolio_id="pid-1",
            symbol="HK.00700",
            side="BUY",
            qty=100,
            price=350.0,
        )

        assert result["fill_seq"] == 1
        assert result["side"] == "BUY"
        assert result["qty"] == 100

    def test_fill_seq_increments(self, mock_db, svc):
        """第二笔成交 fill_seq = 2"""
        mock_db.query.return_value.filter.return_value.scalar.return_value = 1
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit.return_value = None

        result = svc.record_fill(
            db=mock_db,
            portfolio_id="pid-1",
            symbol="HK.00700",
            side="BUY",
            qty=50,
            price=360.0,
        )

        assert result["fill_seq"] == 2

    def test_sell_updates_position(self, mock_db, svc):
        """卖出应更新持仓投影"""
        # 已有持仓
        mock_pos = MagicMock()
        mock_pos.qty = 100
        mock_pos.avg_cost = 350.0
        mock_pos.last_fill_seq = 1
        mock_db.query.return_value.filter.return_value.scalar.return_value = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_pos
        mock_db.commit.return_value = None

        result = svc.record_fill(
            db=mock_db,
            portfolio_id="pid-1",
            symbol="HK.00700",
            side="SELL",
            qty=50,
            price=360.0,
        )

        assert result["side"] == "SELL"
        assert mock_pos.qty == 50  # 100 - 50


# ─────────────────────────────────────────
#  rebuild_positions + reconcile
# ─────────────────────────────────────────


class TestRebuildAndReconcile:
    def test_rebuild_empty(self, mock_db, svc):
        """无成交记录时重放结果为空"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = svc.rebuild_positions(mock_db, "pid-1")
        assert result == {}

    def test_rebuild_buy_sell(self, mock_db, svc):
        """买入+卖出后重放应得到正确持仓"""
        fill1 = MagicMock(spec=PaperFill)
        fill1.symbol = "HK.00700"
        fill1.side = "BUY"
        fill1.qty = 100
        fill1.price = 350.0
        fill1.fill_seq = 1

        fill2 = MagicMock(spec=PaperFill)
        fill2.symbol = "HK.00700"
        fill2.side = "SELL"
        fill2.qty = 30
        fill2.price = 360.0
        fill2.fill_seq = 2

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            fill1, fill2
        ]

        result = svc.rebuild_positions(mock_db, "pid-1")
        assert result["HK.00700"]["qty"] == 70  # 100 - 30

    def test_rebuild_full_sell_removes_position(self, mock_db, svc):
        """全部卖出后持仓应被移除"""
        fill1 = MagicMock(spec=PaperFill)
        fill1.symbol = "HK.00700"
        fill1.side = "BUY"
        fill1.qty = 100
        fill1.price = 350.0
        fill1.fill_seq = 1

        fill2 = MagicMock(spec=PaperFill)
        fill2.symbol = "HK.00700"
        fill2.side = "SELL"
        fill2.qty = 100
        fill2.price = 360.0
        fill2.fill_seq = 2

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            fill1, fill2
        ]

        result = svc.rebuild_positions(mock_db, "pid-1")
        assert "HK.00700" not in result

    def test_reconcile_consistent(self, mock_db, svc):
        """投影与重放一致时 consistent=True"""
        mock_pos = MagicMock()
        mock_pos.symbol = "HK.00700"
        mock_pos.qty = 100
        mock_pos.avg_cost = 350.0
        mock_pos.last_fill_seq = 1

        fill1 = MagicMock(spec=PaperFill)
        fill1.symbol = "HK.00700"
        fill1.side = "BUY"
        fill1.qty = 100
        fill1.price = 350.0
        fill1.fill_seq = 1

        # reconcile: query().filter().all() -> [mock_pos]
        # rebuild_positions: query().filter().order_by().all() -> [fill1]
        mock_all = MagicMock(side_effect=[[mock_pos], [fill1]])
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        mock_filter.order_by.return_value = mock_filter  # order_by 返回自身
        mock_query_result = MagicMock()
        mock_query_result.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query_result

        result = svc.reconcile(mock_db, "pid-1")
        assert result["consistent"] is True

    def test_reconcile_inconsistent(self, mock_db, svc):
        """投影与重放不一致时 consistent=False"""
        mock_pos = MagicMock()
        mock_pos.symbol = "HK.00700"
        mock_pos.qty = 200  # 投影显示 200
        mock_pos.avg_cost = 350.0
        mock_pos.last_fill_seq = 1

        fill1 = MagicMock(spec=PaperFill)
        fill1.symbol = "HK.00700"
        fill1.side = "BUY"
        fill1.qty = 100  # 但重放只有 100
        fill1.price = 350.0
        fill1.fill_seq = 1

        mock_all = MagicMock(side_effect=[[mock_pos], [fill1]])
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        mock_filter.order_by.return_value = mock_filter
        mock_query_result = MagicMock()
        mock_query_result.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query_result

        result = svc.reconcile(mock_db, "pid-1")
        assert result["consistent"] is False


# ─────────────────────────────────────────
#  update_status
# ─────────────────────────────────────────


class TestUpdateStatus:
    def test_pause(self, mock_db, svc):
        """暂停组合"""
        mock_p = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_p
        mock_db.commit.return_value = None

        ok = svc.update_status(mock_db, "pid-1", "paused")
        assert ok is True
        assert mock_p.status == "paused"

    def test_close_sets_closed_at(self, mock_db, svc):
        """关闭组合应设置 closed_at"""
        mock_p = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_p
        mock_db.commit.return_value = None

        ok = svc.update_status(mock_db, "pid-1", "closed")
        assert ok is True
        assert mock_p.closed_at is not None

    def test_nonexistent_returns_false(self, mock_db, svc):
        """不存在的组合返回 False"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        ok = svc.update_status(mock_db, "pid-nope", "paused")
        assert ok is False
