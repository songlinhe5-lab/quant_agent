"""
策略路由深度测试 - 覆盖 _fetch_backtest_data + 文件操作端点
覆盖: backend/routers/strategy.py (lines 346-544, 646-796)
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _unwrap(resp):
    """剥离 response_envelope_middleware 封装: {code, msg, data, ts}"""
    body = resp.json()
    if isinstance(body, dict) and "code" in body and "data" in body:
        return body["data"]
    return body


# ==========================================
# _fetch_backtest_data 内部函数测试
# ==========================================
class TestFetchBacktestData:
    """直接调用 _fetch_backtest_data 覆盖多数据源路径"""

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_local_db_success(self, mock_kw):
        """本地数仓成功返回数据"""
        from backend.routers.strategy import _fetch_backtest_data

        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=300),
                "open": [100.0] * 300,
                "high": [101.0] * 300,
                "low": [99.0] * 300,
                "close": [100.5] * 300,
                "volume": [1000] * 300,
            }
        )
        mock_kw.get_history = AsyncMock(return_value=df)

        success, result_df, source = await _fetch_backtest_data("US.AAPL", "1y", "local", "1d")
        assert success is True
        assert result_df is not None
        assert "Close" in result_df.columns
        assert source == "LocalDB"

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_local_db_insufficient_data(self, mock_kw):
        """本地数仓数据不足"""
        from backend.routers.strategy import _fetch_backtest_data

        # 只有很少数据
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=10),
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.5] * 10,
                "volume": [1000] * 10,
            }
        )
        mock_kw.get_history = AsyncMock(return_value=df)

        success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "local", "1d")
        assert success is False
        assert "LOCAL_DATA_MISSING" in msg

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_local_db_none_data(self, mock_kw):
        """本地数仓返回 None"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)

        success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "local", "1d")
        assert success is False
        assert "LOCAL_DATA_MISSING" in msg

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_local_db_exception(self, mock_kw):
        """本地数仓异常"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(side_effect=Exception("DB down"))

        # data_source=local 时异常后无后续源
        success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "local", "1d")
        # local 失败后没有更多源匹配
        assert success is False

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_futu_success(self, mock_kw, mock_md):
        """Futu 数据源成功"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)
        mock_md.get_history = AsyncMock(
            return_value={
                "status": "success",
                "data": [{"time": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
                * 300,
            }
        )

        success, result_df, source = await _fetch_backtest_data("US.AAPL", "1y", "futu", "1d")
        assert success is True
        assert source == "Futu"
        assert "Close" in result_df.columns

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_futu_failure_explicit(self, mock_kw, mock_md):
        """显式指定 Futu 但失败"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)
        mock_md.get_history = AsyncMock(side_effect=Exception("Futu timeout"))

        success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "futu", "1d")
        assert success is False
        assert "Futu" in msg

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_finnhub_fallback_us_stock(self, mock_kw, mock_md):
        """Finnhub 兜底美股"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)
        mock_md.get_history = AsyncMock(return_value={"status": "error"})
        mock_md.get_stock_history_fh = AsyncMock(
            return_value={
                "status": "success",
                "data": [{"time": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
                * 300,
            }
        )

        success, result_df, source = await _fetch_backtest_data("US.AAPL", "1y", "auto", "1d")
        assert success is True
        assert source == "Finnhub"

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_akshare_fallback_a_stock(self, mock_kw, mock_md):
        """AKShare 兜底 A 股"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)
        mock_md.get_history = AsyncMock(return_value={"status": "error"})
        mock_md.get_stock_history_ak = AsyncMock(
            return_value={
                "status": "success",
                "data": [{"time": "2024-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 5000}] * 300,
            }
        )

        success, result_df, source = await _fetch_backtest_data("SH.600519", "1y", "auto", "1d")
        assert success is True
        assert source == "AKShare"

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_yfinance_final_fallback(self, mock_kw, mock_md):
        """YFinance 终极兜底"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)
        mock_md.get_history = AsyncMock(return_value={"status": "error"})
        mock_md.get_stock_history_fh = AsyncMock(return_value={"status": "error"})
        mock_md.fetch_yf_data = AsyncMock(return_value=(True, pd.DataFrame({"Close": [100] * 300}), "YFinance"))

        success, result_df, source = await _fetch_backtest_data("US.AAPL", "1y", "yfinance", "1d")
        assert success is True

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_unsupported_source(self, mock_kw):
        """不支持的数据源"""
        from backend.routers.strategy import _fetch_backtest_data

        mock_kw.get_history = AsyncMock(return_value=None)

        success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "unknown_source", "1d")
        assert success is False
        assert "未匹配" in msg

    @pytest.mark.asyncio
    @patch("backend.routers.strategy.kline_warehouse")
    async def test_interval_multiplier(self, mock_kw):
        """不同 interval 的 multiplier 计算"""
        from backend.routers.strategy import _fetch_backtest_data

        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=100000),
                "open": [100.0] * 100000,
                "high": [101.0] * 100000,
                "low": [99.0] * 100000,
                "close": [100.5] * 100000,
                "volume": [1000] * 100000,
            }
        )
        mock_kw.get_history = AsyncMock(return_value=df)

        success, _, _ = await _fetch_backtest_data("US.AAPL", "1y", "local", "5m")
        assert success is True

    @pytest.mark.asyncio
    async def test_live_forbidden(self):
        """live 模式被禁止"""
        from backend.routers.strategy import _fetch_backtest_data

        with patch.dict(os.environ, {"ENGINE_ALLOW_LIVE_DATA": "false"}):
            success, result_df, msg = await _fetch_backtest_data("US.AAPL", "1y", "auto", "1d", snapshot_id="live")
            assert success is False
            assert "LIVE_FORBIDDEN" in msg


