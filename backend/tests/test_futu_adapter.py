"""
FutuAdapter 单元测试
覆盖: backend/adapters/futu/futu_adapter.py
"""

import time
from unittest.mock import MagicMock

import pytest

from backend.adapters.futu.futu_adapter import FutuAdapter


@pytest.fixture
def adapter():
    """创建一个未连接的 FutuAdapter 实例"""
    return FutuAdapter(host="127.0.0.1", port=11111)


@pytest.fixture
def connected_adapter():
    """创建一个已连接的 FutuAdapter 实例"""
    a = FutuAdapter(host="127.0.0.1", port=11111)
    a._connected = True
    return a


class TestProtocolProperties:
    def test_name(self, adapter):
        assert adapter.name == "futu"

    def test_version(self, adapter):
        assert adapter.version == "1.0.0"

    def test_capabilities(self, adapter):
        caps = adapter.capabilities
        assert "quote" in caps
        assert "history" in caps
        assert "fund_flow" in caps
        assert "option_chain" in caps
        assert "subscribe_quote" in caps

    def test_is_available_not_connected(self, adapter):
        assert adapter.is_available is False

    def test_is_available_connected(self, connected_adapter):
        assert connected_adapter.is_available is True

    def test_is_available_rate_limited(self, connected_adapter):
        connected_adapter._rate_limited_until = time.time() + 100
        assert connected_adapter.is_available is False


class TestFetch:
    def test_unsupported_action(self, connected_adapter):
        result = connected_adapter.fetch("invalid_action", {})
        assert result.is_error()
        assert "Unsupported action" in result.error

    def test_not_connected_returns_degraded(self, adapter):
        result = adapter.fetch("quote", {"ticker": "HK.00700"})
        assert result.status == "degraded"

    def test_rate_limited(self, connected_adapter):
        connected_adapter._rate_limited_until = time.time() + 100
        result = connected_adapter.fetch("quote", {"ticker": "HK.00700"})
        # is_available 为 False 时返回 degraded
        assert result.status == "degraded"

    def test_fetch_quote_success(self, connected_adapter):
        result = connected_adapter.fetch("quote", {"ticker": "HK.00700"})
        assert result.is_success()
        assert result.data is not None
        assert result.data["ticker"] == "HK.00700"
        assert "price" in result.data
        assert result.latency_ms >= 0
        assert result.source.startswith("futu-")

    def test_fetch_quote_missing_ticker(self, connected_adapter):
        result = connected_adapter.fetch("quote", {})
        assert result.is_error()
        assert "Missing ticker" in result.error

    def test_fetch_history_success(self, connected_adapter):
        result = connected_adapter.fetch("history", {"ticker": "HK.00700", "num": 5})
        assert result.is_success()
        assert len(result.data) == 5
        assert "open" in result.data[0]
        assert "close" in result.data[0]

    def test_fetch_history_missing_ticker(self, connected_adapter):
        result = connected_adapter.fetch("history", {})
        assert result.is_error()

    def test_fetch_fund_flow_success(self, connected_adapter):
        result = connected_adapter.fetch("fund_flow", {"ticker": "HK.00700"})
        assert result.is_success()

    def test_fetch_fund_flow_missing_ticker(self, connected_adapter):
        result = connected_adapter.fetch("fund_flow", {})
        assert result.is_error()

    def test_fetch_option_chain_success(self, connected_adapter):
        result = connected_adapter.fetch("option_chain", {"underlying_ticker": "HK.09988"})
        assert result.is_success()

    def test_fetch_option_chain_missing_ticker(self, connected_adapter):
        result = connected_adapter.fetch("option_chain", {})
        assert result.is_error()

    def test_fetch_exception_handling(self, connected_adapter):
        """模拟内部方法抛出异常"""
        connected_adapter._fetch_quote = MagicMock(side_effect=RuntimeError("boom"))
        result = connected_adapter.fetch("quote", {"ticker": "HK.00700"})
        assert result.is_error()
        assert "boom" in result.error


class TestSubscribe:
    def test_subscribe_valid(self, connected_adapter):
        sub_id = connected_adapter.subscribe("subscribe_quote", {"tickers": ["HK.00700"]}, lambda x: x)
        assert sub_id.startswith("sub_")

    def test_subscribe_invalid_action(self, connected_adapter):
        with pytest.raises(ValueError, match="subscribe_quote"):
            connected_adapter.subscribe("invalid", {}, lambda x: x)

    def test_unsubscribe(self, connected_adapter):
        assert connected_adapter.unsubscribe("sub_12345") is True


class TestConnection:
    def test_connect_success(self, adapter):
        assert adapter._connect() is True
        assert adapter._connected is True

    def test_connect_already_connected(self, connected_adapter):
        assert connected_adapter._connect() is True


class TestRateLimiting:
    def test_is_rate_limited_false(self, adapter):
        assert adapter._is_rate_limited is False

    def test_is_rate_limited_expired(self, adapter):
        adapter._rate_limited_until = time.time() - 1
        assert adapter._is_rate_limited is False

    def test_is_rate_limited_active(self, adapter):
        adapter._rate_limited_until = time.time() + 100
        assert adapter._is_rate_limited is True

    def test_record_request_increments(self, connected_adapter):
        connected_adapter._record_request()
        assert connected_adapter._request_count == 1
        assert connected_adapter._last_request_time is not None

    def test_reset_request_count(self, connected_adapter):
        connected_adapter._request_count = 50
        connected_adapter._rate_limited_until = time.time() + 100
        connected_adapter._reset_request_count()
        assert connected_adapter._request_count == 0
        assert connected_adapter._rate_limited_until is None


class TestHealthCheck:
    def test_health_check_success(self, adapter):
        result = adapter.health_check()
        assert result["healthy"] is True
        assert "latency_ms" in result

    def test_health_check_connect_failure(self, adapter):
        adapter._connect = MagicMock(return_value=False)
        result = adapter.health_check()
        assert result["healthy"] is False
        assert "error" in result
