"""
Tests for backend/services/data_source_router.py

Coverage targets:
- DataSourceNode dataclass
- DataSourceRouter initialization
- HMAC signature generation
- HTTP client lazy loading
- Node selection and health filtering
- Circuit breaker mechanism
- YFinance fetch (local + remote)
- AKShare fetch (local + remote)
- Health status endpoint
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.data_source_router import DataSourceNode, DataSourceRouter


@pytest.fixture
def router_disabled():
    with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
        yield DataSourceRouter()


@pytest.fixture
def router_enabled():
    with patch.dict(os.environ, {
        "DATA_SOURCE_ROUTER_ENABLED": "true",
        "YF_PRIMARY_NODE_URL": "http://localhost:8000",
        "YF_BACKUP_NODE_URL": "http://10.0.0.2:8000",
        "AKSHARE_REMOTE_URL": "http://10.0.0.3:8000",
        "DATA_SOURCE_HMAC_SECRET": "test_secret_123",
    }):
        yield DataSourceRouter()


class TestDataSourceNode:

    def test_node_initialization(self):
        node = DataSourceNode(name="test", url="http://localhost:8000")
        assert node.name == "test"
        assert node.url == "http://localhost:8000"
        assert node.enabled is True
        assert node.weight == 10
        assert node.status == "healthy"
        assert node.error_count == 0

    def test_node_with_capabilities(self):
        node = DataSourceNode(
            name="test",
            url="http://localhost:8000",
            capabilities=["yfinance", "quote"],
            weight=5,
        )
        assert "yfinance" in node.capabilities
        assert node.weight == 5


class TestDataSourceRouterInit:

    def test_router_disabled_by_default(self, router_disabled):
        assert router_disabled._enabled is False

    def test_router_enabled_with_env(self, router_enabled):
        assert router_enabled._enabled is True

    def test_nodes_initialization(self, router_enabled):
        assert "yf_primary" in router_enabled._nodes
        assert "yf_backup" in router_enabled._nodes
        assert "akshare_remote" in router_enabled._nodes

    def test_nodes_capabilities(self, router_enabled):
        yf_primary = router_enabled._nodes["yf_primary"]
        assert "yfinance" in yf_primary.capabilities

        akshare = router_enabled._nodes["akshare_remote"]
        assert "akshare" in akshare.capabilities


class TestHmacSignature:

    def test_sign_request_with_secret(self, router_enabled):
        payload = {"ticker": "AAPL", "fetch_type": "quote"}
        timestamp = "1234567890"
        signature = router_enabled._sign_request(payload, timestamp)
        assert isinstance(signature, str)
        assert len(signature) == 64

    def test_sign_request_without_secret(self, router_disabled):
        payload = {"ticker": "AAPL"}
        signature = router_disabled._sign_request(payload, "1234567890")
        assert signature == ""

    def test_sign_request_consistent(self, router_enabled):
        payload = {"key": "value", "num": 123}
        timestamp = "1234567890"
        sig1 = router_enabled._sign_request(payload, timestamp)
        sig2 = router_enabled._sign_request(payload, timestamp)
        assert sig1 == sig2

    def test_sign_request_with_timestamp(self, router_enabled):
        payload = {"ticker": "AAPL"}
        sig1 = router_enabled._sign_request(payload, "1234567890")
        sig2 = router_enabled._sign_request(payload, "0987654321")
        assert sig1 != sig2


class TestHttpClientLazyLoading:

    def test_http_client_none_initially(self, router_enabled):
        assert router_enabled._http_client is None

    def test_http_client_created_on_first_use(self, router_enabled):
        router_enabled._ensure_http_client()
        assert router_enabled._http_client is not None


class TestNodeHealthFiltering:

    def test_get_healthy_nodes(self, router_enabled):
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert len(nodes) >= 1

    def test_get_healthy_nodes_with_circuit_breaker(self, router_enabled):
        router_enabled._nodes["yf_primary"].circuit_breaker_until = time.time() + 3600
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert router_enabled._nodes["yf_primary"] not in nodes

    def test_get_healthy_nodes_unhealthy_status(self, router_enabled):
        router_enabled._nodes["yf_primary"].status = "unhealthy"
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert router_enabled._nodes["yf_primary"] not in nodes

    def test_select_node_priority(self, router_enabled):
        router_enabled._nodes["yf_primary"].weight = 10
        router_enabled._nodes["yf_backup"].weight = 5
        node = asyncio.run(router_enabled._select_node("yfinance"))
        assert node.name == "yf_primary"


class TestCircuitBreaker:

    def test_update_node_status_success(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=True))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count == 0
        assert node.status == "healthy"

    def test_update_node_status_failure(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="test"))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count == 1
        assert node.status == "healthy"

    def test_circuit_breaker_triggered(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err1"))
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err2"))
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err3"))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count >= 3
        assert node.status == "unhealthy"
        assert node.circuit_breaker_until > time.time()


class TestFetchYFinance:

    @patch("backend.services.yfinance_service.YFinanceService.get_batched_quote")
    def test_fetch_yfinance_disabled_router(self, mock_method, router_disabled):
        mock_method.return_value = {"success": True, "data": {}}
        result = asyncio.run(router_disabled.fetch_yfinance("AAPL", "quote"))
        assert result["success"] is True
        mock_method.assert_called_once()

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_yfinance_remote_success(self, mock_send, router_enabled):
        mock_send.return_value = {"success": True, "data": {"price": 165.0}}
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert result["data"]["price"] == 165.0

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_yfinance_rate_limit_switch(self, mock_send, router_enabled):
        mock_send.side_effect = [
            {"success": False, "message": "429 Rate Limit"},
            {"success": True, "data": {"price": 165.0}},
        ]
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert mock_send.call_count == 2

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    @patch("backend.services.yfinance_service.YFinanceService.fetch_yf_data")
    def test_fetch_yfinance_fallback_local(self, mock_method, mock_send, router_enabled):
        mock_send.side_effect = Exception("Network error")
        mock_method.return_value = (True, {"price": 165.0}, "")
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True


class TestFetchAKShare:

    @patch("backend.services.akshare_service.AKShareService.get_southbound_flow")
    def test_fetch_akshare_disabled_router(self, mock_method, router_disabled):
        mock_method.return_value = {"status": "success", "data": {}}
        result = asyncio.run(router_disabled.fetch_akshare("southbound"))
        assert result["status"] == "success"

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_akshare_remote_success(self, mock_send, router_enabled):
        mock_send.return_value = {"status": "success", "data": {"flow": 100}}
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "success"

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    @patch("backend.services.akshare_service.AKShareService.get_southbound_flow")
    def test_fetch_akshare_fallback_local(self, mock_method, mock_send, router_enabled):
        mock_send.side_effect = Exception("Connection refused")
        mock_method.return_value = {"status": "success", "data": {}}
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "success"


class TestHealthStatus:

    def test_get_health_status(self, router_enabled):
        status = asyncio.run(router_enabled.get_health_status())
        assert status["router_enabled"] is True
        assert "yf_primary" in status["nodes"]
        assert "akshare_remote" in status["nodes"]


class TestClose:

    def test_close_http_client(self, router_enabled):
        router_enabled._ensure_http_client()
        assert router_enabled._http_client is not None
        asyncio.run(router_enabled.close())