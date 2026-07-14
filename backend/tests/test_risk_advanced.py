"""
RISK-01~08 进阶风控能力测试
覆盖: risk_sector / risk_cvar / risk_liquidity / risk_attribution / risk_stress
      + risk_engine RISK-03/07/08 扩展
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import numpy as np

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── 辅助数据 ──────────────────────────────────────────────────────────────


def make_closes(n=60, base=100.0, seed=42):
    """生成模拟收盘价序列"""
    rng = np.random.RandomState(seed)
    returns = rng.normal(0.001, 0.02, n)
    prices = base * np.exp(np.cumsum(returns))
    return prices.tolist()


SAMPLE_POSITIONS = [
    {"code": "HK.00700", "market_val": 50000.0, "position_side": "LONG"},
    {"code": "HK.09988", "market_val": 30000.0, "position_side": "LONG"},
    {"code": "HK.00005", "market_val": 20000.0, "position_side": "LONG"},
]

SAMPLE_KLINE = {
    "HK.00700": make_closes(60, 350, seed=1),
    "HK.09988": make_closes(60, 150, seed=2),
    "HK.00005": make_closes(60, 60, seed=3),
}


# ═══════════════════════════════════════════════════════════════════════════
# RISK-03: 相关性矩阵
# ═══════════════════════════════════════════════════════════════════════════


class TestCorrelationMatrix:
    """RISK-03 相关性矩阵测试"""

    def test_known_correlation(self):
        """已知相关系数矩阵"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        # 两组高度相关的序列
        kline_data = {
            "A": make_closes(60, 100, seed=10),
            "B": make_closes(60, 100, seed=10),  # 同 seed → 完全相同
        }
        result = engine._calc_correlation_matrix(kline_data)

        assert len(result["labels"]) == 2
        assert result["matrix"][0][0] == 1.0  # 对角线 = 1
        assert result["matrix"][1][1] == 1.0
        # 同 seed → 相关系数 = 1.0
        assert abs(result["matrix"][0][1] - 1.0) < 0.01

    def test_single_position(self):
        """单持仓返回 1x1 矩阵"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        kline_data = {"A": make_closes(60, 100, seed=1)}
        result = engine._calc_correlation_matrix(kline_data)

        assert result["labels"] == ["A"]
        assert result["matrix"] == [[1.0]]
        assert result["warnings"] == []

    def test_high_correlation_warning(self):
        """高相关性预警"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        # 用不同但接近的 seed 产生高相关序列
        base = make_closes(60, 100, seed=42)
        noisy = [p * (1 + np.random.RandomState(99).normal(0, 0.001)) for p in base]
        kline_data = {"A": base, "B": noisy}
        result = engine._calc_correlation_matrix(kline_data)

        # 高相关 → 应有预警
        assert len(result["warnings"]) >= 1
        assert result["warnings"][0]["val"] > 0.8


# ═══════════════════════════════════════════════════════════════════════════
# RISK-07: 风险雷达真实数据
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskRadarReal:
    """RISK-07 雷达增强测试"""

    def test_radar_with_real_data(self):
        """有 K 线数据时雷达分数非占位值"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 0.8, "vol": 0.25, "var_95": -0.02, "sharpe": 1.2}
        max_dd = -10.0

        result = engine._build_risk_radar(metrics, max_dd, SAMPLE_KLINE)

        axes = {r["axis"]: r["current"] for r in result}
        # Liq/Corr/Mom 不再是硬编码 72/58/81
        # 有 kline_data 时应为计算值
        assert "Liq" in axes
        assert "Corr" in axes
        assert "Mom" in axes
        # 有数据时值在 0-100 范围
        for val in axes.values():
            assert 0 <= val <= 100

    def test_radar_fallback_without_data(self):
        """无 K 线数据时降级为默认中位值"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()
        metrics = {"beta": 0.5, "vol": 0.1, "var_95": -0.01, "sharpe": 1.5}
        max_dd = -5.0

        result = engine._build_risk_radar(metrics, max_dd)

        axes = {r["axis"]: r["current"] for r in result}
        # 无 kline_data → Liq/Corr/Mom 默认 50
        assert axes["Liq"] == 50
        assert axes["Corr"] == 50
        assert axes["Mom"] == 50


# ═══════════════════════════════════════════════════════════════════════════
# RISK-08: Beta 基准
# ═══════════════════════════════════════════════════════════════════════════


