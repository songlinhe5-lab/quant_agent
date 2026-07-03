"""
Risk Engine 单元测试
覆盖: backend/services/risk_engine.py
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── RiskEngine 单元测试 ───────────────────────────────────────────────────────
class TestRiskEngine:
    """RiskEngine 核心逻辑测试"""

    def test_risk_engine_singleton(self):
        """RiskEngine 单例模式"""
        from backend.services.risk_engine import RiskEngine

        engine1 = RiskEngine()
        engine2 = RiskEngine()
        assert engine1 is engine2

    def test_calc_kpi(self):
        """KPI 计算"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        positions = [
            {"pl_val": 1000.0},
            {"pl_val": -500.0},
        ]

        result = engine._calc_kpi(
            total_assets=100000.0,
            cash=50000.0,
            market_val=50000.0,
            positions=positions,
            currency="HKD",
        )

        assert result["nav"] == 100000.0
        assert result["today_pl"] == 500.0  # 1000 + (-500)
        assert result["cash"] == 50000.0
        assert result["leverage"] == 50.0  # 50000/100000 * 100
        assert result["currency"] == "HKD"
        assert "HK$" in result["nav_fmt"]

    def test_calc_kpi_usd_currency(self):
        """USD 货币符号"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._calc_kpi(100000.0, 50000.0, 50000.0, [], "USD")

        assert "$" in result["nav_fmt"]
        assert result["currency"] == "USD"

    def test_calc_kpi_zero_assets(self):
        """零资产时杠杆为 0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._calc_kpi(0.0, 0.0, 0.0, [])

        assert result["leverage"] == 0
        assert result["today_pl_pct"] == 0

    def test_calc_exposure(self):
        """敞口分布计算"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        positions = [
            {"market_val": 30000.0, "position_side": "LONG"},
            {"market_val": 10000.0, "position_side": "SHORT"},
        ]

        result = engine._calc_exposure(
            total_assets=100000.0,
            cash=60000.0,
            market_val=40000.0,
            positions=positions,
        )

        assert len(result) == 3
        assert result[0]["name"] == "多头"
        assert result[0]["value"] == 30000.0
        assert result[0]["pct"] == 30.0
        assert result[1]["name"] == "空头"
        assert result[1]["value"] == 10000.0
        assert result[1]["pct"] == 10.0
        assert result[2]["name"] == "现金"
        assert result[2]["value"] == 60000.0
        assert result[2]["pct"] == 60.0

    def test_calc_exposure_zero_assets(self):
        """零资产时敞口百分比为 0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._calc_exposure(0.0, 0.0, 0.0, [])

        assert all(item["pct"] == 0 for item in result)

    def test_calc_max_dd_from_snapshots(self):
        """最大回撤计算"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        snapshots = [
            {"ts": 1, "nav": 100.0},
            {"ts": 2, "nav": 110.0},
            {"ts": 3, "nav": 95.0},
            {"ts": 4, "nav": 105.0},
            {"ts": 5, "nav": 90.0},
        ]

        result = engine._calc_max_dd_from_snapshots(snapshots)

        # 峰值 110，最低 90，回撤 = (110-90)/110 = 18.18%
        expected_dd = -(20.0 / 110.0) * 100
        assert abs(result - expected_dd) < 0.01

    def test_calc_max_dd_from_snapshots_empty(self):
        """空快照返回 0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._calc_max_dd_from_snapshots([])
        assert result == 0.0

    def test_calc_max_dd_from_snapshots_single(self):
        """单条快照返回 0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._calc_max_dd_from_snapshots([{"ts": 1, "nav": 100.0}])
        assert result == 0.0

    def test_calc_max_dd_no_drawdown(self):
        """无回撤时为 0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        snapshots = [
            {"ts": 1, "nav": 100.0},
            {"ts": 2, "nav": 105.0},
            {"ts": 3, "nav": 110.0},
        ]

        result = engine._calc_max_dd_from_snapshots(snapshots)
        assert result == 0.0

    def test_build_risk_radar(self):
        """六维风险雷达构建"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 0.85, "vol": 0.25, "var_95": -0.02, "sharpe": 1.2}
        max_dd = -15.0

        result = engine._build_risk_radar(metrics, max_dd)

        assert len(result) == 6
        axes = [r["axis"] for r in result]
        assert "Beta" in axes
        assert "Vol" in axes
        assert "DD" in axes

        # 检查 DD 维度: -15% → 75 分
        dd_item = next(r for r in result if r["axis"] == "DD")
        assert dd_item["current"] == 75.0

    def test_build_risk_factors(self):
        """因子监控构建"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 0.85, "var_95": -0.02, "sharpe": 1.8}
        max_dd = -5.0

        result = engine._build_risk_factors(metrics, max_dd)

        assert len(result) == 4
        labels = [r["label"] for r in result]
        assert "Market Beta" in labels
        assert "VaR (95%)" in labels
        assert "Sharpe" in labels
        assert "Max DD" in labels

        # Beta < 1.0 → safe
        beta_item = next(r for r in result if r["label"] == "Market Beta")
        assert beta_item["status"] == "safe"

        # Sharpe > 1.5 → good
        sharpe_item = next(r for r in result if r["label"] == "Sharpe")
        assert sharpe_item["status"] == "good"

        # Max DD > -10 → safe
        dd_item = next(r for r in result if r["label"] == "Max DD")
        assert dd_item["status"] == "safe"

    def test_build_risk_factors_warn_status(self):
        """因子监控 warn 状态"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 1.2, "var_95": -0.25, "sharpe": 1.2}
        max_dd = -12.0

        result = engine._build_risk_factors(metrics, max_dd)

        # Beta >= 1.0 → warn
        beta_item = next(r for r in result if r["label"] == "Market Beta")
        assert beta_item["status"] == "warn"

        # Max DD between -10 and -15 → warn
        dd_item = next(r for r in result if r["label"] == "Max DD")
        assert dd_item["status"] == "warn"

    def test_build_risk_factors_crit_status(self):
        """因子监控 crit 状态"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 1.5, "var_95": -0.5, "sharpe": 0.5}
        max_dd = -20.0

        result = engine._build_risk_factors(metrics, max_dd)

        # Max DD < -15 → crit
        dd_item = next(r for r in result if r["label"] == "Max DD")
        assert dd_item["status"] == "crit"

        # Sharpe < 1.0 → crit
        sharpe_item = next(r for r in result if r["label"] == "Sharpe")
        assert sharpe_item["status"] == "crit"

    def test_fallback_data(self):
        """降级数据格式"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        result = engine._fallback_data("测试降级")

        assert result["status"] == "error"
        assert result["message"] == "测试降级"
        assert result["kpi"]["nav"] == 0
        assert result["exposure"] == []
        assert result["risk_radar"] == []
        assert result["risk_factors"] == []
        assert result["positions"] == []
        assert "ts" in result

    @patch("backend.services.risk_engine.redis_client")
    def test_get_portfolio_risk_cached(self, mock_redis):
        """缓存命中时直接返回"""
        from backend.services.risk_engine import RiskEngine

        cached_data = {"status": "success", "accounts": {"HK": {}}}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        engine = RiskEngine()

        result = asyncio.run(engine.get_portfolio_risk(days=1))

        assert result["status"] == "success"
        assert "HK" in result["accounts"]

    @patch("backend.services.risk_engine.futu_service")
    @patch("backend.services.risk_engine.redis_client")
    def test_get_portfolio_risk_both_fail(self, mock_redis, mock_futu):
        """两个市场都失败时返回降级数据"""
        from backend.services.risk_engine import RiskEngine

        mock_redis.get = AsyncMock(return_value=None)
        mock_futu.get_account_info = AsyncMock(return_value={"status": "error", "message": "Connection failed"})

        engine = RiskEngine()

        result = asyncio.run(engine.get_portfolio_risk(days=1))

        assert result["status"] == "error"
        assert "均获取失败" in result["message"]

    @patch("backend.services.risk_engine.redis_client")
    def test_get_nav_snapshots_redis(self, mock_redis):
        """days=1 时从 Redis 读取"""
        from backend.services.risk_engine import RiskEngine

        snapshots = [
            json.dumps({"ts": 1719500000.0, "nav": 100000.0}),
            json.dumps({"ts": 1719500300.0, "nav": 100500.0}),
        ]
        mock_redis.lrange = AsyncMock(return_value=snapshots)

        engine = RiskEngine()

        result = asyncio.run(engine._get_nav_snapshots("HK", days=1))

        assert len(result) == 2
        assert result[0]["nav"] == 100000.0
        assert result[1]["nav"] == 100500.0

    @patch("backend.services.risk_engine.redis_client")
    def test_get_nav_snapshots_redis_empty(self, mock_redis):
        """Redis 无数据时返回空列表"""
        from backend.services.risk_engine import RiskEngine

        mock_redis.lrange = AsyncMock(return_value=[])

        engine = RiskEngine()

        result = asyncio.run(engine._get_nav_snapshots("HK", days=1))
        assert result == []

    @patch("backend.services.risk_engine.redis_client")
    def test_calc_risk_metrics_empty_positions(self, mock_redis):
        """空持仓时返回零值"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()

        result = asyncio.run(engine._calc_risk_metrics([]))

        assert result["vol"] == 0
        assert result["var_95"] == 0
        assert result["beta"] == 0
        assert result["sharpe"] == 0
