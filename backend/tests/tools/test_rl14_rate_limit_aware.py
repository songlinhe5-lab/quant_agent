"""
RL-14: Hermes Agent Tool 限流感知智能重试单测
==============================================

验证:
- _is_rate_limit_response: HTTP 429/503 + 响应体关键词检测
- _extract_retry_after: Retry-After 头 / X-RateLimit-Reset 头 / 响应体 / 默认值
- rate_limit_aware_request: 成功直通 / 限流重试后成功 / 重试耗尽返回结构化错误 / 非限流错误直接返回 / 异常重试
- 集成 BrokerMarketTool: 限流场景端到端
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_agent.tools.base import BaseTool

# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def tool():
    return BaseTool()


def _make_response(status_code=200, json_data=None, headers=None, text=""):
    """构造模拟 HTTP 响应"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or str(json_data)
    resp.headers = headers or {}
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ─────────────────────────────────────────
# _is_rate_limit_response
# ─────────────────────────────────────────


class TestIsRateLimitResponse:
    def test_http_429_detected(self, tool):
        resp = _make_response(status_code=429)
        assert tool._is_rate_limit_response(resp) is True

    def test_http_503_detected(self, tool):
        resp = _make_response(status_code=503)
        assert tool._is_rate_limit_response(resp) is True

    def test_http_200_with_rate_limited_status(self, tool):
        resp = _make_response(status_code=200, json_data={"status": "rate_limited"})
        assert tool._is_rate_limit_response(resp) is True

    def test_http_200_with_throttled_status(self, tool):
        resp = _make_response(status_code=200, json_data={"status": "throttled"})
        assert tool._is_rate_limit_response(resp) is True

    def test_http_200_normal_not_detected(self, tool):
        resp = _make_response(status_code=200, json_data={"status": "success"})
        assert tool._is_rate_limit_response(resp) is False

    def test_http_400_not_detected(self, tool):
        resp = _make_response(status_code=400, json_data={"detail": "bad request"})
        assert tool._is_rate_limit_response(resp) is False

    def test_http_500_not_detected(self, tool):
        resp = _make_response(status_code=500)
        assert tool._is_rate_limit_response(resp) is False


# ─────────────────────────────────────────
# _extract_retry_after
# ─────────────────────────────────────────


class TestExtractRetryAfter:
    def test_retry_after_header(self, tool):
        resp = _make_response(status_code=429, headers={"Retry-After": "30"})
        assert tool._extract_retry_after(resp) == 30.0

    def test_retry_after_header_invalid(self, tool):
        resp = _make_response(status_code=429, headers={"Retry-After": "invalid"})
        # 应 fallback 到默认值
        assert tool._extract_retry_after(resp) == tool._DEFAULT_RETRY_DELAY

    def test_x_ratelimit_reset_header(self, tool):
        future_ts = time.time() + 45
        resp = _make_response(status_code=429, headers={"X-RateLimit-Reset": str(future_ts)})
        result = tool._extract_retry_after(resp)
        assert 40 < result <= 45

    def test_x_ratelimit_reset_past(self, tool):
        past_ts = time.time() - 10
        resp = _make_response(status_code=429, headers={"X-RateLimit-Reset": str(past_ts)})
        # 已过期的 reset 时间应 fallback
        assert tool._extract_retry_after(resp) == tool._DEFAULT_RETRY_DELAY

    def test_retry_after_in_body(self, tool):
        resp = _make_response(
            status_code=429,
            json_data={"retry_after_seconds": 20, "message": "rate limited"},
        )
        assert tool._extract_retry_after(resp) == 20.0

    def test_retry_after_in_body_alt_key(self, tool):
        resp = _make_response(
            status_code=429,
            json_data={"retry_after": 15},
        )
        assert tool._extract_retry_after(resp) == 15.0

    def test_no_headers_no_body_returns_default(self, tool):
        resp = _make_response(status_code=429)
        assert tool._extract_retry_after(resp) == tool._DEFAULT_RETRY_DELAY

    def test_header_priority_over_body(self, tool):
        """Retry-After 头优先于响应体"""
        resp = _make_response(
            status_code=429,
            json_data={"retry_after_seconds": 20},
            headers={"Retry-After": "10"},
        )
        assert tool._extract_retry_after(resp) == 10.0


# ─────────────────────────────────────────
# rate_limit_aware_request
# ─────────────────────────────────────────


