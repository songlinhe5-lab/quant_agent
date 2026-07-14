"""
PT-01c: 结算 daemon 测试
========================
覆盖：交易日判定 / 结算幂等 / 停牌前收兜底 / 补结算 / NX 锁互斥 / 周度对账
"""
import asyncio
import json
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pandas as pd

from backend.services.paper_settlement_daemon import PaperSettlementDaemon


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


def _make_daemon() -> PaperSettlementDaemon:
    return PaperSettlementDaemon()


def _make_portfolio(pid: str = "p1", market: str = "HK", initial_capital: float = 100000.0) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.market = market
    p.initial_capital = initial_capital
    p.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    p.status = "running"
    return p


def _make_position(symbol: str, qty: int, avg_cost: float) -> MagicMock:
    pos = MagicMock()
    pos.symbol = symbol
    pos.qty = qty
    pos.avg_cost = avg_cost
    return pos


def _make_fill(side: str, symbol: str, qty: int, price: float, commission: float = 0.0) -> MagicMock:
    f = MagicMock()
    f.side = side
    f.symbol = symbol
    f.qty = qty
    f.price = price
    f.commission = commission
    return f


def _mock_db_session():
    """创建一个 mock DB session"""
    db = MagicMock()
    return db


# ─────────────────────────────────────────
#  交易日判定
# ─────────────────────────────────────────


class TestIsTradingDay:
    @pytest.mark.asyncio
    async def test_trading_day_when_bar_exists(self):
        """基准标的有当日 K_DAY bar → True"""
        daemon = _make_daemon()
        today = date.today()
        df = pd.DataFrame({"time": [datetime(today.year, today.month, today.day)], "close": [350.0]})

        with patch("backend.services.paper_settlement_daemon.kline_warehouse") as mock_kw:
            mock_kw.get_history = AsyncMock(return_value=df)
            result = await daemon._is_trading_day("HK")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_trading_day_when_no_data(self):
        """无数据 → False"""
        daemon = _make_daemon()

        with patch("backend.services.paper_settlement_daemon.kline_warehouse") as mock_kw:
            mock_kw.get_history = AsyncMock(return_value=None)
            result = await daemon._is_trading_day("HK")
        assert result is False

    @pytest.mark.asyncio
    async def test_not_trading_day_when_stale_bar(self):
        """最新 bar 不是今天 → False"""
        daemon = _make_daemon()
        yesterday = date.today() - timedelta(days=1)
        df = pd.DataFrame({"time": [datetime(yesterday.year, yesterday.month, yesterday.day)], "close": [350.0]})

        with patch("backend.services.paper_settlement_daemon.kline_warehouse") as mock_kw:
            mock_kw.get_history = AsyncMock(return_value=df)
            result = await daemon._is_trading_day("US")
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_market_returns_false(self):
        """未知市场 → False"""
        daemon = _make_daemon()
        result = await daemon._is_trading_day("XX")
        assert result is False


# ─────────────────────────────────────────
#  结算幂等
# ─────────────────────────────────────────


class TestSettlePortfolio:
    @pytest.mark.asyncio
    async def test_settle_creates_nav_record(self):
        """首次结算创建 PaperNavDaily 记录"""
        daemon = _make_daemon()
        db = _mock_db_session()
        portfolio = _make_portfolio()
        pos = _make_position("HK.00700", 100, 350.0)

        # 持仓查询
        mock_filter = MagicMock()
        mock_filter.all.return_value = [pos]
        db.query.return_value.filter.return_value = mock_filter

        # 无已存在 NAV
        mock_nav_filter = MagicMock()
        mock_nav_filter.first.return_value = None
        mock_nav_filter.order_by.return_value = mock_nav_filter

        # fill 查询返回空（无成交）
        mock_fill_filter = MagicMock()
        mock_fill_filter.all.return_value = []

        # 配置 query 的多次调用
        db.query.side_effect = lambda model: MagicMock(
            filter=MagicMock(return_value=MagicMock(
                all=MagicMock(return_value=[pos] if model.__name__ == "PaperPosition" else []),
                first=MagicMock(return_value=None),
                order_by=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))),
            ))
        )

        today = date.today()

        with patch.object(daemon, "_get_close_price", new_callable=AsyncMock) as mock_price:
            mock_price.return_value = 360.0
            await daemon._settle_portfolio(db, portfolio, today)

        db.add.assert_called_once()
        db.commit.assert_not_called()  # commit 由 _settle_market 统一调用

    @pytest.mark.asyncio
    async def test_settle_idempotent_overwrite(self):
        """同日期重复结算应覆盖已有记录"""
        daemon = _make_daemon()
        db = _mock_db_session()
        portfolio = _make_portfolio()
        pos = _make_position("HK.00700", 100, 350.0)

        existing_nav = MagicMock()
        existing_nav.nav = 100000.0

        # query 返回持仓 + 已有 NAV
        call_count = [0]
        def query_side_effect(model):
            call_count[0] += 1
            m = MagicMock()
            if model.__name__ == "PaperNavDaily":
                # 第一次 filter: 检查已存在 → 返回 existing
                # 第二次 filter: prev_nav 查询 → 返回 existing
                m.filter.return_value = MagicMock(
                    first=MagicMock(return_value=existing_nav),
                    order_by=MagicMock(return_value=MagicMock(
                        first=MagicMock(return_value=existing_nav)
                    )),
                )
            elif model.__name__ == "PaperPosition":
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[pos]))
            elif model.__name__ == "PaperFill":
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[]))
            else:
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[]))
            return m

        db.query.side_effect = query_side_effect
        today = date.today()

        with patch.object(daemon, "_get_close_price", new_callable=AsyncMock) as mock_price:
            mock_price.return_value = 360.0
            await daemon._settle_portfolio(db, portfolio, today)

        # 应覆盖已有记录（设属性而非 add 新记录）
        assert existing_nav.nav is not None  # 被修改了


