"""
Tests for backend/routers/data_source.py (proxy router)

Coverage targets:
- proxy_yfinance endpoint
- proxy_akshare endpoint
- data_source_health endpoint
- HMAC signature verification
- IP whitelist protection
"""

import hashlib
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")

from backend.main import app

client = TestClient(app)


def _generate_signature(secret: str, payload: dict, timestamp: str) -> str:
    payload_with_ts = payload.copy()
    payload_with_ts["__timestamp"] = timestamp
    return hashlib.sha256(
        secret.encode("utf-8") + json.dumps(payload_with_ts, sort_keys=True).encode("utf-8")
    ).hexdigest()


class TestProxyYFinance:
    @patch("backend.services.yfinance_service.yf_service")
    def test_proxy_yfinance_quote(self, mock_yf):
        from backend.app.market_data import market_data

        with patch.object(
            market_data._yf, "get_batched_quote", new=AsyncMock(return_value={"success": True, "data": {"AAPL": 165.0}})
        ):
            response = client.post("/api/v1/data-source/proxy/yfinance", json={"ticker": "AAPL", "fetch_type": "quote"})
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["success"] is True

    def test_proxy_yfinance_history(self):
        from backend.app.market_data import market_data

        with patch.object(market_data._yf, "fetch_yf_data", new=AsyncMock(return_value=(True, {"price": 165.0}, ""))):
            response = client.post(
                "/api/v1/data-source/proxy/yfinance",
                json={"ticker": "AAPL", "fetch_type": "history", "kwargs": {"period": "1d"}},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["success"] is True

    @patch("backend.services.yfinance_service.yf_service")
    def test_proxy_yfinance_tech(self, mock_yf):
        from backend.app.market_data import market_data

        with patch.object(
            market_data._yf, "get_tech_indicators", new=AsyncMock(return_value={"status": "success", "data": {}})
        ):
            response = client.post(
                "/api/v1/data-source/proxy/yfinance",
                json={"ticker": "AAPL", "fetch_type": "tech", "kwargs": {"lookback_days": 60}},
            )
            assert response.status_code == 200

    def test_proxy_yfinance_unknown_type(self):
        response = client.post("/api/v1/data-source/proxy/yfinance", json={"ticker": "AAPL", "fetch_type": "unknown"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert "success" in data
        assert data["success"] is False


class TestProxyAKShare:
    def test_proxy_akshare_southbound(self):
        from backend.app.market_data import market_data

        with patch.object(
            market_data._ak, "get_southbound_flow", new=AsyncMock(return_value={"status": "success", "data": {}})
        ):
            response = client.post("/api/v1/data-source/proxy/akshare", json={"action": "southbound"})
            assert response.status_code == 200
            data = response.json()["data"]
            assert "status" in data
            assert data["status"] == "success"

    @patch("backend.services.akshare_service.akshare_service")
    def test_proxy_akshare_hsgt_holders(self, mock_ak):
        mock_ak.get_hsgt_top_holders = AsyncMock(return_value={"status": "success", "data": {}})

        response = client.post(
            "/api/v1/data-source/proxy/akshare", json={"action": "hsgt_holders", "kwargs": {"symbol": "00700"}}
        )
        assert response.status_code == 200

    def test_proxy_akshare_unknown_action(self):
        response = client.post("/api/v1/data-source/proxy/akshare", json={"action": "unknown"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert "status" in data
        assert data["status"] == "error"


class TestDataSourceHealth:
    @patch("backend.services.yfinance_service.yf_service")
    @patch("backend.services.akshare_service.akshare_service")
    def test_data_source_health(self, mock_ak, mock_yf):
        mock_yf.yf_health_status = MagicMock(return_value={"status": "healthy"})
        mock_ak.get_health_status = MagicMock(return_value={"status": "healthy"})

        response = client.get("/api/v1/data-source/health")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "status" in data
        assert data["status"] == "healthy"


class TestSecurity:
    @patch("backend.routers.data_source._HMAC_SECRET", "test-secret-123")
    @patch("backend.routers.data_source._allowed_ip_set", set())
    @patch("backend.services.yfinance_service.yf_service")
    def test_proxy_with_valid_signature(self, mock_yf):
        from backend.app.market_data import market_data

        with patch.object(
            market_data._yf, "get_batched_quote", new=AsyncMock(return_value={"success": True, "data": {"AAPL": 165.0}})
        ):
            payload = {"ticker": "AAPL", "fetch_type": "quote"}
            timestamp = str(int(time.time()))
            signature = _generate_signature("test-secret-123", payload, timestamp)

            response = client.post(
                "/api/v1/data-source/proxy/yfinance",
                json=payload,
                headers={"X-Data-Source-Signature": signature, "X-Data-Source-Timestamp": timestamp},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["success"] is True

    @patch("backend.routers.data_source._HMAC_SECRET", "test-secret-123")
    @patch("backend.routers.data_source._allowed_ip_set", set())
    def test_proxy_with_invalid_signature(self):
        payload = {"ticker": "AAPL", "fetch_type": "quote"}
        timestamp = str(int(time.time()))

        response = client.post(
            "/api/v1/data-source/proxy/yfinance",
            json=payload,
            headers={"X-Data-Source-Signature": "invalid-signature", "X-Data-Source-Timestamp": timestamp},
        )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["msg"]

    @patch("backend.routers.data_source._HMAC_SECRET", "test-secret-123")
    @patch("backend.routers.data_source._allowed_ip_set", set())
    def test_proxy_missing_signature(self):
        payload = {"ticker": "AAPL", "fetch_type": "quote"}
        timestamp = str(int(time.time()))

        response = client.post(
            "/api/v1/data-source/proxy/yfinance", json=payload, headers={"X-Data-Source-Timestamp": timestamp}
        )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["msg"]

    @patch("backend.routers.data_source._HMAC_SECRET", "test-secret-123")
    @patch("backend.routers.data_source._allowed_ip_set", set())
    def test_proxy_expired_timestamp(self):
        payload = {"ticker": "AAPL", "fetch_type": "quote"}
        expired_timestamp = str(int(time.time()) - 400)
        signature = _generate_signature("test-secret-123", payload, expired_timestamp)

        response = client.post(
            "/api/v1/data-source/proxy/yfinance",
            json=payload,
            headers={"X-Data-Source-Signature": signature, "X-Data-Source-Timestamp": expired_timestamp},
        )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["msg"]

    @patch("backend.routers.data_source._HMAC_SECRET", "")
    @patch("backend.routers.data_source._allowed_ip_set", set())
    def test_proxy_no_secret_bypasses_verification(self):
        response = client.post("/api/v1/data-source/proxy/yfinance", json={"ticker": "AAPL", "fetch_type": "unknown"})
        assert response.status_code == 200
