"""
Options / Risk / Portfolio 路由覆盖率补充测试
覆盖: backend/routers/options.py, risk.py, portfolio.py
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.routers.options import router as options_router
from backend.routers.portfolio import router as portfolio_router
from backend.routers.risk import router as risk_router

app = FastAPI()
app.include_router(options_router)
app.include_router(risk_router)
app.include_router(portfolio_router)
client = TestClient(app, raise_server_exceptions=False)


# ==========================================
# Options Router
# ==========================================
class TestOptionGreeks:
    @patch("backend.routers.options.market_data")
    def test_greeks_success(self, mock_md):
        mock_md.get_option_chain = AsyncMock(
            return_value={
                "status": "success",
                "options": [
                    {
                        "strike": 150,
                        "type": "CALL",
                        "iv": 30,
                        "volume": 100,
                        "open_interest": 500,
                        "last_price": 5.0,
                        "expiry": "2026-08-01",
                    },
                ],
            }
        )
        mock_md.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
        resp = client.get("/options/greeks/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.options.market_data")
    def test_greeks_chain_fail(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "error", "message": "不支持"})
        resp = client.get("/options/greeks/US.AAPL")
        assert resp.status_code == 404

    @patch("backend.routers.options.market_data")
    def test_greeks_no_spot(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "success", "options": []})
        mock_md.get_quote = AsyncMock(return_value={"status": "error"})
        resp = client.get("/options/greeks/US.AAPL")
        assert resp.status_code == 404

    @patch("backend.routers.options.market_data")
    def test_greeks_empty_options(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "success", "options": []})
        mock_md.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
        resp = client.get("/options/greeks/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["options"] == []


class TestOptionScreen:
    @patch("backend.routers.options.options_screener")
    @patch("backend.routers.options.market_data")
    def test_screen_success(self, mock_md, mock_screener):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "success", "options": [{"strike": 150}]})
        mock_md.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
        mock_screener.screen_options = AsyncMock(return_value={"filtered": [], "count": 0})
        resp = client.post("/options/screen", json={"ticker": "US.AAPL"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.options.market_data")
    def test_screen_chain_fail(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "error"})
        resp = client.post("/options/screen", json={"ticker": "US.AAPL"})
        assert resp.status_code == 404


class TestVolSmile:
    @patch("backend.routers.options.options_screener")
    @patch("backend.routers.options.market_data")
    def test_vol_smile_success(self, mock_md, mock_screener):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "success", "options": [{"strike": 150}]})
        mock_md.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
        mock_screener.analyze_vol_smile = AsyncMock(return_value={"smile": []})
        resp = client.get("/options/vol-smile/US.AAPL")
        assert resp.status_code == 200

    @patch("backend.routers.options.market_data")
    def test_vol_smile_fail(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "error"})
        resp = client.get("/options/vol-smile/US.AAPL")
        assert resp.status_code == 404


class TestIVRank:
    @patch("backend.routers.options.options_screener")
    @patch("backend.routers.options.market_data")
    def test_iv_rank_success(self, mock_md, mock_screener):
        mock_md.get_option_chain = AsyncMock(
            return_value={
                "status": "success",
                "options": [
                    {
                        "strike": 150,
                        "type": "CALL",
                        "iv": 30,
                        "volume": 100,
                        "open_interest": 500,
                        "last_price": 5.0,
                        "expiry": "2026-08-01",
                    },
                ],
            }
        )
        mock_md.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
        mock_screener.get_iv_rank_analysis = AsyncMock(return_value={"iv_rank": 50, "iv_percentile": 45})
        resp = client.get("/options/iv-rank/US.AAPL")
        assert resp.status_code == 200

    @patch("backend.routers.options.market_data")
    def test_iv_rank_chain_fail(self, mock_md):
        mock_md.get_option_chain = AsyncMock(return_value={"status": "error"})
        resp = client.get("/options/iv-rank/US.AAPL")
        assert resp.status_code == 404


# ==========================================
# Risk Router
# ==========================================
class TestRiskDashboard:
    @patch("backend.routers.risk.risk_engine")
    def test_dashboard_success(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "success", "accounts": {}})
        resp = client.get("/risk/dashboard")
        assert resp.status_code == 200

    @patch("backend.routers.risk.risk_engine")
    def test_dashboard_error(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "error", "message": "系统异常"})
        resp = client.get("/risk/dashboard")
        assert resp.status_code == 500

    @patch("backend.routers.risk.risk_engine")
    def test_dashboard_empty(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "empty", "accounts": {}})
        resp = client.get("/risk/dashboard")
        assert resp.status_code == 200


class TestPositionsBreakdown:
    @patch("backend.routers.risk.risk_engine")
    def test_breakdown_success(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(
            return_value={
                "status": "success",
                "accounts": {"HK": {"positions": [{"code": "00700"}]}},
                "ts": 123,
            }
        )
        resp = client.get("/risk/positions-breakdown")
        assert resp.status_code == 200
        assert len(resp.json()["positions"]) == 1

    @patch("backend.routers.risk.risk_engine")
    def test_breakdown_error(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "error", "message": "fail"})
        resp = client.get("/risk/positions-breakdown")
        assert resp.status_code == 500


class TestSectorExposure:
    @patch("backend.routers.risk._get_market_data")
    def test_no_positions(self, mock_gmd):
        mock_gmd.return_value = (None, None, None)
        resp = client.get("/risk/sector-exposure?market=HK")
        assert resp.status_code == 200
        assert resp.json()["sectors"] == []

    @patch("backend.routers.risk.sector_analyzer")
    @patch("backend.routers.risk._get_market_data")
    def test_with_positions(self, mock_gmd, mock_sa):
        mock_gmd.return_value = ([{"code": "00700"}], {}, 100000)
        mock_sa.get_sector_exposure = AsyncMock(return_value={"sectors": [{"name": "Tech"}]})
        resp = client.get("/risk/sector-exposure?market=HK")
        assert resp.status_code == 200


class TestCorrelation:
    @patch("backend.routers.risk.risk_engine")
    def test_correlation_empty(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "success", "accounts": {}})
        resp = client.get("/risk/correlation?market=HK")
        assert resp.status_code == 200
        assert resp.json()["labels"] == []

    @patch("backend.routers.risk.risk_engine")
    def test_correlation_error(self, mock_engine):
        mock_engine.get_portfolio_risk = AsyncMock(return_value={"status": "error", "message": "fail"})
        resp = client.get("/risk/correlation?market=HK")
        assert resp.status_code == 500


class TestCVaR:
    @patch("backend.routers.risk._get_market_data")
    def test_cvar_no_data(self, mock_gmd):
        mock_gmd.return_value = (None, None, None)
        resp = client.get("/risk/cvar?market=HK")
        assert resp.status_code == 200
        assert resp.json()["portfolio_cvar"] == 0.0


class TestLiquidity:
    @patch("backend.routers.risk._get_market_data")
    def test_liquidity_no_data(self, mock_gmd):
        mock_gmd.return_value = (None, None, None)
        resp = client.get("/risk/liquidity?market=HK")
        assert resp.status_code == 200
        assert resp.json()["assessments"] == []


class TestAttribution:
    @patch("backend.routers.risk._get_market_data")
    def test_attribution_no_data(self, mock_gmd):
        mock_gmd.return_value = (None, None, None)
        resp = client.get("/risk/attribution?market=HK")
        assert resp.status_code == 200
        assert resp.json()["alpha"] == 0.0


class TestStressTest:
    @patch("backend.routers.risk._get_market_data")
    @patch("backend.routers.risk.stress_tester")
    def test_stress_no_data(self, mock_st, mock_gmd):
        mock_gmd.return_value = (None, None, None)
        mock_st._empty_result.return_value = {"scenario": "crisis", "impact": 0}
        resp = client.post("/risk/stress-test", json={"scenario": "crisis", "market": "HK"})
        assert resp.status_code == 200

    @patch("backend.routers.risk.stress_tester")
    def test_scenarios(self, mock_st):
        mock_st.list_scenarios.return_value = [{"name": "crisis"}, {"name": "rate_hike"}]
        resp = client.get("/risk/stress-test/scenarios")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ==========================================
# Portfolio Router
# ==========================================
class TestPortfolioOptimize:
    def test_optimize_too_few_symbols(self):
        resp = client.post("/portfolio/optimize", json={"symbols": ["AAPL"]})
        assert resp.status_code == 400

    @patch("backend.routers.portfolio._fetch_returns")
    @patch("backend.routers.portfolio.portfolio_optimizer")
    def test_optimize_equal_weight(self, mock_opt, mock_fetch):
        import pandas as pd

        mock_fetch.return_value = pd.DataFrame({"AAPL": [0.01, -0.005, 0.002], "MSFT": [0.008, -0.003, 0.001]})
        resp = client.post(
            "/portfolio/optimize",
            json={"symbols": ["AAPL", "MSFT"], "model": "equal_weight"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.portfolio._fetch_returns")
    @patch("backend.routers.portfolio.portfolio_optimizer")
    def test_optimize_markowitz(self, mock_opt, mock_fetch):
        import pandas as pd

        mock_fetch.return_value = pd.DataFrame({"AAPL": [0.01, -0.005], "MSFT": [0.008, -0.003]})
        mock_result = MagicMock()
        mock_result.weights = [0.5, 0.5]
        mock_result.expected_return = 0.1
        mock_result.expected_volatility = 0.15
        mock_result.sharpe_ratio = 0.67
        mock_result.risk_contributions = [0.5, 0.5]
        mock_result.effective_n = 2.0
        mock_opt.mean_variance.return_value = mock_result
        resp = client.post(
            "/portfolio/optimize",
            json={"symbols": ["AAPL", "MSFT"], "model": "markowitz"},
        )
        assert resp.status_code == 200

    def test_optimize_unknown_model(self):
        resp = client.post(
            "/portfolio/optimize",
            json={"symbols": ["AAPL", "MSFT"], "model": "unknown_model"},
        )
        # _fetch_returns 会走 mock 数据，然后抛 400
        assert resp.status_code in (400, 500)


class TestEfficientFrontier:
    def test_frontier_too_few(self):
        resp = client.post("/portfolio/efficient-frontier", json={"symbols": ["AAPL"]})
        assert resp.status_code == 400

    @patch("backend.routers.portfolio._fetch_returns")
    @patch("backend.routers.portfolio.portfolio_optimizer")
    def test_frontier_success(self, mock_opt, mock_fetch):
        import pandas as pd

        mock_fetch.return_value = pd.DataFrame({"AAPL": [0.01, -0.005], "MSFT": [0.008, -0.003]})
        mock_opt.efficient_frontier.return_value = [{"return": 0.1, "vol": 0.15}]
        resp = client.post(
            "/portfolio/efficient-frontier",
            json={"symbols": ["AAPL", "MSFT"]},
        )
        assert resp.status_code == 200


class TestCompareModels:
    def test_compare_too_few(self):
        resp = client.post("/portfolio/compare", json={"symbols": ["AAPL"]})
        assert resp.status_code == 400

    @patch("backend.routers.portfolio._fetch_returns")
    @patch("backend.routers.portfolio.portfolio_optimizer")
    def test_compare_success(self, mock_opt, mock_fetch):
        import pandas as pd

        mock_fetch.return_value = pd.DataFrame({"AAPL": [0.01, -0.005], "MSFT": [0.008, -0.003]})
        mock_opt.compare_models.return_value = {"models": []}
        resp = client.post(
            "/portfolio/compare",
            json={"symbols": ["AAPL", "MSFT"]},
        )
        assert resp.status_code == 200
