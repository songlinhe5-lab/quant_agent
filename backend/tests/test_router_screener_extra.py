"""
选股器路由增强单元测试
覆盖: backend/routers/screener.py 中未在 test_screener.py 覆盖的端点
"""

import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


def _unwrap(resp):
    """剥离统一响应封装，返回路由原始 dict"""
    body = resp.json()
    return body.get("data", body)


class TestScreenerSuggestionsRoutes:
    """选股灵感路由测试"""

    def test_get_screener_suggestions_success(self):
        """正常路径：获取随机选股灵感"""
        client = TestClient(app)
        resp = client.get("/api/v1/screener/suggestions?limit=5")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) <= 5


class TestScreenerTranslateRoutes:
    """自然语言转 DSL 路由测试"""

    @patch("backend.routers.screener.screener_service")
    def test_translate_dsl_success(self, mock_service):
        """正常路径：自然语言转 DSL 成功"""
        mock_service.translate_nlp_to_dsl = AsyncMock(return_value='{"markets": ["US"], "filters": []}')
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/translate",
            json={"query": "美股市值大于1000亿"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.screener_service")
    def test_translate_dsl_failure(self, mock_service):
        """异常路径：转译失败返回 500"""
        mock_service.translate_nlp_to_dsl = AsyncMock(side_effect=RuntimeError("LLM 限流"))
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/translate",
            json={"query": "无效查询"},
        )
        assert resp.status_code == 500

    def test_translate_dsl_invalid_payload(self):
        """参数校验：缺少 query 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/screener/translate", json={})
        assert resp.status_code == 422


class TestScreenerRunRoutes:
    """选股器执行路由测试"""

    @patch("backend.routers.screener.redis_client")
    @patch("backend.routers.screener.screener_service")
    @patch("backend.routers.screener.market_data")
    def test_run_screener_cache_hit(self, mock_futu, mock_service, mock_redis):
        """缓存命中：直接返回 Redis 中的选股结果"""
        import json

        cached = json.dumps([{"symbol": "US.AAPL", "name": "Apple"}])
        mock_redis.get = AsyncMock(return_value=cached)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"markets": ["US"], "filters": []}'},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.redis_client")
    @patch("backend.routers.screener.screener_service")
    @patch("backend.routers.screener.market_data")
    def test_run_screener_invalid_dsl(self, mock_futu, mock_service, mock_redis):
        """异常路径：DSL 不是合法 JSON 返回 400"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": "not a json"},
        )
        assert resp.status_code == 400

    def test_run_screener_invalid_payload(self):
        """参数校验：缺少 dsl 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/screener/run", json={})
        assert resp.status_code == 422


class TestScreenerSummarizeRoutes:
    """AI 总结选股结果路由测试"""

    @patch("backend.routers.screener.screener_service")
    def test_summarize_results_success(self, mock_service):
        """正常路径：AI 总结成功"""
        mock_service.summarize_results = AsyncMock(return_value="整体市场情绪偏多，半导体板块领涨。")
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/summarize",
            json={"stocks": [{"symbol": "US.NVDA", "name": "NVIDIA"}]},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.screener_service")
    def test_summarize_results_failure(self, mock_service):
        """异常路径：AI 总结失败返回 error"""
        mock_service.summarize_results = AsyncMock(side_effect=RuntimeError("LLM 限流"))
        client = TestClient(app)
        resp = client.post(
            "/api/v1/screener/summarize",
            json={"stocks": []},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
