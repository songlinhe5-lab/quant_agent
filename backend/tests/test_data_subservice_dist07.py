"""
DIST-07: data_subservice HTTP 接口 — 单元测试
================================================

验证:
  1. HMAC 签名验证 (有效/无效/缺失/无密钥模式)
  2. 限流错误检测 (error_category 注入)
  3. /v1/quote, /v1/history, /v1/batch, /v1/indicators, /v1/search 端点
  4. /v1/macro 从 Redis 读取缓存
  5. /v1/health 返回健康状态
  6. worker 未初始化时返回 503
  7. 路由器兼容端点 (/api/v1/data-source/proxy/yfinance, /api/v1/data-source/proxy/batch_quote)
"""

import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────
#  HMAC 签名辅助
# ─────────────────────────────────────────
_HMAC_SECRET = "test-secret-key"


def _sign(body: dict, secret: str = _HMAC_SECRET, timestamp: str | None = None) -> dict:
    """构造合法 HMAC 签名 headers，默认使用当前时间"""
    if timestamp is None:
        timestamp = str(int(time.time()))
    body_with_ts = body.copy()
    body_with_ts["__timestamp"] = timestamp
    sig = hashlib.sha256(secret.encode("utf-8") + json.dumps(body_with_ts, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "X-Data-Source-Signature": sig,
        "X-Data-Source-Timestamp": timestamp,
    }


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_routes_state():
    """每个测试前重置 routes 模块的全局状态"""
    import data_subservice.routes as routes_mod

    routes_mod._request_timestamps.clear()
    yield


@pytest.fixture()
def mock_worker():
    """构造 mock YFinanceWorker"""
    w = MagicMock()
    w.batched_quote = AsyncMock(return_value={"status": "success", "data": {"price": 150.0}})
    w.fetch = AsyncMock(return_value={"success": True, "data": [{"Close": 150}], "message": ""})
    w.tech_indicators = AsyncMock(return_value={"status": "success", "data": {"macd": 1.2}})
    w.search = AsyncMock(return_value={"status": "success", "data": [{"symbol": "AAPL"}]})
    w.get_health.return_value = {"status": "healthy", "daemon_running": True}
    return w


@pytest.fixture()
def mock_redis():
    """构造 mock Redis 客户端"""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


@pytest.fixture()
def client_no_auth(mock_worker, mock_redis):
    """无 HMAC 密钥模式下的 TestClient (开发模式，签名验证跳过)"""
    import data_subservice.main as main_mod
    import data_subservice.routes as routes_mod

    with (
        patch.object(routes_mod, "_HMAC_SECRET", ""),
        patch.object(main_mod, "_yf_worker", mock_worker),
        patch.object(main_mod, "_redis_client", mock_redis),
    ):
        from data_subservice.main import app

        yield TestClient(app)


@pytest.fixture()
def client_with_auth(mock_worker, mock_redis):
    """启用 HMAC 签名验证的 TestClient"""
    import data_subservice.main as main_mod
    import data_subservice.routes as routes_mod

    with (
        patch.object(routes_mod, "_HMAC_SECRET", _HMAC_SECRET),
        patch.object(routes_mod, "_allowed_ip_set", set()),
        patch.object(main_mod, "_yf_worker", mock_worker),
        patch.object(main_mod, "_redis_client", mock_redis),
    ):
        from data_subservice.main import app

        yield TestClient(app)


# ─────────────────────────────────────────
#  1. 限流错误检测
# ─────────────────────────────────────────


class TestDetectErrorCategory:
    """验证 _detect_error_category 限流关键词注入"""

    def test_rate_limit_429(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "error", "message": "429 Too Many Requests"})
        assert result["error_category"] == "rate_limit"

    def test_rate_limit_chinese_keyword(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "error", "message": "限流冷却中：yfinance 触发了 429"})
        assert result["error_category"] == "rate_limit"

    def test_rate_limit_yf_error(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "error", "message": "YFRateLimitError: something"})
        assert result["error_category"] == "rate_limit"

    def test_normal_error_no_category(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "error", "message": "connection timeout"})
        assert "error_category" not in result

    def test_success_no_category(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "success", "data": {"price": 150}})
        assert "error_category" not in result

    def test_empty_message(self):
        from data_subservice.routes import _detect_error_category

        result = _detect_error_category({"status": "error", "message": ""})
        assert "error_category" not in result


# ─────────────────────────────────────────
#  2. HMAC 签名验证
# ─────────────────────────────────────────


