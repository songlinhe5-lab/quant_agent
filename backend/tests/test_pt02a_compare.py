"""
PT-02a: 对比 API 测试
======================
覆盖: 序号对齐 / TE 计算一致 / benchmark 双轨切换
"""
from datetime import date
from unittest.mock import MagicMock, patch

from backend.routers.paper import get_compare, get_nav_series

# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


def _mock_db():
    return MagicMock()


def _make_nav_rows(n: int, start_nav: float = 100000.0, daily_pct: float = 0.001):
    """生成 n 天的 NAV 数据"""
    rows = []
    nav = start_nav
    for i in range(n):
        d = date(2026, 7, 1 + i) if 1 + i <= 28 else date(2026, 8, 1 + i - 31)
        rows.append({
            "portfolio_id": "p1",
            "trade_date": d.isoformat(),
            "nav": nav,
            "cash": nav * 0.5,
            "market_value": nav * 0.5,
            "daily_return": daily_pct if i > 0 else 0.0,
            "stale_symbols": None,
        })
        nav *= (1 + daily_pct)
    return rows


# ─────────────────────────────────────────
#  NAV 序列端点
# ─────────────────────────────────────────


class TestNavEndpoint:
    def test_nav_returns_data(self):
        """NAV 端点返回净值序列"""
        db = _mock_db()
        nav_rows = _make_nav_rows(10)

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = nav_rows
            result = get_nav_series("p1", days=30, db=db)

        assert result["status"] == "success"
        assert len(result["data"]) == 10

    def test_nav_empty(self):
        """无数据返回空列表"""
        db = _mock_db()

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = []
            result = get_nav_series("p1", days=30, db=db)

        assert result["status"] == "success"
        assert result["data"] == []


# ─────────────────────────────────────────
#  对比端点
# ─────────────────────────────────────────


class TestCompareEndpoint:
    def test_compare_no_data(self):
        """无净值数据 → error"""
        db = _mock_db()

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = []
            result = get_compare("p1", days=30, db=db)

        assert result["status"] == "error"

    def test_compare_returns_structure(self):
        """有数据 → 返回完整结构"""
        db = _mock_db()
        nav_rows = _make_nav_rows(10)

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = nav_rows
            mock_ledger.get_portfolio.return_value = {
                "id": "p1",
                "benchmark_backtest_ref": None,
            }
            result = get_compare("p1", days=30, db=db)

        assert result["status"] == "success"
        data = result["data"]
        assert "tracking_error" in data
        assert "cumulative_drift" in data
        assert "chart" in data
        assert "paper_sharpe" in data
        assert "paper_max_dd" in data
        assert len(data["chart"]) == 10

    def test_compare_chart_has_paper_and_benchmark(self):
        """图表数据包含 paper 和 benchmark 列"""
        db = _mock_db()
        nav_rows = _make_nav_rows(5)

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = nav_rows
            mock_ledger.get_portfolio.return_value = {
                "id": "p1",
                "benchmark_backtest_ref": None,
            }
            result = get_compare("p1", days=30, db=db)

        chart = result["data"]["chart"]
        for point in chart:
            assert "paper" in point
            assert "benchmark" in point

    def test_compare_te_with_identical_data(self):
        """相同数据 → TE 为 0（无 benchmark 时 benchmark 全 0）"""
        db = _mock_db()
        # 生成固定 NAV（无波动 → TE = 0）
        nav_rows = _make_nav_rows(10, daily_pct=0.0)

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = nav_rows
            mock_ledger.get_portfolio.return_value = {
                "id": "p1",
                "benchmark_backtest_ref": None,
            }
            result = get_compare("p1", days=30, db=db)

        # 无波动时 TE 为 0
        assert result["data"]["tracking_error"] == 0.0

    def test_compare_with_benchmark_ref(self):
        """有 benchmark ref 时仍正常返回"""
        db = _mock_db()
        nav_rows = _make_nav_rows(10)

        with patch("backend.routers.paper.paper_ledger_service") as mock_ledger:
            mock_ledger.get_nav_daily.return_value = nav_rows
            mock_ledger.get_portfolio.return_value = {
                "id": "p1",
                "benchmark_backtest_ref": "bt_ref_001",
            }
            # _load_benchmark_nav 返回 None（Redis 未命中）
            result = get_compare("p1", days=30, db=db)

        assert result["status"] == "success"
        # benchmark 降级为全 0
        for point in result["data"]["chart"]:
            assert point["benchmark"] == 0.0
