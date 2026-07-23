"""
策略研发工作台路由补充测试
覆盖: backend/routers/strategy.py 未覆盖的端点
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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
    body = resp.json()
    return body.get("data", body)


# ==========================================
# POST /strategy/save
# ==========================================


class TestStrategySave:
    @patch("backend.routers.strategy.strategy_version_service")
    def test_save_success(self, mock_ver, client, tmp_path):
        """正常保存策略"""
        mock_ver.save_version.return_value = {
            "version_id": "abc123",
            "seq": 1,
            "code_hash": "deadbeef1234",
        }
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(tmp_path / "drafts")):
            with patch("builtins.open", MagicMock()):
                with patch("backend.routers.strategy.os.makedirs"):
                    resp = client.post(
                        "/api/v1/strategy/save",
                        json={"source_code": "class S: pass", "class_name": "TestStrat"},
                    )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_save_with_message(self, mock_ver, client, tmp_path):
        """带备注保存"""
        mock_ver.save_version.return_value = {
            "version_id": "v1",
            "seq": 2,
            "code_hash": "hash123456",
        }
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(tmp_path / "drafts")):
            with patch("builtins.open", MagicMock()):
                with patch("backend.routers.strategy.os.makedirs"):
                    resp = client.post(
                        "/api/v1/strategy/save",
                        json={"source_code": "class S: pass", "class_name": "MyStrat", "message": "v2 优化"},
                    )
        assert resp.status_code == 200

    def test_save_missing_fields(self, client):
        """缺少必填字段返回 422"""
        resp = client.post("/api/v1/strategy/save", json={"source_code": "x"})
        assert resp.status_code == 422


# ==========================================
# GET /strategy/list
# ==========================================


class TestStrategyList:
    def test_list_no_dir(self, client):
        """目录不存在返回空列表"""
        with patch("backend.routers.strategy.os.path.exists", return_value=False):
            resp = client.get("/api/v1/strategy/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"] == []

    def test_list_with_files(self, client, tmp_path):
        """有策略文件时返回列表"""
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "my_strat.py").write_text("class S: pass")
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(drafts)):
            resp = client.get("/api/v1/strategy/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert len(data["data"]) >= 1
        assert data["data"][0]["name"] == "my_strat"


# ==========================================
# GET /strategy/{name}/versions
# ==========================================


class TestStrategyVersions:
    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_versions(self, mock_ver, client):
        mock_ver.get_versions.return_value = [{"id": "v1", "seq": 1}]
        resp = client.get("/api/v1/strategy/my_strat/versions")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_version_detail(self, mock_ver, client):
        mock_ver.get_version.return_value = {"id": "v1", "code": "class S: pass"}
        resp = client.get("/api/v1/strategy/versions/v1")
        assert resp.status_code == 200

    @patch("backend.routers.strategy.strategy_version_service")
    def test_get_version_not_found(self, mock_ver, client):
        mock_ver.get_version.return_value = None
        resp = client.get("/api/v1/strategy/versions/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/{name}/restore
# ==========================================


class TestStrategyRestore:
    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_success(self, mock_ver, client):
        mock_ver.restore_version.return_value = {"version_id": "new_v"}
        resp = client.post("/api/v1/strategy/my_strat/restore", json={"version_id": "old_v"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_missing_version_id(self, mock_ver, client):
        resp = client.post("/api/v1/strategy/my_strat/restore", json={})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    @patch("backend.routers.strategy.strategy_version_service")
    def test_restore_version_not_found(self, mock_ver, client):
        mock_ver.restore_version.return_value = None
        resp = client.post("/api/v1/strategy/my_strat/restore", json={"version_id": "bad"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# GET/DELETE /strategy/draft/{name}
# ==========================================


class TestStrategyDraft:
    def test_get_draft_exists(self, client, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "test_strat.py").write_text("class TestStrat: pass")
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(drafts)):
            resp = client.get("/api/v1/strategy/draft/test_strat")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "class TestStrat" in data["data"]["source_code"]

    def test_get_draft_not_exists(self, client, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(drafts)):
            resp = client.get("/api/v1/strategy/draft/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"

    def test_delete_draft_success(self, client, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        f = drafts / "to_delete.py"
        f.write_text("class X: pass")
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(drafts)):
            resp = client.delete("/api/v1/strategy/draft/to_delete")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    def test_delete_draft_not_exists(self, client, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        with patch("backend.routers.strategy.os.path.abspath", return_value=str(drafts)):
            resp = client.delete("/api/v1/strategy/draft/nonexist")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# POST /strategy/run-sandbox
# ==========================================


class TestStrategyRunSandbox:
    @patch("backend.routers.strategy.redis_client")
    @patch("backend.routers.strategy._fetch_backtest_data", new_callable=AsyncMock)
    @patch("backend.routers.strategy.run_dynamic_sandbox_backtest")
    def test_run_sandbox_data_fail(self, mock_bt, mock_fetch, mock_redis, client):
        """数据加载失败"""
        from backend.routers.auth import get_current_user

        # RateLimiter mock
        pipe_mock = AsyncMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True])
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)

        mock_fetch.return_value = (False, None, "数据源不可用")
        # 覆盖认证依赖
        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1)
        try:
            resp = client.post(
                "/api/v1/strategy/run-sandbox",
                json={
                    "source_code": "class S: pass",
                    "class_name": "S",
                    "params": {},
                    "ticker": "US.AAPL",
                },
            )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "数据加载失败" in data["message"]


# ==========================================
# POST /strategy/generate (streaming)
# ==========================================


class TestStrategyGenerate:
    @patch("backend.routers.strategy.llm_service")
    def test_generate_stream(self, mock_llm, client):
        """流式生成策略代码"""

        async def mock_stream():
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            chunk1.choices[0].delta.content = "class S:"
            chunk1.choices[0].delta.reasoning_content = None
            yield chunk1
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            chunk2.choices[0].delta.content = " pass"
            chunk2.choices[0].delta.reasoning_content = None
            yield chunk2

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_llm.get_client.return_value = mock_client
        mock_llm.get_model.return_value = "test-model"

        resp = client.post("/api/v1/strategy/generate", json={"prompt": "双均线策略"})
        assert resp.status_code == 200


# ==========================================
# POST /strategy/format
# ==========================================


class TestStrategyFormat:
    def test_format_invalid_code(self, client):
        """格式化语法错误代码"""
        resp = client.post("/api/v1/strategy/format", json={"source_code": "def f(:\n  pass"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        # black 会报错或成功
        assert data["status"] in ("success", "error")


# ==========================================
# RateLimiter 单元测试
# ==========================================


class TestRateLimiter:
    @patch("backend.routers.strategy.redis_client")
    def test_rate_limit_exceeded(self, mock_redis, client):
        """触发限流返回 429"""
        pipe_mock = AsyncMock()
        pipe_mock.execute = AsyncMock(return_value=[100, True, 100, True])  # 超过限制
        pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
        pipe_mock.__aexit__ = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        # violation count
        v_pipe = AsyncMock()
        v_pipe.execute = AsyncMock(return_value=[1, True])
        v_pipe.__aenter__ = AsyncMock(return_value=v_pipe)
        v_pipe.__aexit__ = AsyncMock(return_value=None)

        # 第二次 pipeline 调用返回 violation
        call_count = [0]
        orig_pipeline = mock_redis.pipeline

        def side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return pipe_mock
            return v_pipe

        mock_redis.pipeline = MagicMock(side_effect=side_effect)

        with patch("backend.routers.strategy._ensure_and_load_inspirations", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = ["策略A", "策略B"]
            resp = client.get("/api/v1/strategy/inspirations?limit=1")
        assert resp.status_code == 429

    @patch("backend.routers.strategy.redis_client")
    def test_rate_limit_blacklisted(self, mock_redis, client):
        """黑名单拦截返回 403"""
        mock_redis.get = AsyncMock(return_value="1")  # 在黑名单中
        with patch("backend.routers.strategy._ensure_and_load_inspirations", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = ["策略A"]
            resp = client.get("/api/v1/strategy/inspirations?limit=1")
        assert resp.status_code == 403
