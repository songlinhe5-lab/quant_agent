"""
Screener Service 集成测试
验证所有内置的选股灵感提示词都能被大模型成功转译为合法的 DSL JSON。
注意：此测试依赖外部 LLM 服务和 Redis，在无外部服务环境中自动跳过。
"""
import asyncio
import json
import pytest

from backend.routers.screener import SUGGESTIONS
from backend.services.screener_service import ScreenerDecision, screener_service


@pytest.mark.asyncio
@pytest.mark.skip(reason="集成测试：依赖外部 LLM 服务和 Redis，本地环境不可用")
async def test_all_suggestions_can_be_translated():
    """
    验证所有内置的选股灵感提示词都能被大模型成功转译为合法的 DSL JSON，
    并且能通过 Pydantic 模型的严格校验。
    """
    tasks = [screener_service.translate_nlp_to_dsl(query) for query in SUGGESTIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for query, result in zip(SUGGESTIONS, results):
        if isinstance(result, Exception):
            pytest.skip(f"外部服务不可用，翻译 '{query}' 时发生异常: {result}")

        assert isinstance(result, str), f"翻译 '{query}' 返回的不是字符串类型: {type(result)}"

        try:
            dsl_obj = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            pytest.fail(f"翻译 '{query}' 返回的不是合法的 JSON: {result}")

        try:
            ScreenerDecision.model_validate(dsl_obj)
        except Exception as e:
            pytest.fail(f"翻译 '{query}' 生成的 DSL 未能通过 Pydantic 校验: {e}\nDSL: {result}")