class TestHMACVerification:
    """验证 HMAC 签名校验逻辑"""

    def test_valid_signature_passes(self, client_with_auth, mock_worker):
        """有效签名应通过验证"""
        body = {"ticker": "AAPL"}
        headers = _sign(body)
        resp = client_with_auth.post("/v1/quote", json=body, headers=headers)
        assert resp.status_code == 200
        mock_worker.batched_quote.assert_awaited_once()

    def test_missing_signature_rejected(self, client_with_auth):
        """缺少签名应返回 401"""
        resp = client_with_auth.post("/v1/quote", json={"ticker": "AAPL"})
        assert resp.status_code == 401

    def test_invalid_signature_rejected(self, client_with_auth):
        """错误签名应返回 401"""
        ts = str(int(time.time()))
        headers = {
            "X-Data-Source-Signature": "bad-signature",
            "X-Data-Source-Timestamp": ts,
        }
        resp = client_with_auth.post("/v1/quote", json={"ticker": "AAPL"}, headers=headers)
        assert resp.status_code == 401

    def test_expired_timestamp_rejected(self, client_with_auth):
        """过期时间戳应返回 401"""
        body = {"ticker": "AAPL"}
        headers = _sign(body, timestamp="946684800")  # 2000-01-01, 远超 5 分钟窗口
        resp = client_with_auth.post("/v1/quote", json=body, headers=headers)
        assert resp.status_code == 401

    def test_no_secret_skips_verification(self, client_no_auth):
        """未配置 HMAC_SECRET 时跳过验证"""
        resp = client_no_auth.post("/v1/quote", json={"ticker": "AAPL"})
        assert resp.status_code == 200


# ─────────────────────────────────────────
#  3. /v1/quote 端点
# ─────────────────────────────────────────


