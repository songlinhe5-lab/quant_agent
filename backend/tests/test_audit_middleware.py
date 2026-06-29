"""审计中间件单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch


class TestAuditMiddleware:
    """审计日志中间件测试"""

    async def test_get_request_passes_through_without_audit(self):
        """测试 GET 请求不触发审计直接放行"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/v1/auth/login"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        result = await audit_middleware(request, call_next)
        assert result is response
        assert call_next.called

    async def test_non_auditable_post_path_passes_through(self):
        """测试 POST 到非审计路径直接放行"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/health"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        result = await audit_middleware(request, call_next)
        assert result is response

    async def test_auditable_path_success_triggers_log_audit(self):
        """测试审计路径成功响应触发审计日志写入"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/auth/login"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        mock_db = MagicMock()
        with patch("backend.middleware.audit_middleware.get_db", return_value=iter([mock_db])):
            with patch("backend.middleware.audit_middleware.log_audit") as mock_log:
                result = await audit_middleware(request, call_next)
                assert result is response
                assert mock_log.called

    async def test_auditable_path_error_status_skips_audit(self):
        """测试审计路径错误响应不触发审计"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/auth/login"
        response = MagicMock()
        response.status_code = 500
        call_next = AsyncMock(return_value=response)
        with patch("backend.middleware.audit_middleware.log_audit") as mock_log:
            result = await audit_middleware(request, call_next)
            assert result is response
            assert not mock_log.called

    async def test_audit_log_exception_does_not_break_request(self):
        """测试审计日志写入异常不影响主请求响应"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "DELETE"
        request.url.path = "/api/v1/auth/logout"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        mock_db = MagicMock()
        with patch("backend.middleware.audit_middleware.get_db", return_value=iter([mock_db])):
            with patch("backend.middleware.audit_middleware.log_audit", side_effect=Exception("DB down")):
                result = await audit_middleware(request, call_next)
                assert result is response

    async def test_put_request_auditable_path_triggers_audit(self):
        """测试 PUT 请求审计路径触发审计"""
        from backend.middleware.audit_middleware import audit_middleware

        request = MagicMock()
        request.method = "PUT"
        request.url.path = "/api/v1/settings"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        mock_db = MagicMock()
        with patch("backend.middleware.audit_middleware.get_db", return_value=iter([mock_db])):
            with patch("backend.middleware.audit_middleware.log_audit") as mock_log:
                result = await audit_middleware(request, call_next)
                assert result is response
                assert mock_log.called
