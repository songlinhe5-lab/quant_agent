"""
AI-02 · LLM 多模型路由单元测试

覆盖:
- ModelTier 枚举值
- LLMRouter tier 路由正确性
- Ollama 降级触发与恢复
- 版本钉定
- LLMService 向后兼容
"""

from unittest.mock import AsyncMock, patch


class TestModelTier:
    """ModelTier 枚举"""

    def test_tier_values(self):
        from backend.services.llm_service import ModelTier

        assert ModelTier.LIGHTWEIGHT.value == "lightweight"
        assert ModelTier.STANDARD.value == "standard"
        assert ModelTier.FLAGSHIP.value == "flagship"


class TestLLMRouter:
    """LLMRouter 路由逻辑"""

    def _make_router(self, **kwargs):
        from backend.services.llm_service import LLMRouter

        defaults = dict(
            api_key="test-key",
            base_url="https://api.test.com",
            standard_model="std-model",
            lightweight_model="light-model",
            flagship_model="flag-model",
            ollama_base_url="http://localhost:11434/v1",
            fallback_enabled=True,
            fallback_threshold=3,
        )
        defaults.update(kwargs)
        return LLMRouter(**defaults)

    def test_get_model_returns_pinned_version(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router()
        assert router.get_model(ModelTier.LIGHTWEIGHT) == "light-model"
        assert router.get_model(ModelTier.STANDARD) == "std-model"
        assert router.get_model(ModelTier.FLAGSHIP) == "flag-model"

    def test_get_client_default_returns_primary(self):
        router = self._make_router()
        client = router.get_client()
        # 默认应返回主供应商客户端
        assert client is not None
        assert not router.is_fallback_active

    def test_record_failure_triggers_fallback_after_threshold(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router(fallback_threshold=3)
        assert not router.is_fallback_active

        router.record_failure(ModelTier.STANDARD)
        assert not router.is_fallback_active

        router.record_failure(ModelTier.STANDARD)
        assert not router.is_fallback_active

        # 第 3 次失败触发降级
        router.record_failure(ModelTier.STANDARD)
        assert router.is_fallback_active

    def test_fallback_returns_ollama_client(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router(fallback_threshold=2)

        # 触发降级
        router.record_failure(ModelTier.STANDARD)
        router.record_failure(ModelTier.STANDARD)
        assert router.is_fallback_active

        # 降级后应返回 Ollama 客户端
        ollama_client = router.get_client(ModelTier.STANDARD)
        assert ollama_client is not None
        # Ollama 客户端 base_url 应指向本地
        assert "localhost" in str(ollama_client.base_url) or "11434" in str(ollama_client.base_url)

    def test_record_success_resets_fallback(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router(fallback_threshold=2)

        router.record_failure(ModelTier.STANDARD)
        router.record_failure(ModelTier.STANDARD)
        assert router.is_fallback_active

        # 成功调用应恢复主供应商
        router.record_success(ModelTier.STANDARD)
        assert not router.is_fallback_active

    def test_failure_count_reset_on_success(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router(fallback_threshold=3)

        router.record_failure(ModelTier.STANDARD)
        router.record_failure(ModelTier.STANDARD)
        # 中间成功一次，计数重置
        router.record_success(ModelTier.STANDARD)
        # 再失败两次不应触发降级
        router.record_failure(ModelTier.STANDARD)
        router.record_failure(ModelTier.STANDARD)
        assert not router.is_fallback_active

    def test_fallback_disabled(self):
        from backend.services.llm_service import ModelTier

        router = self._make_router(fallback_enabled=False, fallback_threshold=1)
        router.record_failure(ModelTier.STANDARD)
        # fallback 禁用时不应降级
        assert not router.is_fallback_active

    def test_health_check(self):
        """health_check 应返回 primary 和 ollama 状态"""
        import asyncio

        router = self._make_router()

        # Mock 客户端的 models.list() 方法
        mock_primary = AsyncMock()
        mock_primary.models.list = AsyncMock(return_value=[])
        router._primary_client = mock_primary

        mock_ollama = AsyncMock()
        mock_ollama.models.list = AsyncMock(side_effect=Exception("not running"))
        router._ollama_client = mock_ollama

        result = asyncio.get_event_loop().run_until_complete(router.health_check())
        assert result["primary"] is True
        assert result["ollama"] is False


class TestLLMServiceBackwardCompat:
    """LLMService 向后兼容"""

    def test_get_model_without_tier(self):
        """不传 tier 时返回默认模型"""
        with patch.dict("os.environ", {"LLM_API_KEY": "test", "LLM_MODEL": "deepseek-chat"}):
            from backend.services.llm_service import LLMService

            svc = LLMService()
            assert svc.get_model() == "deepseek-chat"

    def test_get_model_with_tier(self):
        """传入 tier 时返回对应模型"""
        from backend.services.llm_service import LLMService, ModelTier

        svc = LLMService()
        assert svc.get_model(ModelTier.LIGHTWEIGHT) == svc.router.get_model(ModelTier.LIGHTWEIGHT)

    def test_router_attribute_exists(self):
        """LLMService 应有 router 属性"""
        from backend.services.llm_service import LLMService

        svc = LLMService()
        assert hasattr(svc, "router")
        assert svc.router is not None
