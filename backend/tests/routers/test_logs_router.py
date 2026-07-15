"""
FE-05b: 前端日志路由单元测试
"""

from unittest.mock import MagicMock, patch

import pytest


class TestLogsRouterPost:
    """POST /api/v1/logs 接收前端日志"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock 数据库会话"""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.bulk_save_objects = MagicMock()
        session.commit = MagicMock()
        return session

    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI Request"""
        req = MagicMock()
        req.headers = {
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "referer": "https://quant.stephenhe.com/data-center",
        }
        return req

    @pytest.mark.asyncio
    async def test_receive_logs_success(self, mock_db_session, mock_request):
        """正常路径：批量接收日志并写入数据库"""
        from backend.routers.logs import LogBatchSchema, LogEntrySchema, receive_frontend_logs

        with patch("backend.core.database.SessionLocal", return_value=mock_db_session):
            body = LogBatchSchema(
                logs=[
                    LogEntrySchema(
                        timestamp="2026-07-14T14:00:00.000Z",
                        level=2,
                        message="Test warning message",
                        context={"page": "data-center"},
                    ),
                    LogEntrySchema(
                        timestamp="2026-07-14T14:00:01.000Z",
                        level=3,
                        message="Test error message",
                        error={"name": "TypeError", "message": "Cannot read property"},
                    ),
                ]
            )

            result = await receive_frontend_logs(body, mock_request, username="testuser")

            assert result["status"] == "success"
            assert result["data"]["received"] == 2
            mock_db_session.bulk_save_objects.assert_called_once()
            mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_logs_level_mapping(self, mock_db_session, mock_request):
        """级别映射：0=DEBUG, 1=INFO, 2=WARN, 3=ERROR"""
        from backend.routers.logs import LogBatchSchema, LogEntrySchema, receive_frontend_logs

        with patch("backend.core.database.SessionLocal", return_value=mock_db_session):
            body = LogBatchSchema(
                logs=[
                    LogEntrySchema(timestamp="2026-07-14T14:00:00Z", level=0, message="debug msg"),
                    LogEntrySchema(timestamp="2026-07-14T14:00:01Z", level=1, message="info msg"),
                    LogEntrySchema(timestamp="2026-07-14T14:00:02Z", level=2, message="warn msg"),
                    LogEntrySchema(timestamp="2026-07-14T14:00:03Z", level=3, message="error msg"),
                ]
            )

            await receive_frontend_logs(body, mock_request, username=None)

            call_args = mock_db_session.bulk_save_objects.call_args[0][0]
            levels = [r.level for r in call_args]
            assert levels == ["DEBUG", "INFO", "WARN", "ERROR"]

    @pytest.mark.asyncio
    async def test_receive_logs_empty_context(self, mock_db_session, mock_request):
        """可选字段：context 和 error 可以为 None"""
        from backend.routers.logs import LogBatchSchema, LogEntrySchema, receive_frontend_logs

        with patch("backend.core.database.SessionLocal", return_value=mock_db_session):
            body = LogBatchSchema(
                logs=[
                    LogEntrySchema(timestamp="2026-07-14T14:00:00Z", level=1, message="simple msg"),
                ]
            )

            result = await receive_frontend_logs(body, mock_request, username=None)
            assert result["data"]["received"] == 1


class TestLogsRouterGet:
    """GET /api/v1/logs 查询前端日志"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock 数据库会话"""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        return session

    @pytest.mark.asyncio
    async def test_query_logs_success(self, mock_db_session):
        """正常路径：查询日志并返回分页结果"""
        from datetime import datetime, timezone

        from backend.core.models import FrontendLog
        from backend.routers.logs import query_frontend_logs

        mock_log = MagicMock(spec=FrontendLog)
        mock_log.id = 1
        mock_log.timestamp = datetime(2026, 7, 14, 14, 0, 0, tzinfo=timezone.utc)
        mock_log.level = "ERROR"
        mock_log.message = "Test error"
        mock_log.context = {"page": "quotes"}
        mock_log.page_url = "https://quant.stephenhe.com/quotes"
        mock_log.user_agent = "Mozilla/5.0"

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.all.return_value = [mock_log]
        mock_db_session.query.return_value = mock_query

        with patch("backend.core.database.SessionLocal", return_value=mock_db_session):
            result = await query_frontend_logs(
                level="ERROR", since=None, until=None, limit=100, offset=0, username="testuser"
            )

            assert result["status"] == "success"
            assert result["data"]["total"] == 1
            assert len(result["data"]["items"]) == 1
            assert result["data"]["items"][0]["level"] == "ERROR"

    @pytest.mark.asyncio
    async def test_query_logs_invalid_level(self):
        """无效 level 参数返回 400"""
        from fastapi import HTTPException

        from backend.routers.logs import query_frontend_logs

        with pytest.raises(HTTPException) as exc_info:
            await query_frontend_logs(
                level="INVALID", since=None, until=None, limit=100, offset=0, username=None
            )
        assert exc_info.value.status_code == 400