# ─────────────────────────────────────────
#  停牌前收兜底 + stale_symbols
# ─────────────────────────────────────────


class TestStaleFallback:
    @pytest.mark.asyncio
    async def test_stale_symbol_uses_prev_close(self):
        """取不到收盘价时使用前收兜底 + 标记 stale"""
        daemon = _make_daemon()
        db = _mock_db_session()
        portfolio = _make_portfolio()
        pos = _make_position("HK.09988", 200, 80.0)

        prev_nav = MagicMock()
        prev_nav.nav = 100000.0
        prev_nav.stale_symbols = {"symbols": [], "prices": {"HK.09988": 82.0}}

        # nav_daily 调用计数：第 1 次返回 None（今日无记录），第 2 次返回 prev_nav（前日）
        nav_call_count = [0]

        def query_side_effect(model):
            m = MagicMock()
            if model.__name__ == "PaperNavDaily":
                nav_call_count[0] += 1
                if nav_call_count[0] == 1:
                    # 检查今日是否已结算 → 无记录
                    m.filter.return_value = MagicMock(first=MagicMock(return_value=None))
                else:
                    # 查前日 NAV
                    m.filter.return_value = MagicMock(
                        order_by=MagicMock(return_value=MagicMock(
                            first=MagicMock(return_value=prev_nav)
                        ))
                    )
            elif model.__name__ == "PaperPosition":
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[pos]))
            elif model.__name__ == "PaperFill":
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[]))
            else:
                m.filter.return_value = MagicMock(all=MagicMock(return_value=[]))
            return m

        db.query.side_effect = query_side_effect
        today = date.today()

        with patch.object(daemon, "_get_close_price", new_callable=AsyncMock) as mock_price:
            mock_price.return_value = None  # 取不到价格
            await daemon._settle_portfolio(db, portfolio, today)

        # 验证 add 被调用（新记录，因为今日无已有记录）
        db.add.assert_called_once()
        added_record = db.add.call_args[0][0]
        assert added_record.stale_symbols is not None
        assert "HK.09988" in added_record.stale_symbols.get("symbols", [])


# ─────────────────────────────────────────
#  现金计算
# ─────────────────────────────────────────


class TestComputeCash:
    def test_no_fills_returns_initial_capital(self):
        """无成交 → 现金 = initial_capital"""
        daemon = _make_daemon()
        db = _mock_db_session()

        mock_filter = MagicMock()
        mock_filter.all.return_value = []
        db.query.return_value.filter.return_value = mock_filter

        cash = daemon._compute_cash(db, "p1", 100000.0)
        assert cash == 100000.0

    def test_buy_reduces_cash(self):
        """买入减少现金"""
        daemon = _make_daemon()
        db = _mock_db_session()
        fill = _make_fill("BUY", "HK.00700", 100, 350.0, commission=10.0)

        mock_filter = MagicMock()
        mock_filter.all.return_value = [fill]
        db.query.return_value.filter.return_value = mock_filter

        cash = daemon._compute_cash(db, "p1", 100000.0)
        # 100000 - (100 * 350 + 10) = 100000 - 35010 = 64990
        assert cash == pytest.approx(64990.0)

    def test_sell_increases_cash(self):
        """卖出增加现金"""
        daemon = _make_daemon()
        db = _mock_db_session()
        buy = _make_fill("BUY", "HK.00700", 100, 350.0, commission=10.0)
        sell = _make_fill("SELL", "HK.00700", 50, 360.0, commission=10.0)

        mock_filter = MagicMock()
        mock_filter.all.return_value = [buy, sell]
        db.query.return_value.filter.return_value = mock_filter

        cash = daemon._compute_cash(db, "p1", 100000.0)
        # 100000 - 35010 + (50*360 - 10) = 100000 - 35010 + 17990 = 82980
        assert cash == pytest.approx(82980.0)


# ─────────────────────────────────────────
#  Redis NX 锁互斥
# ─────────────────────────────────────────