# ==========================================
# POST /strategy/format
# ==========================================
class TestFormatEndpoint:
    def test_format_success(self, client):
        """格式化 - black 可能未安装"""
        resp = client.post(
            "/api/v1/strategy/format",
            json={"source_code": "x=1\ny=2\n"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        # black 未安装时返回 error，安装了返回 success
        assert data["status"] in ("success", "error")
        if data["status"] == "success":
            assert "x = 1" in data["data"]

    def test_format_syntax_error(self, client):
        """语法错误"""
        resp = client.post(
            "/api/v1/strategy/format",
            json={"source_code": "def foo(\n"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/parse-config
# ==========================================
class TestParseConfig:
    def test_parse_config(self, client):
        """解析策略参数配置"""
        code = '''
class MyStrategy(BaseStrategy):
    """测试策略
    :param fast_ma: 快速均线
    :param slow_ma: 慢速均线
    """
    def __init__(self, fast_ma: int = 5, slow_ma: int = 20):
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
'''
        resp = client.post("/api/v1/strategy/parse-config", json={"source_code": code})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data.get("status") == "success" or "params" in str(data)


# ==========================================
# GET /strategy/list
# ==========================================
class TestListStrategies:
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.stat")
    def test_list_strategies(self, mock_stat, mock_listdir, mock_exists, client):
        """列出策略草稿"""
        mock_exists.return_value = True
        mock_listdir.return_value = ["my_strategy.py", "readme.txt"]
        mock_stat_result = MagicMock()
        mock_stat_result.st_mtime = 1700000000
        mock_stat.return_value = mock_stat_result

        resp = client.get("/api/v1/strategy/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        # 只有 .py 文件
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "my_strategy"

    @patch("os.path.exists")
    def test_list_no_dir(self, mock_exists, client):
        """目录不存在"""
        mock_exists.return_value = False
        resp = client.get("/api/v1/strategy/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"] == []


# ==========================================
# GET /strategy/draft/{name}
# ==========================================
class TestGetDraft:
    @patch("builtins.open", create=True)
    @patch("os.path.exists")
    def test_get_draft_success(self, mock_exists, mock_open, client):
        """获取策略草稿"""
        mock_exists.return_value = True
        mock_open.return_value.__enter__ = lambda s: MagicMock(read=lambda: "class Foo: pass")
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.get("/api/v1/strategy/draft/foo")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("os.path.exists")
    def test_get_draft_not_found(self, mock_exists, client):
        """策略不存在"""
        mock_exists.return_value = False
        resp = client.get("/api/v1/strategy/draft/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# DELETE /strategy/draft/{name}
# ==========================================
class TestDeleteDraft:
    @patch("os.remove")
    @patch("os.path.exists")
    def test_delete_draft_success(self, mock_exists, mock_remove, client):
        """删除策略草稿"""
        mock_exists.return_value = True
        resp = client.delete("/api/v1/strategy/draft/foo")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("os.path.exists")
    def test_delete_draft_not_found(self, mock_exists, client):
        """文件不存在"""
        mock_exists.return_value = False
        resp = client.delete("/api/v1/strategy/draft/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/save
# ==========================================
class TestSaveStrategy:
    @patch("backend.routers.strategy.strategy_version_service")
    @patch("builtins.open", create=True)
    @patch("os.makedirs")
    def test_save_success(self, mock_makedirs, mock_open, mock_version_svc, client):
        """保存策略成功"""
        mock_version_svc.save_version.return_value = {
            "version_id": "v12345678",
            "seq": 1,
            "code_hash": "abcdef1234567890",
        }
        mock_file = MagicMock()
        mock_open.return_value.__enter__ = lambda s: mock_file
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/api/v1/strategy/save",
            json={"source_code": "class Foo: pass", "class_name": "Foo", "message": "test"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "version_id" in data["data"]

    @patch("backend.routers.strategy.strategy_version_service")
    @patch("os.makedirs")
    def test_save_exception(self, mock_makedirs, mock_version_svc, client):
        """保存失败"""
        mock_version_svc.save_version.side_effect = Exception("DB error")

        resp = client.post(
            "/api/v1/strategy/save",
            json={"source_code": "class Foo: pass", "class_name": "Foo"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/run-sandbox (error paths)
# ==========================================
class TestRunSandbox:
    @pytest.fixture(autouse=True)
    def _override_auth(self):
        """覆盖 get_current_user 依赖以绕过鉴权"""
        from backend.routers.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1)
        yield
        app.dependency_overrides.pop(get_current_user, None)

    @patch("backend.routers.strategy._fetch_backtest_data")
    def test_data_load_failure(self, mock_fetch, client):
        """数据加载失败"""
        mock_fetch.return_value = (False, None, "NO_DATA")

        resp = client.post(
            "/api/v1/strategy/run-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
                "ticker": "US.AAPL",
                "period": "1y",
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "回测数据加载失败" in data["message"]

    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_dynamic_sandbox_backtest")
    def test_value_error(self, mock_run, mock_fetch, client):
        """策略代码 ValueError"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_run.side_effect = ValueError("策略逻辑错误")

        resp = client.post(
            "/api/v1/strategy/run-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert data["error_code"] == "SANDBOX_RUNTIME_ERROR"

    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_dynamic_sandbox_backtest")
    def test_generic_exception(self, mock_run, mock_fetch, client):
        """策略代码未知异常"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_run.side_effect = RuntimeError("unexpected crash")

        resp = client.post(
            "/api/v1/strategy/run-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "error_detail" in data["data"]


# ==========================================
# POST /strategy/optimize-sandbox (error paths)
# ==========================================
class TestOptimizeSandbox:
    @patch("backend.routers.strategy._fetch_backtest_data")
    def test_data_load_failure(self, mock_fetch, client):
        """数据加载失败"""
        mock_fetch.return_value = (False, None, "NO_DATA")

        resp = client.post(
            "/api/v1/strategy/optimize-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "param_grid": {"fast_ma": [5, 10]},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_grid_search_backtest")
    def test_no_valid_results(self, mock_run, mock_fetch, client):
        """网格搜索无有效结果"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_run.return_value = []

        resp = client.post(
            "/api/v1/strategy/optimize-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "param_grid": {"fast_ma": [5, 10]},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "未找到" in data["message"]

    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_grid_search_backtest")
    def test_value_error(self, mock_run, mock_fetch, client):
        """ValueError"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_run.side_effect = ValueError("bad params")

        resp = client.post(
            "/api/v1/strategy/optimize-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "param_grid": {"fast_ma": [5, 10]},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/run-batch-sandbox
# ==========================================
class TestBatchSandbox:
    @patch("backend.routers.strategy._fetch_backtest_data")
    def test_all_fetch_fail(self, mock_fetch, client):
        """所有标的数据获取失败"""
        mock_fetch.return_value = (False, None, "NO_DATA")

        resp = client.post(
            "/api/v1/strategy/run-batch-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
                "tickers": ["US.AAPL", "US.MSFT"],
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "失败" in data["message"]

    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_batch_sandbox_backtest")
    def test_batch_success(self, mock_run, mock_fetch, client):
        """批量回测成功"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_run.return_value = {"results": []}

        resp = client.post(
            "/api/v1/strategy/run-batch-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
                "tickers": ["US.AAPL"],
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"


# ==========================================
# POST /strategy/monte-carlo-sandbox
# ==========================================
class TestMonteCarloSandbox:
    @patch("backend.routers.strategy._fetch_backtest_data")
    def test_data_load_failure(self, mock_fetch, client):
        """数据加载失败"""
        mock_fetch.return_value = (False, None, "NO_DATA")

        resp = client.post(
            "/api/v1/strategy/monte-carlo-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    @patch("backend.routers.strategy.market_data")
    @patch("backend.routers.strategy._fetch_backtest_data")
    @patch("backend.routers.strategy.run_monte_carlo_stress_test")
    def test_monte_carlo_success(self, mock_mc, mock_fetch, mock_md, client):
        """蒙特卡洛成功"""
        df = pd.DataFrame({"Open": [100], "High": [101], "Low": [99], "Close": [100], "Volume": [1000]})
        mock_fetch.return_value = (True, df, "LocalDB")
        mock_md.fetch_yf_data = AsyncMock(return_value=(True, {"marketCap": 1e12, "beta": 1.2}, "YFinance"))
        mock_mc.return_value = {"mean_return": 0.05}

        resp = client.post(
            "/api/v1/strategy/monte-carlo-sandbox",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"


# ==========================================
# POST /strategy/deploy-to-oms
# ==========================================
class TestDeployToOms:
    @patch("backend.services.bot_runtime.bot_runtime")
    @patch("builtins.open", create=True)
    @patch("os.makedirs")
    def test_deploy_success(self, mock_makedirs, mock_open, mock_bot_rt, client):
        """部署成功"""
        mock_bot_rt.start_bot = AsyncMock()
        mock_file = MagicMock()
        mock_open.return_value.__enter__ = lambda s: mock_file
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/api/v1/strategy/deploy-to-oms",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
                "ticker": "US.AAPL",
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "bot_id" in data["data"]

    @patch("os.makedirs")
    def test_deploy_exception(self, mock_makedirs, client):
        """部署异常"""
        mock_makedirs.side_effect = Exception("Permission denied")

        resp = client.post(
            "/api/v1/strategy/deploy-to-oms",
            json={
                "source_code": "class Foo(BaseStrategy): pass",
                "class_name": "Foo",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# Version management endpoints
# ==========================================
class TestVersionEndpoints:
    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_versions(self, mock_svc, client):
        """获取版本列表"""
        mock_svc.get_versions.return_value = [{"id": "v1", "seq": 1}]
        resp = client.get("/api/v1/strategy/my_strat/versions")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_version_found(self, mock_svc, client):
        """获取单个版本"""
        mock_svc.get_version.return_value = {"id": "v1", "code": "class Foo: pass"}
        resp = client.get("/api/v1/strategy/versions/v1")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_version_not_found(self, mock_svc, client):
        """版本不存在"""
        mock_svc.get_version.return_value = None
        resp = client.get("/api/v1/strategy/versions/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_version(self, mock_svc, client):
        """恢复版本"""
        mock_svc.restore_version.return_value = {"version_id": "v2", "seq": 2}
        resp = client.post(
            "/api/v1/strategy/my_strat/restore",
            json={"version_id": "v1"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_version_missing_id(self, mock_svc, client):
        """缺少 version_id"""
        resp = client.post(
            "/api/v1/strategy/my_strat/restore",
            json={},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_version_not_found(self, mock_svc, client):
        """源版本不存在"""
        mock_svc.restore_version.return_value = None
        resp = client.post(
            "/api/v1/strategy/my_strat/restore",
            json={"version_id": "nonexist"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
