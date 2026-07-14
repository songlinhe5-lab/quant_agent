"""
服务层逻辑单元测试
覆盖: strategy_parser, notification_service, search_service, system_monitor_service, llm_service
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


# ─── strategy_parser.py ─────────────────────────────────────────────
class TestStrategyParser:
    SAMPLE_STRATEGY = '''
class MyStrategy:
    """A test strategy"""
    def __init__(self, fast_ma: int = 10, slow_ma: int = 20, pos_size: float = 1.0):
        """
        :param fast_ma: 快速均线周期
        :param slow_ma: 慢速均线周期
        :param pos_size: 仓位大小
        """
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
'''

    def test_parse_valid_strategy(self):
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(self.SAMPLE_STRATEGY)
        assert result["status"] == "success"
        assert len(result["data"]) == 1
        params = result["data"][0]["parameters"]
        assert len(params) == 3
        param_names = [p["name"] for p in params]
        assert "fast_ma" in param_names
        assert "slow_ma" in param_names

    def test_parse_strategy_with_defaults(self):
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(self.SAMPLE_STRATEGY)
        params = {p["name"]: p for p in result["data"][0]["parameters"]}
        assert params["fast_ma"]["default"] == 10
        assert params["fast_ma"]["type"] == "int"
        assert params["pos_size"]["type"] == "float"

    def test_parse_strategy_descriptions(self):
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(self.SAMPLE_STRATEGY)
        params = {p["name"]: p for p in result["data"][0]["parameters"]}
        assert "快速均线" in params["fast_ma"]["description"]

    def test_parse_syntax_error(self):
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters("def bad syntax {{{")
        assert result["status"] == "error"

    def test_parse_no_strategy_class(self):
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters("x = 1\ny = 2")
        assert result["status"] == "error"

    def test_parse_google_style_docstring(self):
        code = '''
class TestBot:
    def __init__(self, period=14):
        """
        period (int): 回看周期
        """
        pass
'''
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(code)
        assert result["status"] == "success"
        params = result["data"][0]["parameters"]
        assert params[0]["name"] == "period"
        assert params[0]["default"] == 14

    def test_parse_strategy_with_type_hints(self):
        code = """
class MyStrategy:
    def __init__(self, threshold: float = 0.5, enabled: bool = True):
        pass
"""
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(code)
        params = {p["name"]: p for p in result["data"][0]["parameters"]}
        assert params["threshold"]["type"] == "float"
        assert params["enabled"]["type"] == "bool"

    def test_parse_strategy_required_param(self):
        code = """
class MyStrategy:
    def __init__(self, required_param, optional=10):
        pass
"""
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(code)
        params = {p["name"]: p for p in result["data"][0]["parameters"]}
        assert params["required_param"]["required"] is True
        assert params["optional"]["required"] is False

    def test_parse_helper_class_filtered(self):
        code = """
class HelperClass:
    def __init__(self, x=1):
        pass

class MyStrategy:
    def __init__(self, fast=10):
        pass
