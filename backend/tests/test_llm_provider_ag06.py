"""
AGENT-06: LLM Provider 适配缝 - 单元测试

验收标准：
1. 注入主 provider 故障后自动切备用
2. 前端按 §2.4 STALE 规范标注降级态（SSE 事件）
3. 默认路由不变（主推理仍为 deepseek-v4-flash）
4. 恢复探测机制
"""

from unittest.mock import MagicMock

import pytest

from hermes_agent.llm_provider import (
    FAILOVER_THRESHOLD,
    FailoverEvent,
    LLMProvider,
    LLMProviderRouter,
    ProviderStatus,
)


class MockAsyncOpenAI:
    """模拟 AsyncOpenAI 客户端"""

    def __init__(self, should_fail=False, fail_count=0):
        self.should_fail = should_fail
        self.fail_count = fail_count
        self._call_count = 0
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._mock_create

    async def _mock_create(self, **kwargs):
        self._call_count += 1
        if self.should_fail and self._call_count <= self.fail_count:
            raise Exception(f"模拟 provider 故障 (call #{self._call_count})")

        # 返回模拟 response
        mock_msg = MagicMock()
        mock_msg.content = "test response"
        mock_msg.tool_calls = None
        mock_msg.reasoning_content = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_msg
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        return mock_response


def make_provider(name, model, should_fail=False, fail_count=0, priority=0):
    """创建测试用 provider"""
    client = MockAsyncOpenAI(should_fail=should_fail, fail_count=fail_count)
    return LLMProvider(
        name=name,
        client=client,
        model=model,
        priority=priority,
    )


class TestLLMProvider:
    """LLMProvider 基础测试"""

    def test_provider_creation(self):
        """测试 provider 创建"""
        p = make_provider("test-provider", "test-model")
        assert p.name == "test-provider"
        assert p.model == "test-model"
        assert p.status == ProviderStatus.HEALTHY
        assert p.consecutive_failures == 0

    def test_mark_success(self):
        """测试成功标记"""
        p = make_provider("test", "model")
        p.consecutive_failures = 3
        p.status = ProviderStatus.FAILED
        p.mark_success()
        assert p.consecutive_failures == 0
        assert p.status == ProviderStatus.HEALTHY

    def test_mark_failure(self):
        """测试失败标记"""
        p = make_provider("test", "model")
        p.mark_failure()
        assert p.consecutive_failures == 1
        p.mark_failure()
        assert p.consecutive_failures == 2


class TestLLMProviderRouter:
    """LLMProviderRouter 测试"""

    @pytest.fixture
    def primary(self):
        return make_provider("primary-deepseek", "deepseek-v4-flash", priority=0)

    @pytest.fixture
    def fallback(self):
        return make_provider("fallback-gpt4o", "gpt-4o-mini", priority=1)

    @pytest.fixture
    def router(self, primary):
        return LLMProviderRouter(primary)

    def test_initial_state(self, router):
        """测试初始状态：活跃 provider 是 primary"""
        assert router.get_active_provider().name == "primary-deepseek"
        assert not router.is_degraded()

    def test_add_fallback(self, router, fallback):
        """测试添加 fallback"""
        router.add_fallback(fallback)
        assert len(router.all_providers) == 2
        assert router.all_providers[1].name == "fallback-gpt4o"

    def test_default_routing_unchanged(self, router):
        """验收：默认路由不变（主推理仍为 deepseek-v4-flash）"""
        assert router.get_active_model() == "deepseek-v4-flash"
        assert router.primary_provider.model == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_report_success(self, router):
        """测试成功报告"""
        await router.report_success()
        assert router.get_active_provider().consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_report_failure_below_threshold(self, router, fallback):
        """测试失败报告（未达阈值）— 无 fallback 时不切换"""
        # 无 fallback 时，失败不会触发切换
        event = await router.report_failure()
        assert event is None  # 无 fallback，无法切换
        assert router.get_active_provider().consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_failover_on_threshold(self, router, fallback):
        """验收：注入主 provider 故障后自动切备用"""
        router.add_fallback(fallback)

        # 连续失败达阈值
        for _ in range(FAILOVER_THRESHOLD):
            event = await router.report_failure()

        # 最后一次应该触发切换
        assert event is not None
        assert event.from_provider == "primary-deepseek"
        assert event.to_provider == "fallback-gpt4o"
        assert router.is_degraded()
        assert router.get_active_provider().name == "fallback-gpt4o"

    @pytest.mark.asyncio
    async def test_execute_with_failover_success(self, router):
        """测试 execute_with_failover 成功路径"""

        async def create_func(client, model):
            return await client.chat.completions.create(model=model)

        response, event = await router.execute_with_failover(create_func)
        assert response is not None
        assert event is None  # 无故障，无切换事件

    @pytest.mark.asyncio
    async def test_execute_with_failover_triggers_failover(self, router, fallback):
        """测试 execute_with_failover 触发故障切换"""
        router.add_fallback(fallback)

        # 让 primary 连续失败 FAILOVER_THRESHOLD 次以触发切换
        call_count = 0

        async def create_func(client, model):
            nonlocal call_count
            call_count += 1
            # 前 FAILOVER_THRESHOLD 次调用（primary）失败，之后（fallback）成功
            if model == router.primary_provider.model:
                raise Exception("模拟 primary 故障")
            return await client.chat.completions.create(model=model)

        response, event = await router.execute_with_failover(create_func)
        assert response is not None
        assert event is not None  # 发生了切换
        assert event.to_provider == "fallback-gpt4o"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self, primary):
        """测试所有 provider 都失败时抛异常"""
        primary.client.should_fail = True
        primary.client.fail_count = 100  # 一直失败

        router = LLMProviderRouter(primary)
        # 不添加 fallback

        async def create_func(client, model):
            return await client.chat.completions.create(model=model)

        with pytest.raises(Exception, match="模拟 provider 故障"):
            await router.execute_with_failover(create_func)


