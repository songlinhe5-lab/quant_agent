"""
HTTP 中间件单元测试

覆盖：
- AccessLogMiddleware 请求日志记录
- Prometheus 指标收集
- 异常处理路径
- httpx 外部 API 监控
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.core.middleware import (
    EXTERNAL_API_COUNT,
    EXTERNAL_API_LATENCY,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    AccessLogMiddleware,
    httpx_log_request,
    httpx_log_response,
)


class TestAccessLogMiddleware:
    """AccessLogMiddleware 中间件测试"""

    @pytest.fixture
    def middleware(self):
        """创建中间件实例"""
        return AccessLogMiddleware(app=MagicMock())

    @pytest.fixture
    def mock_request(self):
        """创建 mock Request"""
        request = MagicMock(spec=Request)
        request.method = "GET"
        request.url.path = "/api/test"
        request.scope = {}
        return request

    @pytest.fixture
    def mock_call_next(self):
        """创建 mock call_next 函数"""
        async def call_next(request: Request):
            return JSONResponse(content={"status": "ok"}, status_code=200)
        return call_next

    @pytest.mark.asyncio
    async def test_dispatch_success(self, middleware, mock_request, mock_call_next):
        """测试正常请求处理"""
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_with_route(self, middleware, mock_request, mock_call_next):
        """测试带路由信息的请求"""
        # 模拟已匹配的路由
        mock_route = MagicMock()
        mock_route.path = "/api/test/{id}"
        mock_request.scope["route"] = mock_route

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_unmatched_route(self, middleware, mock_request, mock_call_next):
        """测试未匹配路由的请求"""
        mock_request.scope = {}  # 没有 route

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_exception(self, middleware, mock_request):
        """测试请求处理异常"""
        async def call_next_with_error(request: Request):
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await middleware.dispatch(mock_request, call_next_with_error)

    @pytest.mark.asyncio
    async def test_dispatch_calls_prometheus_metrics(self, middleware, mock_request, mock_call_next):
        """测试 Prometheus 指标被调用"""
        with patch("backend.core.middleware.REQUEST_COUNT") as mock_counter, \
             patch("backend.core.middleware.REQUEST_LATENCY") as mock_histogram:
            response = await middleware.dispatch(mock_request, mock_call_next)

            assert response.status_code == 200
            # 验证 Prometheus 指标被调用
            mock_counter.labels.assert_called()
            mock_counter.labels.return_value.inc.assert_called_once()
            mock_histogram.labels.assert_called()
            mock_histogram.labels.return_value.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_exception_calls_prometheus_metrics(self, middleware, mock_request):
        """测试异常时 Prometheus 指标被调用"""
        async def call_next_with_error(request: Request):
            raise ValueError("Test error")

        with patch("backend.core.middleware.REQUEST_COUNT") as mock_counter, \
             patch("backend.core.middleware.REQUEST_LATENCY") as mock_histogram:
            with pytest.raises(ValueError):
                await middleware.dispatch(mock_request, call_next_with_error)

            # 验证异常时被记录为 500
            mock_counter.labels.assert_called_with(method="GET", endpoint="UNMATCHED_ROUTE", http_status=500)
            mock_counter.labels.return_value.inc.assert_called_once()


class TestHttpxMonitoring:
    """httpx 外部 API 监控测试"""

    def test_httpx_log_request(self):
        """测试请求时间记录"""
        mock_request = httpx.Request("GET", "https://api.test.com")
        
        # 调用前确保字典为空
        from backend.core.middleware import _request_timers
        _request_timers.clear()
        
        # 直接调用异步函数
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_request(mock_request))
        
        # 验证时间被记录
        assert id(mock_request) in _request_timers

    def test_httpx_log_response_finnhub(self):
        """测试 Finnhub API 响应监控"""
        mock_request = MagicMock()
        mock_request.url.host = "finnhub.io"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))

    def test_httpx_log_response_fred(self):
        """测试 FRED API 响应监控"""
        mock_request = MagicMock()
        mock_request.url.host = "stlouisfed.org"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))

    def test_httpx_log_response_yahoo(self):
        """测试 Yahoo Finance API 响应监控"""
        mock_request = MagicMock()
        mock_request.url.host = "yahoo.com"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))

    def test_httpx_log_response_llm(self):
        """测试 LLM API 响应监控"""
        mock_request = MagicMock()
        mock_request.url.host = "api.openai.com"
        mock_request.method = "POST"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))

    def test_httpx_log_response_unknown_service(self):
        """测试未知服务名的处理"""
        mock_request = MagicMock()
        mock_request.url.host = "unknown-service.com"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        import asyncio
        asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))

    def test_httpx_log_response_slow_api(self):
        """测试慢速 API 警告日志"""
        mock_request = MagicMock()
        mock_request.url.host = "finnhub.io"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        # 模拟慢请求（> 3秒）
        from backend.core.middleware import _request_timers
        # 创建一个真实的 httpx.Request 对象
        real_request = httpx.Request("GET", "https://finnhub.io/api/test")
        mock_response.request = real_request
        _request_timers[id(real_request)] = time.perf_counter() - 4.0  # 4秒前
        
        import asyncio
        with patch("backend.core.middleware.logger") as mock_logger:
            asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))
            # 验证警告日志被调用
            mock_logger.warning.assert_called()

    def test_httpx_log_response_fast_api(self):
        """测试快速 API 不触发警告"""
        mock_request = MagicMock()
        mock_request.url.host = "finnhub.io"
        mock_request.method = "GET"
        
        mock_response = MagicMock()
        mock_response.request = mock_request
        mock_response.status_code = 200
        
        # 模拟快速请求（< 3秒）
        from backend.core.middleware import _request_timers
        real_request = httpx.Request("GET", "https://finnhub.io/api/test")
        mock_response.request = real_request
        _request_timers[id(real_request)] = time.perf_counter() - 1.0  # 1秒前
        
        import asyncio
        with patch("backend.core.middleware.logger") as mock_logger:
            asyncio.get_event_loop().run_until_complete(httpx_log_response(mock_response))
            # 验证警告日志未被调用
            mock_logger.warning.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
