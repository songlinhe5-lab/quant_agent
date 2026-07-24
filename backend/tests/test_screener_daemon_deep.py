"""
市场守护进程辅助函数 + 选股路由深度测试
覆盖: backend/services/market_daemon.py (辅助函数)
覆盖: backend/routers/screener.py (选股查询/字典/订阅)
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
from backend.services.market_daemon import _generate_news_tags, _get_news_tags_rules


@pytest.fixture
def client():
    return TestClient(app)


def _unwrap(resp):
    body = resp.json()
    if isinstance(body, dict) and "code" in body and "data" in body:
        return body["data"]
    return body


# ==========================================
# _generate_news_tags 测试
# ==========================================
class TestGenerateNewsTags:
    def test_fed_tag(self):
        """FED 相关标签"""
        rules = {"FED": r"\b(fed|fomc|powell|rate(s)?|cut|hike)\b"}
        tags = _generate_news_tags("the fed announced a rate cut today", rules)
        assert "FED" in tags

    def test_no_match(self):
        """无匹配"""
        rules = {"FED": r"\b(fed|fomc)\b"}
        tags = _generate_news_tags("apple released new iphone", rules)
        assert tags == []

    def test_multiple_tags(self):
        """多标签匹配"""
        rules = {
            "FED": r"\b(fed|rate)\b",
            "CRYPTO": r"\b(bitcoin|btc)\b",
        }
        tags = _generate_news_tags("fed rate decision impacts bitcoin price", rules)
        assert "FED" in tags
        assert "CRYPTO" in tags

    def test_invalid_regex(self):
        """无效正则不崩溃"""
        rules = {"BAD": r"[invalid("}
        tags = _generate_news_tags("some text", rules)
        assert tags == []

    def test_empty_rules(self):
        """空规则"""
        tags = _generate_news_tags("some text", {})
        assert tags == []


# ==========================================
# _get_news_tags_rules 测试
# ==========================================
class TestGetNewsTagsRules:
    @pytest.mark.asyncio
    @patch("backend.services.market_daemon.l1_cached_redis")
    async def test_from_cache(self, mock_redis):
        """从缓存获取规则"""
        custom_rules = {"CUSTOM": r"\b(test)\b"}
        mock_redis.get = AsyncMock(return_value=json.dumps(custom_rules))
        rules = await _get_news_tags_rules()
        assert "CUSTOM" in rules

    @pytest.mark.asyncio
    @patch("backend.services.market_daemon.l1_cached_redis")
    async def test_default_rules(self, mock_redis):
        """缓存为空返回默认规则"""
        mock_redis.get = AsyncMock(return_value=None)
        rules = await _get_news_tags_rules()
        assert "FED" in rules
        assert "CRYPTO" in rules
        assert "GEOPOLITICS" in rules

    @pytest.mark.asyncio
    @patch("backend.services.market_daemon.l1_cached_redis")
    async def test_redis_error(self, mock_redis):
        """Redis 异常返回默认规则"""
        mock_redis.get = AsyncMock(side_effect=Exception("down"))
        rules = await _get_news_tags_rules()
        assert "FED" in rules


# ==========================================
# POST /screener/query (缓存路径)
# ==========================================
class TestScreenerQuery:
    @patch("backend.routers.screener.redis_client")
    def test_query_from_cache(self, mock_redis, client):
        """选股查询命中缓存"""
        cached_data = [
            {"symbol": "US.AAPL", "name": "Apple", "price": 150.0, "chg": 1.5, "pe": 28.0},
            {"symbol": "US.MSFT", "name": "Microsoft", "price": 400.0, "chg": -0.5, "pe": 35.0},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"market": ["US"], "filters": {}}', "page": 1, "page_size": 20},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 2

    @patch("backend.routers.screener.redis_client")
    def test_query_with_sort(self, mock_redis, client):
        """选股查询排序"""
        cached_data = [
            {"symbol": "US.AAPL", "name": "Apple", "price": 150.0, "chg": 1.5},
            {"symbol": "US.MSFT", "name": "Microsoft", "price": 400.0, "chg": -0.5},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        resp = client.post(
            "/api/v1/screener/run",
            json={
                "dsl": '{"market": ["US"]}',
                "page": 1,
                "page_size": 20,
                "sort_key": "price",
                "sort_dir": -1,
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        # 降序排列，MSFT(400) 在前
        assert data["data"][0]["symbol"] == "US.MSFT"

    @patch("backend.routers.screener.redis_client")
    def test_query_with_filters(self, mock_redis, client):
        """选股查询过滤"""
        cached_data = [
            {"symbol": "US.AAPL", "name": "Apple", "price": 150.0, "pe": 28.0},
            {"symbol": "US.MSFT", "name": "Microsoft", "price": 400.0, "pe": 35.0},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        resp = client.post(
            "/api/v1/screener/run",
            json={
                "dsl": '{"market": ["US"]}',
                "page": 1,
                "page_size": 20,
                "filters": {"pe": {"min": 0, "max": 30}},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 1
        assert data["data"][0]["symbol"] == "US.AAPL"

    @patch("backend.routers.screener.redis_client")
    def test_query_pagination(self, mock_redis, client):
        """选股查询分页"""
        cached_data = [{"symbol": f"US.STK{i}", "name": f"Stock{i}", "price": float(i)} for i in range(50)]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        resp = client.post(
            "/api/v1/screener/run",
            json={"dsl": '{"market": ["US"]}', "page": 2, "page_size": 10},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 10
        assert data["total"] == 50


# ==========================================
# Screener dictionary endpoints
# ==========================================
class TestScreenerDictionary:
    @pytest.fixture(autouse=True)
    def _override_auth(self):
        from backend.routers.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1)
        yield
        app.dependency_overrides.pop(get_current_user, None)

    @patch("backend.routers.screener.screener_service")
    def test_get_dictionary(self, mock_svc, client):
        """获取选股字典"""
        mock_svc.get_custom_rules = AsyncMock(
            return_value={"status": "success", "data": [{"id": "1", "desc": "test", "rule": "pe<20"}]}
        )
        resp = client.get("/api/v1/screener/dictionary")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.screener.screener_service")
    def test_add_dictionary_item(self, mock_svc, client):
        """添加选股规则"""
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "success"})
        resp = client.post(
            "/api/v1/screener/dictionary",
            json={"desc": "低市盈率", "rule": "pe < 15"},
        )
        assert resp.status_code == 200

    @patch("backend.routers.screener.screener_service")
    def test_add_dictionary_error(self, mock_svc, client):
        """添加规则失败"""
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "error", "message": "dup"})
        resp = client.post(
            "/api/v1/screener/dictionary",
            json={"desc": "低市盈率", "rule": "pe < 15"},
        )
        assert resp.status_code == 500

    @patch("backend.routers.screener.screener_service")
    def test_batch_import(self, mock_svc, client):
        """批量导入"""
        mock_svc.add_custom_rule = AsyncMock(return_value={"status": "success"})
        resp = client.post(
            "/api/v1/screener/dictionary/batch",
            json={"items": [{"desc": "r1", "rule": "pe<20"}, {"desc": "r2", "rule": "pb<3"}]},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "2" in data.get("message", "")


# ==========================================
# Screener subscribe endpoints
# ==========================================
class TestScreenerSubscribe:
    @pytest.fixture(autouse=True)
    def _override_auth(self):
        from backend.routers.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: MagicMock(id=1)
        yield
        app.dependency_overrides.pop(get_current_user, None)

    def test_subscribe_invalid_time(self, client):
        """无效触发时间"""
        resp = client.post(
            "/api/v1/screener/subscribe",
            json={"name": "test", "dsl": "{}", "trigger_time": "invalid"},
        )
        assert resp.status_code == 400


# ==========================================
# Macro capital-flow endpoint
# ==========================================
class TestCapitalFlow:
    @patch("backend.routers.macro.redis_client")
    def test_capital_flow_cached(self, mock_redis, client):
        """资金流向缓存"""
        cached = {"status": "success", "data": {"flows": [], "is_market_closed": False}}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        resp = client.get("/api/v1/macro/capital-flow")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