class TestFailoverEvent:
    """FailoverEvent 测试"""

    def test_to_sse_dict(self):
        """测试 SSE 事件序列化"""
        event = FailoverEvent(
            from_provider="primary-deepseek",
            to_provider="fallback-gpt4o",
            reason="连续失败 2 次",
        )
        d = event.to_sse_dict()
        assert d["type"] == "provider_degraded"
        assert d["from_provider"] == "primary-deepseek"
        assert d["to_provider"] == "fallback-gpt4o"
        assert "连续失败" in d["reason"]


class TestAcceptanceCriteria:
    """验收标准测试"""

    @pytest.mark.asyncio
    async def test_primary_failure_auto_switch(self):
        """
        验收标准 1: 注入主 provider 故障后自动切备用。

        模拟主 provider 连续失败 FAILOVER_THRESHOLD 次，
        验证 router 自动切换到 fallback provider。
        """
        primary = make_provider("primary", "deepseek-v4-flash")
        fallback = make_provider("fallback", "gpt-4o-mini")
        router = LLMProviderRouter(primary)
        router.add_fallback(fallback)

        # 模拟连续失败
        for i in range(FAILOVER_THRESHOLD):
            event = await router.report_failure()

        # 验收：自动切换
        assert router.is_degraded()
        assert router.get_active_provider().name == "fallback"
        assert event is not None
        assert event.from_provider == "primary"
        assert event.to_provider == "fallback"

    @pytest.mark.asyncio
    async def test_sse_degraded_event_format(self):
        """
        验收标准 2: 前端按 §2.4 STALE 规范标注降级态。

        验证 FailoverEvent.to_sse_dict() 输出格式正确，
        前端可据此渲染降级提示。
        """
        event = FailoverEvent(
            from_provider="primary-deepseek-v4-flash",
            to_provider="fallback-gpt-4o-mini",
            reason="主 provider 连续失败 2 次，自动降级",
        )
        sse = event.to_sse_dict()

        # 验收：SSE 事件格式
        assert sse["type"] == "provider_degraded"
        assert "from_provider" in sse
        assert "to_provider" in sse
        assert "reason" in sse
        assert "timestamp" in sse

    def test_default_routing_unchanged(self):
        """
        验收标准 3: 默认路由不变。

        验证 router 初始化后活跃 provider 是 primary，
        模型名称为 deepseek-v4-flash。
        """
        primary = make_provider("primary", "deepseek-v4-flash")
        router = LLMProviderRouter(primary)

        assert router.get_active_model() == "deepseek-v4-flash"
        assert not router.is_degraded()


class TestRouterStatusSummary:
    """Router 状态摘要测试"""

    def test_status_summary(self):
        """测试状态摘要输出"""
        primary = make_provider("primary", "deepseek-v4-flash")
        fallback = make_provider("fallback", "gpt-4o-mini")
        router = LLMProviderRouter(primary)
        router.add_fallback(fallback)

        summary = router.get_status_summary()
        assert summary["active_provider"] == "primary"
        assert summary["is_degraded"] is False
        assert len(summary["providers"]) == 2
        assert summary["providers"][0]["name"] == "primary"
        assert summary["providers"][1]["name"] == "fallback"