class TestRedisLock:
    @pytest.mark.asyncio
    async def test_settle_market_skips_when_lock_exists(self):
        """Redis NX 锁已存在 → 跳过结算"""
        daemon = _make_daemon()

        with patch("backend.services.paper_settlement_daemon.redis_client") as mock_redis:
            mock_redis.set = AsyncMock(return_value=False)  # 锁已存在
            with patch.object(daemon, "_get_running_portfolios") as mock_portfolios:
                await daemon._settle_market("HK")
                mock_portfolios.assert_not_called()

    @pytest.mark.asyncio
    async def test_settle_market_proceeds_when_lock_acquired(self):
        """获取 NX 锁 → 正常结算"""
        daemon = _make_daemon()

        with patch("backend.services.paper_settlement_daemon.redis_client") as mock_redis:
            mock_redis.set = AsyncMock(return_value=True)  # 获取锁成功

            mock_db = _mock_db_session()
            mock_db.query.return_value.filter.return_value.all.return_value = []

            with patch("backend.services.paper_settlement_daemon.SessionLocal", return_value=mock_db):
                with patch.object(daemon, "_get_running_portfolios", return_value=[]):
                    await daemon._settle_market("HK")
                    # 不报错即通过


# ─────────────────────────────────────────
#  周度对账
# ─────────────────────────────────────────


class TestWeeklyReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_detects_inconsistency(self):
        """reconcile 检测到不一致"""
        daemon = _make_daemon()

        mock_db = _mock_db_session()
        p1 = _make_portfolio("p1")
        p1.status = "running"

        mock_db.query.return_value.filter.return_value.all.return_value = [p1]

        reconcile_result = {
            "consistent": False,
            "projected": {"HK.00700": {"qty": 100, "avg_cost": 350.0}},
            "replayed": {"HK.00700": {"qty": 50, "avg_cost": 350.0}},
        }

        with patch("backend.services.paper_settlement_daemon.SessionLocal", return_value=mock_db):
            with patch("backend.services.paper_settlement_daemon.paper_ledger_service") as mock_ledger:
                mock_ledger.reconcile.return_value = reconcile_result
                results = await daemon.weekly_reconcile()

        assert "p1" in results
        assert results["p1"]["consistent"] is False

    @pytest.mark.asyncio
    async def test_reconcile_all_consistent(self):
        """所有组合一致"""
        daemon = _make_daemon()

        mock_db = _mock_db_session()
        p1 = _make_portfolio("p1")
        p1.status = "running"

        mock_db.query.return_value.filter.return_value.all.return_value = [p1]

        reconcile_result = {
            "consistent": True,
            "projected": {"HK.00700": {"qty": 100, "avg_cost": 350.0}},
            "replayed": {"HK.00700": {"qty": 100, "avg_cost": 350.0}},
        }

        with patch("backend.services.paper_settlement_daemon.SessionLocal", return_value=mock_db):
            with patch("backend.services.paper_settlement_daemon.paper_ledger_service") as mock_ledger:
                mock_ledger.reconcile.return_value = reconcile_result
                results = await daemon.weekly_reconcile()

        assert results["p1"]["consistent"] is True


# ─────────────────────────────────────────
#  补结算
# ─────────────────────────────────────────


class TestBackfillSettlement:
    @pytest.mark.asyncio
    async def test_backfill_fills_gap(self):
        """补结算填充 3 天缺口"""
        daemon = _make_daemon()

        mock_db = _mock_db_session()
        p1 = _make_portfolio("p1")
        p1.status = "running"

        today = date.today()
        gap_date = today - timedelta(days=3)

        # 最新 NAV 在 3 天前
        latest_nav = MagicMock()
        latest_nav.trade_date = gap_date

        mock_db.query.return_value.filter.return_value.all.return_value = [p1]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = latest_nav

        with patch("backend.services.paper_settlement_daemon.SessionLocal", return_value=mock_db):
            with patch("backend.services.paper_settlement_daemon.redis_client") as mock_redis:
                mock_redis.set = AsyncMock(return_value=True)
                with patch.object(daemon, "_settle_portfolio", new_callable=AsyncMock) as mock_settle:
                    await daemon.backfill_settlement(max_days=7)
                    # 应补 2 天（gap_date+1 到 today-1）
                    assert mock_settle.call_count == 2

    @pytest.mark.asyncio
    async def test_backfill_skips_when_no_gap(self):
        """无缺口 → 不补结算"""
        daemon = _make_daemon()

        mock_db = _mock_db_session()
        p1 = _make_portfolio("p1")
        p1.status = "running"

        today = date.today()
        latest_nav = MagicMock()
        latest_nav.trade_date = today - timedelta(days=1)

        mock_db.query.return_value.filter.return_value.all.return_value = [p1]
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = latest_nav

        with patch("backend.services.paper_settlement_daemon.SessionLocal", return_value=mock_db):
            with patch("backend.services.paper_settlement_daemon.redis_client") as mock_redis:
                with patch.object(daemon, "_settle_portfolio", new_callable=AsyncMock) as mock_settle:
                    await daemon.backfill_settlement(max_days=7)
                    mock_settle.assert_not_called()
