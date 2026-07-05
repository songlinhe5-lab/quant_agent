"""
单元测试：LLM 服务 (services/llm_service.py)
测试大语言模型服务的结构化输出和客户端管理
"""

import json
from unittest import mock

import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from backend.services.llm_service import LLMService


class TestResponse(BaseModel):
    """测试用 Pydantic 模型"""

    message: str
    score: float


class TestLLMServiceInit:
    """测试 LLM 服务初始化"""

    def test_init_from_env(self, monkeypatch):
        """测试从环境变量初始化"""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_BASE_URL", "https://test.com/v1")
        monkeypatch.setenv("LLM_MODEL", "test-model")

        service = LLMService()
        assert service.api_key == "test-key"
        assert service.base_url == "https://test.com/v1"
        assert service.model_name == "test-model"

    def test_init_defaults(self, monkeypatch):
        """测试使用默认值初始化"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        service = LLMService()
        assert service.api_key == ""
        assert service.base_url == "https://api.deepseek.com"
        assert service.model_name == "deepseek-chat"

    def test_client_timeout(self):
        """测试客户端超时设置"""
        with mock.patch.dict("os.environ", {"LLM_API_KEY": "test-key"}):
            service = LLMService()
            # httpx.Timeout 对象是一个浮点数或者 Timeout 对象
            # AsyncOpenAI 的 timeout 参数可以是浮点数
            assert service.client.timeout == 30.0 or service.client.timeout.connect == 30.0


class TestLLMServiceGetters:
    """测试 LLM 服务获取方法"""

    @pytest.fixture
    def service(self):
        with mock.patch.dict("os.environ", {"LLM_API_KEY": "test-key", "LLM_MODEL": "test-model"}):
            return LLMService()

    def test_get_client(self, service):
        """测试获取客户端"""
        client = service.get_client()
        assert isinstance(client, AsyncOpenAI)

    def test_get_model(self, service):
        """测试获取模型名称"""
        assert service.get_model() == "test-model"


class TestLLMServiceGeneratePydantic:
    """测试结构化输出生成"""

    @pytest.fixture
    def service(self):
        with mock.patch.dict("os.environ", {"LLM_API_KEY": "test-key"}):
            service = LLMService()
            return service

    @mock.patch("backend.services.llm_service.LLMService.get_model")
    async def test_generate_pydantic_success(self, mock_get_model, service):
        """测试成功生成 Pydantic 对象"""
        mock_get_model.return_value = "test-model"

        # Mock OpenAI 响应
        mock_response = mock.MagicMock()
        mock_response.choices = [
            mock.MagicMock(message=mock.MagicMock(content=json.dumps({"message": "Hello", "score": 0.95})))
        ]
        service.client.chat.completions.create = mock.AsyncMock(return_value=mock_response)

        result = await service.generate_pydantic(
            prompt="Test prompt",
            response_model=TestResponse,
            system_prompt="You are a test assistant.",
        )

        assert isinstance(result, TestResponse)
        assert result.message == "Hello"
        assert result.score == 0.95

    @mock.patch("backend.services.llm_service.LLMService.get_model")
    async def test_generate_pydantic_with_markdown(self, mock_get_model, service):
        """测试清理 Markdown 代码块标记"""
        mock_get_model.return_value = "test-model"

        mock_response = mock.MagicMock()
        mock_response.choices = [
            mock.MagicMock(
                message=mock.MagicMock(content="```json\n" + json.dumps({"message": "Hello", "score": 0.8}) + "\n```")
            )
        ]
        service.client.chat.completions.create = mock.AsyncMock(return_value=mock_response)

        result = await service.generate_pydantic(
            prompt="Test prompt",
            response_model=TestResponse,
        )

        assert result.message == "Hello"
        assert result.score == 0.8

    @mock.patch("backend.services.llm_service.LLMService.get_model")
    async def test_generate_pydantic_validation_error(self, mock_get_model, service):
        """测试 Pydantic 校验失败抛出异常"""
        mock_get_model.return_value = "test-model"

        mock_response = mock.MagicMock()
        mock_response.choices = [mock.MagicMock(message=mock.MagicMock(content=json.dumps({"invalid": "data"})))]
        service.client.chat.completions.create = mock.AsyncMock(return_value=mock_response)

        with pytest.raises(ValueError, match="LLM 输出未通过 Pydantic 校验"):
            await service.generate_pydantic(
                prompt="Test prompt",
                response_model=TestResponse,
            )

    @mock.patch("backend.services.llm_service.LLMService.get_model")
    async def test_generate_pydantic_empty_content(self, mock_get_model, service):
        """测试空内容处理"""
        mock_get_model.return_value = "test-model"

        mock_response = mock.MagicMock()
        mock_response.choices = [mock.MagicMock(message=mock.MagicMock(content=None))]
        service.client.chat.completions.create = mock.AsyncMock(return_value=mock_response)

        # 空内容会导致 ValidationError，然后被捕获并重新抛出为 ValueError
        with pytest.raises(ValueError, match="LLM 输出未通过 Pydantic 校验"):
            await service.generate_pydantic(
                prompt="Test prompt",
                response_model=TestResponse,
            )

    def test_json_schema_generation(self, service):
        """测试 JSON Schema 正确生成"""
        schema = TestResponse.model_json_schema()
        schema_str = json.dumps(schema, ensure_ascii=False)

        assert "message" in schema_str
        assert "score" in schema_str
        assert "string" in schema_str.lower() or "str" in schema_str.lower()
        assert "number" in schema_str.lower() or "float" in schema_str.lower()


class TestLLMServiceClose:
    """测试 LLM 服务关闭"""

    async def test_close(self):
        with mock.patch.dict("os.environ", {"LLM_API_KEY": "test-key"}):
            service = LLMService()
            service.client.close = mock.AsyncMock()

            await service.close()

            service.client.close.assert_called_once()
