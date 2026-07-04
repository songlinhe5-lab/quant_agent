"""
策略研发工作台路由单元测试
覆盖: backend/routers/strategy.py
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd
from fastapi.testclient import TestClient

from backend.main import app


def _unwrap(resp):
    """剥离统一响应封装，返回路由原始 dict"""
    body = resp.json()
    return body.get("data", body)


class TestStrategyInspirationsRoutes:
    """策略灵感接口路由测试"""

    @patch("backend.routers.strategy.redis_client")
    @patch("backend.routers.strategy._ensure_and_load_inspirations", new_callable=AsyncMock)
    def test_get_inspirations_success(self, mock_load, mock_redis):
        """正常路径：返回随机策略灵感"""
        pipe_mock = AsyncMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True, 1, True])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        mock_load.return_value = ["双均线交叉策略", "RSI 超卖反弹", "布林带均值回归"]
        client = TestClient(app)
        resp = client.get("/api/v1/strategy/inspirations?limit=2")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) <= 2


class TestStrategyParseConfigRoutes:
    """策略参数解析路由测试"""

    @patch("backend.routers.strategy.parse_strategy_parameters")
    def test_parse_config_success(self, mock_parse):
        """正常路径：解析策略源码参数"""
        mock_parse.return_value = {
            "status": "success",
            "parameters": [{"name": "fast_ma", "type": "int", "default": 10}],
        }
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/parse-config",
            json={"source_code": "class S: pass"},
        )
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"

    def test_parse_config_invalid_payload(self):
        """参数校验：缺少 source_code 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/strategy/parse-config", json={})
        assert resp.status_code == 422


class TestStrategyFormatRoutes:
    """代码格式化路由测试"""

    def test_format_code_success(self):
        """正常路径：成功格式化代码"""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/format",
            json={"source_code": "x=1"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] in ("success", "error")

    def test_format_code_invalid_payload(self):
        """参数校验：缺少 source_code 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/strategy/format", json={})
        assert resp.status_code == 422


class TestStrategySaveAndListRoutes:
    """策略保存、列表与草稿读写路由测试"""

    def test_save_strategy_success(self):
        """正常路径：保存策略到草稿目录"""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/save",
            json={
                "source_code": "class MyStrategy:\n    pass\n",
                "class_name": "MyStrategy",
            },
        )
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"

    def test_save_strategy_invalid_payload(self):
        """参数校验：缺少 class_name 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/strategy/save", json={"source_code": "x"})
        assert resp.status_code == 422

    def test_list_strategies_success(self):
        """正常路径：获取策略草稿列表"""
        client = TestClient(app)
        resp = client.get("/api/v1/strategy/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_get_draft_not_exist(self):
        """异常路径：获取不存在的草稿返回 error"""
        client = TestClient(app)
        resp = client.get("/api/v1/strategy/draft/__non_exist__")
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "error"

    def test_delete_draft_not_exist(self):
        """异常路径：删除不存在的草稿返回 error"""
        client = TestClient(app)
        resp = client.delete("/api/v1/strategy/draft/__non_exist__")
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "error"


class TestStrategySandboxRoutes:
    """沙箱回测类路由测试（含降级与异常路径）

    注：run-sandbox 接口使用 by_user=True 限流器，依赖 get_current_user。
    通过 app.dependency_overrides 覆盖该依赖以绕过 JWT 校验。
    """

    def setup_method(self):
        """覆盖 get_current_user 依赖以绕过鉴权"""
        from backend.routers.auth import get_current_user

        self._orig = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1)

    def teardown_method(self):
        from backend.routers.auth import get_current_user

        if self._orig is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = self._orig

    @patch("backend.routers.strategy._fetch_backtest_data", new_callable=AsyncMock)
    @patch("backend.routers.strategy.redis_client")
    @patch("backend.routers.strategy.run_dynamic_sandbox_backtest")
    def test_run_sandbox_success(self, mock_run, mock_redis, mock_fetch):
        """正常路径：沙箱回测成功"""
        pipe_mock = AsyncMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        mock_fetch.return_value = (True, pd.DataFrame({"Open": [1], "Close": [2]}), "LocalDB")
        mock_run.return_value = {"total_return": 0.1}
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/run-sandbox",
            json={
                "source_code": "class S: pass",
                "class_name": "S",
                "params": {},
            },
        )
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"

    @patch("backend.routers.strategy._fetch_backtest_data", new_callable=AsyncMock)
    @patch("backend.routers.strategy.redis_client")
    def test_run_sandbox_data_load_fail(self, mock_redis, mock_fetch):
        """异常路径：数据加载失败时返回 error"""
        pipe_mock = AsyncMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        mock_fetch.return_value = (False, None, "数据源不可用")
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/run-sandbox",
            json={
                "source_code": "class S: pass",
                "class_name": "S",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "回测数据加载失败" in data["message"]


class TestStrategyDeployRoutes:
    """策略部署到 OMS 路由测试"""

    @patch("backend.services.bot_runtime.bot_runtime")
    @patch("backend.core.redis_client.redis_client")
    def test_deploy_to_oms_success(self, mock_redis, mock_bot_rt):
        """正常路径：策略成功部署到 OMS

        注：deploy-to-oms 内部使用 from ... import redis_client 局部导入，
        故需 patch 源头 backend.core.redis_client.redis_client。
        """
        mock_redis.hset = AsyncMock(return_value=1)
        mock_bot_rt.start_bot = AsyncMock(return_value="bot_test_001")
        client = TestClient(app)
        resp = client.post(
            "/api/v1/strategy/deploy-to-oms",
            json={
                "source_code": "class S: pass",
                "class_name": "MyDeployStrategy",
                "params": {"fast_ma": 10},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "OMS" in data["message"] or "Bot" in data["message"]