class TestV1Quote:
    """验证 /v1/quote 端点"""

    def test_normal_response(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/quote", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        mock_worker.batched_quote.assert_awaited_once_with("AAPL", req_type="quote")

    def test_missing_ticker_returns_400(self, client_no_auth):
        resp = client_no_auth.post("/v1/quote", json={})
        assert resp.status_code == 400
        assert "缺少 ticker" in resp.json()["message"]

    def test_worker_unavailable_returns_503(self, client_no_auth):
        import data_subservice.main as main_mod

        with patch.object(main_mod, "_yf_worker", None):
            resp = client_no_auth.post("/v1/quote", json={"ticker": "AAPL"})
            assert resp.status_code == 503

    def test_rate_limit_injects_error_category(self, client_no_auth, mock_worker):
        mock_worker.batched_quote.return_value = {"status": "error", "message": "限流冷却中：429 保护"}
        resp = client_no_auth.post("/v1/quote", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        assert resp.json()["error_category"] == "rate_limit"


# ─────────────────────────────────────────
#  4. /v1/history 端点
# ─────────────────────────────────────────


class TestV1History:
    """验证 /v1/history 端点"""

    def test_normal_response(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/history", json={"ticker": "AAPL", "period": "1mo"})
        assert resp.status_code == 200
        mock_worker.fetch.assert_awaited_once_with("AAPL", "history", ttl=3600, period="1mo")

    def test_missing_ticker_returns_400(self, client_no_auth):
        resp = client_no_auth.post("/v1/history", json={"period": "1mo"})
        assert resp.status_code == 400


# ─────────────────────────────────────────
#  5. /v1/batch 端点
# ─────────────────────────────────────────


class TestV1Batch:
    """验证 /v1/batch 端点"""

    def test_normal_response(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/batch", json={"ticker": "AAPL", "req_type": "quote"})
        assert resp.status_code == 200
        mock_worker.batched_quote.assert_awaited_once_with("AAPL", req_type="quote")

    def test_default_req_type(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/batch", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        mock_worker.batched_quote.assert_awaited_once_with("AAPL", req_type="quote")


# ─────────────────────────────────────────
#  6. /v1/indicators 端点
# ─────────────────────────────────────────


class TestV1Indicators:
    """验证 /v1/indicators 端点"""

    def test_normal_response(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/indicators", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        mock_worker.tech_indicators.assert_awaited_once_with("AAPL")


# ─────────────────────────────────────────
#  7. /v1/search 端点
# ─────────────────────────────────────────


class TestV1Search:
    """验证 /v1/search 端点"""

    def test_normal_response(self, client_no_auth, mock_worker):
        resp = client_no_auth.post("/v1/search", json={"query": "Apple"})
        assert resp.status_code == 200
        mock_worker.search.assert_awaited_once_with("Apple")

    def test_missing_query_returns_400(self, client_no_auth):
        resp = client_no_auth.post("/v1/search", json={})
        assert resp.status_code == 400


# ─────────────────────────────────────────
#  8. /v1/macro 端点
# ─────────────────────────────────────────


class TestV1Macro:
    """验证 /v1/macro 端点"""

    def test_reads_from_redis(self, client_no_auth, mock_redis):
        mock_redis.get = AsyncMock(return_value=json.dumps([{"Close": 4500}]))
        resp = client_no_auth.get("/v1/macro?ticker=^GSPC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "^GSPC" in data["data"]

    def test_empty_cache_returns_success(self, client_no_auth, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        resp = client_no_auth.get("/v1/macro?ticker=FAKE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"] == {}

    def test_redis_unavailable_returns_503(self, client_no_auth):
        import data_subservice.main as main_mod

        with patch.object(main_mod, "_redis_client", None):
            resp = client_no_auth.get("/v1/macro")
            assert resp.status_code == 503


# ─────────────────────────────────────────
#  9. /v1/health 端点
# ─────────────────────────────────────────


class TestV1Health:
    """验证 /v1/health 端点"""

    def test_returns_health(self, client_no_auth, mock_worker):
        resp = client_no_auth.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["status"] == "healthy"
        assert data["data"]["daemon_running"] is True

    def test_worker_unavailable_returns_degraded(self, client_no_auth):
        import data_subservice.main as main_mod

        with patch.object(main_mod, "_yf_worker", None):
            resp = client_no_auth.get("/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "degraded"


# ─────────────────────────────────────────
#  10. 路由器兼容端点
# ─────────────────────────────────────────


class TestProxyEndpoints:
    """验证 /api/v1/data-source/proxy/* 路由器兼容端点"""

    def test_proxy_yfinance_history(self, client_no_auth, mock_worker):
        """proxy/yfinance + fetch_type=history 应调用 worker.fetch"""
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/yfinance",
            json={"ticker": "AAPL", "fetch_type": "history"},
        )
        assert resp.status_code == 200
        mock_worker.fetch.assert_awaited_once()

    def test_proxy_yfinance_quote(self, client_no_auth, mock_worker):
        """proxy/yfinance + fetch_type=quote 应调用 worker.batched_quote"""
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/yfinance",
            json={"ticker": "AAPL", "fetch_type": "quote"},
        )
        assert resp.status_code == 200
        mock_worker.batched_quote.assert_awaited_once()

    def test_proxy_yfinance_tech(self, client_no_auth, mock_worker):
        """proxy/yfinance + fetch_type=tech 应调用 worker.tech_indicators"""
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/yfinance",
            json={"ticker": "AAPL", "fetch_type": "tech"},
        )
        assert resp.status_code == 200
        mock_worker.tech_indicators.assert_awaited_once()

    def test_proxy_yfinance_rate_limit(self, client_no_auth, mock_worker):
        """proxy/yfinance 限流时应注入 error_category"""
        mock_worker.fetch.return_value = {"success": False, "data": None, "message": "YFRateLimitError: 429"}
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/yfinance",
            json={"ticker": "AAPL", "fetch_type": "history"},
        )
        assert resp.json()["error_category"] == "rate_limit"

    def test_proxy_batch_quote(self, client_no_auth, mock_worker):
        """proxy/batch_quote 应调用 worker.batched_quote"""
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/batch_quote",
            json={"ticker": "AAPL", "req_type": "quote"},
        )
        assert resp.status_code == 200
        mock_worker.batched_quote.assert_awaited_once_with("AAPL", req_type="quote")

    def test_proxy_worker_unavailable(self, client_no_auth):
        """worker 未初始化时 proxy 端点返回 503"""
        import data_subservice.main as main_mod

        with patch.object(main_mod, "_yf_worker", None):
            resp = client_no_auth.post(
                "/api/v1/data-source/proxy/yfinance",
                json={"ticker": "AAPL", "fetch_type": "history"},
            )
            assert resp.status_code == 503

    def test_proxy_missing_ticker(self, client_no_auth):
        """缺少 ticker 返回 400"""
        resp = client_no_auth.post(
            "/api/v1/data-source/proxy/yfinance",
            json={"fetch_type": "history"},
        )
        assert resp.status_code == 400