class TestBetaBenchmark:
    """RISK-08 Beta 基准测试"""

    @patch("backend.services.risk_engine.kline_warehouse")
    @patch("backend.services.risk_engine.futu_service")
    def test_beta_real_benchmark(self, mock_futu, mock_warehouse):
        """有基准数据时 beta 非 0.85"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()

        # Mock futu_service.get_history 返回持仓 K 线
        async def mock_history(ticker, ktype="K_DAY", num=60):
            return {
                "status": "success",
                "data": [{"close": p} for p in make_closes(60, 100, seed=hash(ticker) % 100)],
            }

        mock_futu.get_history = AsyncMock(side_effect=mock_history)

        # Mock kline_warehouse 返回基准 K 线
        import pandas as pd

        bench_df = pd.DataFrame({"close": make_closes(60, 3000, seed=77)})
        mock_warehouse.get_history = AsyncMock(return_value=bench_df)

        positions = [
            {"code": "HK.00700", "market_val": 50000.0},
            {"code": "HK.09988", "market_val": 30000.0},
        ]
        result, kline_data = asyncio.run(engine._calc_risk_metrics(positions, "HK"))

        # beta 不应等于旧占位值 0.85
        assert result["beta"] != 0.85
        # beta 应为有限数
        assert np.isfinite(result["beta"])

    @patch("backend.services.risk_engine.kline_warehouse")
    @patch("backend.services.risk_engine.futu_service")
    def test_beta_fallback_on_no_benchmark(self, mock_futu, mock_warehouse):
        """基准数据缺失时 beta=0"""
        from backend.services.risk_engine import RiskEngine

        engine = RiskEngine()

        async def mock_history(ticker, ktype="K_DAY", num=60):
            return {
                "status": "success",
                "data": [{"close": p} for p in make_closes(60, 100, seed=42)],
            }

        mock_futu.get_history = AsyncMock(side_effect=mock_history)
        mock_warehouse.get_history = AsyncMock(return_value=None)

        positions = [{"code": "HK.00700", "market_val": 50000.0}]
        result, _ = asyncio.run(engine._calc_risk_metrics(positions, "HK"))

        assert result["beta"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# RISK-01: 板块暴露
# ═══════════════════════════════════════════════════════════════════════════


class TestSectorExposure:
    """RISK-01 板块暴露测试"""

    @patch("backend.services.risk_sector.redis_client")
    def test_sector_aggregation(self, mock_redis):
        """板块聚合正确"""
        from backend.services.risk_sector import SectorAnalyzer

        mock_redis.get = AsyncMock(return_value=json.dumps({
            "HK.00700": "Technology",
            "HK.09988": "Technology",
            "HK.00005": "Financials",
        }))

        analyzer = SectorAnalyzer()
        positions = SAMPLE_POSITIONS
        result = asyncio.run(analyzer.get_sector_exposure(positions, "HK"))

        sectors = result["sectors"]
        assert len(sectors) == 2
        # 科技板块市值最高
        assert sectors[0]["sector"] == "科技"
        assert sectors[0]["pct"] > 0

    @patch("backend.services.risk_sector.redis_client")
    def test_sector_empty_positions(self, mock_redis):
        """空持仓返回空列表"""
        from backend.services.risk_sector import SectorAnalyzer

        analyzer = SectorAnalyzer()
        result = asyncio.run(analyzer.get_sector_exposure([], "HK"))
        assert result["sectors"] == []


# ═══════════════════════════════════════════════════════════════════════════
# RISK-05: CVaR 分解
# ═══════════════════════════════════════════════════════════════════════════


class TestCVaR:
    """RISK-05 CVaR 测试"""

    def test_known_cvar(self):
        """已知 CVaR 值"""
        from backend.services.risk_cvar import calc_cvar

        # 标准正态分布 → CVaR(5%) ≈ -2.06
        returns = np.random.RandomState(42).normal(0, 1, 10000)
        cvar = calc_cvar(returns, alpha=0.05)
        assert cvar < -1.5  # 应显著为负

    def test_cvar_empty(self):
        """空序列返回 0"""
        from backend.services.risk_cvar import calc_cvar

        assert calc_cvar(np.array([])) == 0.0
        assert calc_cvar(np.array([0.01])) == 0.0

    def test_decompose_cvar(self):
        """CVaR 分解结构正确"""
        from backend.services.risk_cvar import decompose_cvar

        positions = [
            {"code": "A", "market_val": 60000.0},
            {"code": "B", "market_val": 40000.0},
        ]
        kline_data = {
            "A": make_closes(60, 100, seed=1),
            "B": make_closes(60, 50, seed=2),
        }
        result = decompose_cvar(positions, kline_data)

        assert "portfolio_cvar" in result
        assert "var_threshold" in result
        assert len(result["decompositions"]) == 2
        # 权重之和 = 1
        total_w = sum(d["weight"] for d in result["decompositions"])
        assert abs(total_w - 1.0) < 0.01

    def test_decompose_cvar_empty(self):
        """空持仓返回空分解"""
        from backend.services.risk_cvar import decompose_cvar

        result = decompose_cvar([], {})
        assert result["portfolio_cvar"] == 0.0
        assert result["decompositions"] == []


# ═══════════════════════════════════════════════════════════════════════════
# RISK-06: 流动性风险
# ═══════════════════════════════════════════════════════════════════════════


class TestLiquidity:
    """RISK-06 流动性风险测试"""

    def test_high_liquidity(self):
        """高流动性标的"""
        from backend.services.risk_liquidity import LiquidityAssessor

        assessor = LiquidityAssessor()
        # 高波动 → 高流动性代理
        kline_data = {"A": make_closes(60, 100, seed=42)}
        positions = [{"code": "A", "market_val": 10000.0}]
        result = assessor.assess(positions, kline_data, total_nav=100000.0)

        assert len(result["assessments"]) == 1
        assert result["assessments"][0]["score"] > 0
        # 占比 10% → 不应触发大额预警
        assert all("大额" not in w["reason"] for w in result["warnings"])

    def test_large_position_warning(self):
        """大额持仓预警"""
        from backend.services.risk_liquidity import LiquidityAssessor

        assessor = LiquidityAssessor()
        kline_data = {"A": make_closes(60, 100, seed=42)}
        # 持仓占 NAV 50% → 触发大额预警
        positions = [{"code": "A", "market_val": 50000.0}]
        result = assessor.assess(positions, kline_data, total_nav=100000.0)

        large_warnings = [w for w in result["warnings"] if "大额" in w["reason"]]
        assert len(large_warnings) >= 1

    def test_empty_positions(self):
        """空持仓"""
        from backend.services.risk_liquidity import LiquidityAssessor

        assessor = LiquidityAssessor()
        result = assessor.assess([], {})
        assert result["assessments"] == []
        assert result["portfolio_score"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# RISK-02: Beta/Alpha 归因
# ═══════════════════════════════════════════════════════════════════════════


class TestAttribution:
    """RISK-02 归因测试"""

    def test_known_attribution(self):
        """已知归因结果"""
        from backend.services.risk_attribution import calc_attribution

        rng = np.random.RandomState(42)
        benchmark = rng.normal(0.001, 0.02, 100)
        # 组合 = 1.2 * 基准 + 小 alpha
        portfolio = 1.2 * benchmark + 0.0005 + rng.normal(0, 0.005, 100)

        result = calc_attribution(portfolio, benchmark)

        assert abs(result["beta"] - 1.2) < 0.3  # beta 应接近 1.2
        assert result["r_squared"] > 0.5  # 拟合优度应较高
        assert "attribution" in result

    def test_zero_beta(self):
        """零 beta (组合与基准无关)"""
        from backend.services.risk_attribution import calc_attribution

        rng = np.random.RandomState(42)
        benchmark = rng.normal(0.001, 0.02, 100)
        portfolio = rng.normal(0.001, 0.02, 100)  # 独立随机

        result = calc_attribution(portfolio, benchmark)

        # beta 应接近 0 (但不必精确)
        assert abs(result["beta"]) < 0.5

    def test_empty_data(self):
        """空数据返回零值"""
        from backend.services.risk_attribution import calc_attribution

        result = calc_attribution(np.array([]), np.array([]))
        assert result["alpha"] == 0.0
        assert result["beta"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# RISK-04: 压力测试
# ═══════════════════════════════════════════════════════════════════════════


class TestStressTest:
    """RISK-04 压力测试"""

    def test_historical_scenario(self):
        """历史情景"""
        from backend.services.risk_stress import StressTester

        tester = StressTester()
        result = tester.run_stress(SAMPLE_POSITIONS, SAMPLE_KLINE, "2008_crash")

        assert result["scenario"] == "2008_crash"
        assert result["type"] == "historical"
        assert result["nav_before"] > 0
        assert result["change_pct"] < 0  # 危机 → 亏损

    def test_hypothetical_scenario(self):
        """假设情景"""
        from backend.services.risk_stress import StressTester

        tester = StressTester()
        result = tester.run_stress(
            SAMPLE_POSITIONS, SAMPLE_KLINE, "vol_double", market="HK"
        )

        assert result["type"] == "hypothetical"
        assert result["change_pct"] < 0  # 波动率翻倍 → 亏损

    def test_empty_positions(self):
        """空持仓"""
        from backend.services.risk_stress import StressTester

        tester = StressTester()
        result = tester.run_stress([], {}, "2008_crash")
        assert result["nav_before"] == 0

    def test_unknown_scenario(self):
        """未知情景"""
        from backend.services.risk_stress import StressTester

        tester = StressTester()
        result = tester.run_stress(SAMPLE_POSITIONS, SAMPLE_KLINE, "unknown_event")
        assert "未知" in result["desc"]

    def test_list_scenarios(self):
        """列出所有情景"""
        from backend.services.risk_stress import StressTester

        tester = StressTester()
        result = tester.list_scenarios()
        assert len(result["historical"]) == 3
        assert len(result["hypothetical"]) == 3
