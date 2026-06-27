import asyncio
import unittest
import json
from backend.services.screener_service import screener_service, ScreenerDecision
from backend.routers.screener import SUGGESTIONS

class TestScreenerService(unittest.TestCase):

    def test_all_suggestions_can_be_translated(self):
        """
        验证所有内置的选股灵感提示词都能被大模型成功转译为合法的 DSL JSON，
        并且能通过 Pydantic 模型的严格校验。
        """
        async def run_tests():
            tasks = [screener_service.translate_nlp_to_dsl(query) for query in SUGGESTIONS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for query, result in zip(SUGGESTIONS, results):
                with self.subTest(query=query):
                    self.assertFalse(isinstance(result, Exception), f"翻译 '{query}' 时发生异常: {result}")
                    
                    # 验证返回的是合法的 JSON 字符串
                    if not isinstance(result, str):
                        self.fail(f"翻译 '{query}' 返回的不是字符串类型: {type(result)}")
                    
                    try:
                        dsl_obj = json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        self.fail(f"翻译 '{query}' 返回的不是合法的 JSON: {result}")

                    # 验证 JSON 内容能通过 Pydantic 模型的强类型校验
                    try:
                        ScreenerDecision.model_validate(dsl_obj)
                    except Exception as e:
                        self.fail(f"翻译 '{query}' 生成的 DSL 未能通过 Pydantic 校验: {e}\nDSL: {result}")
        
        asyncio.run(run_tests())

if __name__ == '__main__':
    unittest.main()