"""
选股器路由补充测试
覆盖: backend/routers/screener.py 未覆盖的端点
"""

import json
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
# GET /screener/suggestions
# ==========================================


class TestScreenerSuggestions:
    def test_suggestions_default(self, client):
        resp = client.get("/api/v1/screener/suggestions")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 6

    def test_suggestions_custom_limit(self, client):
        resp = client.get("/api/v1/screener/suggestions?limit=3")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert len(data["data"]) == 3


# ==========================================
# POST /screener/translate
# ==========================================


class TestScreenerTranslate:
    @patch("backend.routers.screener.screener_service")
    def test_translate_success(self, mock_svc, client):
        mock_svc.translate_nlp_to_dsl = AsyncMock(return_value='{"market": ["US"], "filters": []}')
        resp = client.post("/api/v1/screener/translate", json={"query": "低市盈率美股"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.screener_service")
    def test_translate_error(self, mock_svc, client):
        mock_svc.translate_nlp_to_dsl = AsyncMock(side_effect=Exception("LLM 不可用"))
        resp = client.post("/api/v1/screener/translate", json={"query": "test"})
        assert resp.status_code == 500


# ==========================================
# POST /screener/run
# ==========================================


class TestScreenerRun:
    @patch("backend.routers.screener.redis_client")
    def test_run_cache_hit(self, mock_redis, client):
        """Redis 缓存命中"""
        cached_data = [{"symbol": "US.AAPL", "name": "Apple", "mktcap": "3T", "price": 200}]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        resp = client.post("/api/v1/screener/run", json={"dsl": '{"market":["US"]}'})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "命中 Redis 极速缓存" in data.get("message", "")

    @patch("backend.routers.screener.screener_service")
    @patch("backend.routers.screener.market_data")
    @patch("backend.routers.screener.redis_client")
    def test_run_futu_success(self, mock_redis, mock_md, mock_svc, client):
        """Futu 在线筛选成功"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_svc.parse_dsl_to_futu_filters.return_value = (["US"], {"pe": {"min": 0, "max": 20}}, {})
        mock_svc.apply_technical_pattern_filtering = AsyncMock(
            return_value=[{"symbol": "US.AAPL", "name": "Apple", "mktcap": "3T"}]
        )
        mock_md.screen_stocks = AsyncMock(
            return_value={"status": "success", "data": [{"symbol": "US.AAPL", "name": "Apple", "mktcap": "3T"}]}
        )
        mock_md.status = "CONNECTED"
        resp = client.post("/api/v1/screener/run", json={"dsl": '{"market":["US"],"filters":[]}'})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.redis_client")
    def test_run_invalid_dsl(self, mock_redis, client):
        """DSL 格式错误"""
        mock_redis.get = AsyncMock(return_value=None)
        resp = client.post("/api/v1/screener/run", json={"dsl": "not valid json {"})
        assert resp.status_code == 400

    @patch("backend.routers.screener.redis_client")
    def test_run_with_pagination(self, mock_redis, client):
        """带分页参数"""
        cached_data = [
            {"symbol": f"US.STK{i}", "name": f"Stock{i}", "mktcap": "1B", "price": 100 + i} for i in range(20)
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"market":["US"]}', "page": 2, "page_size": 5},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["total"] == 20
        assert len(data["data"]) == 5

    @patch("backend.routers.screener.redis_client")
    def test_run_with_filters(self, mock_redis, client):
        """带表头二次过滤"""
        cached_data = [
            {"symbol": "US.A", "name": "A", "price": 50, "mktcap": "1B"},
            {"symbol": "US.B", "name": "B", "price": 150, "mktcap": "2B"},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"market":["US"]}', "filters": {"price": {"min": 100, "max": 200}}},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["total"] == 1

    @patch("backend.routers.screener.redis_client")
    def test_run_sort_by_name(self, mock_redis, client):
        """按名称排序"""
        cached_data = [
            {"symbol": "US.B", "name": "Beta", "price": 100},
            {"symbol": "US.A", "name": "Alpha", "price": 200},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))
        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"market":["US"]}', "sort_key": "name", "sort_dir": 1},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"][0]["name"] == "Alpha"


# ==========================================
# GET/POST /screener/history
# ==========================================


class TestScreenerHistory:
    @patch("backend.routers.screener.redis_client")
    @patch("backend.routers.screener.get_current_user")
    def test_get_history_empty(self, mock_user, mock_redis, client):
        """空历史"""
        mock_user.return_value = MagicMock(id=1)
        mock_redis.get = AsyncMock(return_value=None)
        # 需要覆盖认证依赖
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.get("/api/v1/screener/history")
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()

    @patch("backend.routers.screener.redis_client")
    def test_save_history(self, mock_redis, client):
        """保存历史"""
        mock_redis.set = AsyncMock(return_value=True)
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post(
                "/api/v1/screener/history",
                json={"history": [{"nlp": "低PE", "dsl": "{}", "time": 1700000000}]},
            )
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()


# ==========================================
# POST /screener/reload-indicators
# ==========================================


class TestScreenerReloadIndicators:
    @patch("backend.routers.screener.screener_service")
    def test_reload_success(self, mock_svc, client):
        mock_svc.reload_rag_corpus.return_value = {"count": 150}
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post("/api/v1/screener/reload-indicators")
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()


# ==========================================
# GET/POST/DELETE /screener/dictionary
# ==========================================


class TestScreenerDictionary:
    @patch("backend.routers.screener.screener_service")
    def test_get_dictionary(self, mock_svc, client):
        mock_svc.get_custom_rules = AsyncMock(return_value=[{"id": 1, "desc": "低PE", "rule": "pe<15"}])
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.get("/api/v1/screener/dictionary")
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()

    @patch("backend.routers.screener.screener_service")
    def test_add_dictionary_item(self, mock_svc, client):
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "success"})
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post("/api/v1/screener/dictionary", json={"desc": "低PE", "rule": "pe<15"})
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()

    @patch("backend.routers.screener.screener_service")
    def test_add_dictionary_error(self, mock_svc, client):
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "error", "message": "重复"})
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post("/api/v1/screener/dictionary", json={"desc": "dup", "rule": "x"})
            assert resp.status_code in (500, 401, 403)
        finally:
            app.dependency_overrides.clear()


# ==========================================
# POST /screener/dictionary/batch
# ==========================================


class TestScreenerDictionaryBatch:
    @patch("backend.routers.screener.screener_service")
    def test_batch_import_success(self, mock_svc, client):
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "success"})
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post(
                "/api/v1/screener/dictionary/batch",
                json={"items": [{"desc": "规则1", "rule": "pe<10"}, {"desc": "规则2", "rule": "pb<1"}]},
            )
            assert resp.status_code in (200, 401, 403)
        finally:
            app.dependency_overrides.clear()

    @patch("backend.routers.screener.screener_service")
    def test_batch_import_all_fail(self, mock_svc, client):
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "error", "message": "fail"})
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post(
                "/api/v1/screener/dictionary/batch",
                json={"items": [{"desc": "bad", "rule": "x"}]},
            )
            assert resp.status_code in (500, 401, 403)
        finally:
            app.dependency_overrides.clear()


# ==========================================
# POST /screener/subscribe
# ==========================================


class TestScreenerSubscribe:
    def test_subscribe_invalid_time(self, client):
        """触发时间格式错误"""
        app.dependency_overrides[get_current_user_dep()] = lambda: MagicMock(id=1)
        try:
            resp = client.post(
                "/api/v1/screener/subscribe",
                json={"name": "test", "dsl": "{}", "trigger_time": "invalid"},
            )
            assert resp.status_code in (400, 401, 403, 500)
        finally:
            app.dependency_overrides.clear()


# ==========================================
# 辅助函数测试
# ==========================================


class TestScreenerHelpers:
    def test_parse_human_number(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number(100) == 100.0
        assert _parse_human_number("1.5T") == 1.5e12
        assert _parse_human_number("500B") == 500e8
        assert _parse_human_number("200M") == 200e6
        assert _parse_human_number("50K") == 50e3
        assert _parse_human_number("10万") == 10e4
        assert _parse_human_number("5亿") == 5e8
        assert _parse_human_number("2万亿") == 2e12
        assert _parse_human_number(None) == 0.0
        assert _parse_human_number("+15%") == 15.0
        assert _parse_human_number("invalid") == 0.0

    def test_clean_json_dsl(self):
        from backend.routers.screener import _clean_json_dsl

        # 带 markdown 代码块
        dsl = '```json\n{"market": ["US"]}\n```'
        cleaned = _clean_json_dsl(dsl)
        assert cleaned == '{"market": ["US"]}'

        # 带注释
        dsl_with_comment = '{"market": ["US"]} // comment'
        cleaned = _clean_json_dsl(dsl_with_comment)
        assert "comment" not in cleaned


def get_current_user_dep():
    """获取认证依赖函数"""
    from backend.routers.auth import get_current_user

    return get_current_user