"""
        from backend.services.strategy_parser import parse_strategy_parameters

        result = parse_strategy_parameters(code)
        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert result["data"][0]["class_name"] == "MyStrategy"


# ─── notification_service.py ────────────────────────────────────────
class TestNotificationService:
    """ALERT-03 收敛后 NotificationService 改为 dispatcher 薄包装"""

    @pytest.mark.asyncio
    async def test_send_alert_delegates_to_dispatcher(self):
        from backend.services.notification_service import NotificationService

        service = NotificationService()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock()
        service._dispatcher = mock_dispatcher

        await service.send_alert("Test alert message")
        mock_dispatcher.dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_with_priority(self):
        from backend.core.alert_models import NotificationPriority
        from backend.services.notification_service import NotificationService

        service = NotificationService()
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock()
        service._dispatcher = mock_dispatcher

        await service.send_alert("Critical!", priority=NotificationPriority.P0, source="kill_switch")
        call_args = mock_dispatcher.dispatch.call_args
        event = call_args[0][0]
        assert event.priority == NotificationPriority.P0
        assert event.source == "kill_switch"

    @pytest.mark.asyncio
    async def test_priority_to_severity_mapping(self):
        from backend.core.alert_models import AlertSeverity, NotificationPriority
        from backend.services.notification_service import NotificationService

        assert NotificationService._priority_to_severity(NotificationPriority.P0) == AlertSeverity.CRITICAL
        assert NotificationService._priority_to_severity(NotificationPriority.P1) == AlertSeverity.CRITICAL
        assert NotificationService._priority_to_severity(NotificationPriority.P2) == AlertSeverity.WARNING
        assert NotificationService._priority_to_severity(NotificationPriority.P3) == AlertSeverity.INFO


# ─── search_service.py ──────────────────────────────────────────────
class TestSearchService:
    @pytest.mark.asyncio
    async def test_web_search_no_api_keys(self):
        from backend.services.search_service import SearchService

        service = SearchService()
        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "BOCHA_API_KEY": ""}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            os.environ.pop("BOCHA_API_KEY", None)
            with patch("backend.services.search_service.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = [{"title": "Test", "url": "http://test.com", "body": "content"}]
                result = await service.web_search("test query")
                assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_web_search_empty_results(self):
        from backend.services.search_service import SearchService

        service = SearchService()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            os.environ.pop("BOCHA_API_KEY", None)
            with patch("backend.services.search_service.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = []
                result = await service.web_search("test")
                assert result["status"] == "success"
                assert "data" in result


# ─── system_monitor_service.py ──────────────────────────────────────
class TestSystemMonitorService:
    def test_init(self):
        from backend.services.system_monitor_service import SystemMonitorService

        service = SystemMonitorService()
        assert service._last_alert_time == 0.0

    def test_save_performance_log(self):
        from backend.services.system_monitor_service import SystemMonitorService

        service = SystemMonitorService()
        with patch("backend.services.system_monitor_service.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            service._save_performance_log("test_type", 150.0, "/api/test", "details")

    def test_save_performance_log_error(self):
        from backend.services.system_monitor_service import SystemMonitorService

        service = SystemMonitorService()
        with patch("backend.services.system_monitor_service.SessionLocal") as mock_session:
            mock_session.side_effect = Exception("DB error")
            # Should not raise
            service._save_performance_log("test", 100.0)


# ─── llm_service.py ─────────────────────────────────────────────────
class TestLLMService:
    def test_init(self):
        from backend.services.llm_service import LLMService

        service = LLMService()
        assert service.client is not None
        assert service.get_model() is not None

    def test_get_client(self):
        from backend.services.llm_service import LLMService

        service = LLMService()
        assert service.get_client() is not None

    @pytest.mark.asyncio
    async def test_close(self):
        from backend.services.llm_service import LLMService

        service = LLMService()
        service.client.close = AsyncMock()
        await service.close()
        service.client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_pydantic(self):
        from pydantic import BaseModel

        from backend.services.llm_service import LLMService

        class TestModel(BaseModel):
            name: str
            value: int

        service = LLMService()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"name": "test", "value": 42}'
        service.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await service.generate_pydantic("test prompt", TestModel)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_generate_pydantic_strips_markdown(self):
        from pydantic import BaseModel

        from backend.services.llm_service import LLMService

        class TestModel(BaseModel):
            name: str

        service = LLMService()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '```json\n{"name": "test"}\n```'
        service.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await service.generate_pydantic("prompt", TestModel)
        assert result.name == "test"

    @pytest.mark.asyncio
    async def test_generate_pydantic_validation_error(self):
        from pydantic import BaseModel

        from backend.services.llm_service import LLMService

        class TestModel(BaseModel):
            name: str
            required_field: int

        service = LLMService()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"name": "test"}'  # Missing required_field
        service.client.chat.completions.create = AsyncMock(return_value=mock_response)

        with pytest.raises(ValueError, match="LLM 输出未通过 Pydantic 校验"):
            await service.generate_pydantic("prompt", TestModel)