class TestRateLimitAwareRequest:
    @pytest.mark.asyncio
    async def test_success_returns_json(self, tool):
        """成功请求直接返回 JSON"""
        client = AsyncMock()
        resp = _make_response(status_code=200, json_data={"status": "success", "data": [1, 2, 3]})
        client.request.return_value = resp

        result = await tool.rate_limit_aware_request(client, "GET", "http://test/api")
        assert result == {"status": "success", "data": [1, 2, 3]}
        assert client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_retry_then_success(self, tool):
        """限流后重试成功"""
        client = AsyncMock()
        rate_limit_resp = _make_response(
            status_code=429,
            json_data={"retry_after_seconds": 0.01},
            headers={"Retry-After": "0.01"},
        )
        success_resp = _make_response(status_code=200, json_data={"status": "success"})
        client.request.side_effect = [rate_limit_resp, success_resp]

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool.rate_limit_aware_request(client, "GET", "http://test/api")

        assert result == {"status": "success"}
        assert client.request.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_exhausted_returns_structured_error(self, tool):
        """重试耗尽返回结构化限流错误"""
        client = AsyncMock()
        rate_limit_resp = _make_response(
            status_code=429,
            headers={"Retry-After": "0.01"},
        )
        client.request.return_value = rate_limit_resp

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock):
            result = await tool.rate_limit_aware_request(client, "GET", "http://test/api", max_retries=2)

        assert result["status"] == "rate_limited"
        assert "retry_after_seconds" in result
        assert result["attempts"] == 3  # 0 + 2 retries
        assert client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_returns_immediately(self, tool):
        """非限流类错误直接返回，不重试"""
        client = AsyncMock()
        error_resp = _make_response(
            status_code=400,
            json_data={"detail": "Bad Request"},
        )
        client.request.return_value = error_resp

        result = await tool.rate_limit_aware_request(client, "GET", "http://test/api")

        assert result["status"] == "error"
        assert "400" in result["message"]
        assert client.request.call_count == 1  # 不重试

    @pytest.mark.asyncio
    async def test_exception_with_retry(self, tool):
        """请求异常时指数退避重试"""
        client = AsyncMock()
        client.request.side_effect = [
            ConnectionError("Connection refused"),
            _make_response(status_code=200, json_data={"status": "success"}),
        ]

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool.rate_limit_aware_request(client, "GET", "http://test/api")

        assert result == {"status": "success"}
        assert client.request.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_exhausted(self, tool):
        """异常重试耗尽"""
        client = AsyncMock()
        client.request.side_effect = ConnectionError("Connection refused")

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock):
            result = await tool.rate_limit_aware_request(client, "GET", "http://test/api", max_retries=1)

        assert result["status"] == "error"
        assert "重试 1 次" in result["message"]
        assert client.request.call_count == 2  # 1 initial + 1 retry

    @pytest.mark.asyncio
    async def test_max_retry_delay_capped(self, tool):
        """重试延迟不超过 MAX_RETRY_DELAY"""
        client = AsyncMock()
        rate_limit_resp = _make_response(
            status_code=429,
            headers={"Retry-After": "9999"},  # 超大延迟
        )
        success_resp = _make_response(status_code=200, json_data={"status": "success"})
        client.request.side_effect = [rate_limit_resp, success_resp]

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool.rate_limit_aware_request(client, "GET", "http://test/api")

        assert result["status"] == "success"
        # 验证 sleep 被调用时延迟被 cap 到 MAX_RETRY_DELAY
        call_args = mock_sleep.call_args[0][0]
        assert call_args <= tool._MAX_RETRY_DELAY

    @pytest.mark.asyncio
    async def test_zero_max_retries(self, tool):
        """max_retries=0 不重试"""
        client = AsyncMock()
        rate_limit_resp = _make_response(status_code=429, headers={"Retry-After": "10"})
        client.request.return_value = rate_limit_resp

        result = await tool.rate_limit_aware_request(client, "GET", "http://test/api", max_retries=0)

        assert result["status"] == "rate_limited"
        assert client.request.call_count == 1


# ─────────────────────────────────────────
# BrokerMarketTool 集成测试
# ─────────────────────────────────────────


class TestBrokerMarketToolIntegration:
    @pytest.mark.asyncio
    async def test_broker_tool_rate_limit_returns_structured(self):
        """BrokerMarketTool 限流场景端到端"""
        from hermes_agent.tools.broker_market_tool import BrokerMarketTool

        tool = BrokerMarketTool()
        rate_limit_resp = _make_response(
            status_code=429,
            headers={"Retry-After": "0.01"},
        )

        mock_client = AsyncMock()
        mock_client.request.return_value = rate_limit_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("hermes_agent.tools.base.asyncio.sleep", new_callable=AsyncMock):
            with patch("hermes_agent.tools.broker_market_tool.SecureAsyncClient", return_value=mock_client):
                result = await tool.run(action="QUOTE", ticker="AAPL")

        assert result["status"] == "rate_limited"
        assert "retry_after_seconds" in result

    @pytest.mark.asyncio
    async def test_broker_tool_success(self):
        """BrokerMarketTool 正常请求"""
        from hermes_agent.tools.broker_market_tool import BrokerMarketTool

        tool = BrokerMarketTool()
        success_resp = _make_response(
            status_code=200,
            json_data={"status": "success", "price": 150.0},
        )

        mock_client = AsyncMock()
        mock_client.request.return_value = success_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("hermes_agent.tools.broker_market_tool.SecureAsyncClient", return_value=mock_client):
            result = await tool.run(action="QUOTE", ticker="AAPL")

        assert result["status"] == "success"
        assert result["price"] == 150.0
