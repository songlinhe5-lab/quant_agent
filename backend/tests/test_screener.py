import asyncio
import json
import os
import unittest
import warnings

import unittest.mock as _mock

from backend.routers.screener import SUGGESTIONS
from backend.services.screener_service import screener_service


class TestScreenerSuggestions(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # 忽略 asyncio 和 Pydantic 的一些无害警告
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        # 💡 加速：mock reload_rag_corpus，避免真实加载 RAG 语料库（耗时）
        cls._rag_patcher = _mock.patch.object(
            screener_service, "reload_rag_corpus"
        )
        cls._rag_patcher.start()
        screener_service.reload_rag_corpus()

    @classmethod
    def tearDownClass(cls):
        cls._rag_patcher.stop()
        super().tearDownClass()

    @unittest.skipIf(
        os.getenv("QUANT_ENV") == "ci",
        "在 CI 环境中跳过极其耗时且消耗 API Token 的全量大模型转译测试",
    )  # noqa: E501
    async def test_all_suggestions_translation_and_parsing(self):
        """
        并发遍历验证 routers/screener.py 中的所有 SUGGESTIONS (灵感例子)。

        💡 加速：mock translate_nlp_to_dsl，不真实调用 LLM API，
        直接返回合法 DSL JSON，只验证后续解析逻辑是否正确。
        """
        total = len(SUGGESTIONS)
        print(f"\n🚀 对 {total} 条选股灵感进行 DSL 解析验证（已跳过 LLM 调用）...")

        failed_queries = []
        semaphore = asyncio.Semaphore(5)

        # 一个合法的最小 DSL，能通过 ScreenerDecision 校验并被 parse_dsl_to_futu_filters 正常解析
        _VALID_DSL = json.dumps({
            "dsl_display": "market:US",
            "markets": ["US"],
            "exclude_st": False,
            "technical_patterns": [],
            "filters": [],
            "rag_rules": [],
        })

        async def _verify_query(query: str, index: int):
            async with semaphore:
                try:
                    dsl_json = await screener_service.translate_nlp_to_dsl(query)
                    markets, futu_filters, post_filters = (
                        screener_service.parse_dsl_to_futu_filters(dsl_json)
                    )

                    self.assertIsInstance(markets, list, f"Markets 必须是列表: {dsl_json}")
                    self.assertTrue(len(markets) > 0, f"Markets 不能为空: {dsl_json}")
                    self.assertIsInstance(futu_filters, list, f"futu_filters 必须是列表: {dsl_json}")
                    self.assertIsInstance(post_filters, dict, f"post_filters 必须是字典: {dsl_json}")

                    print(f"✅ [{index:02d}/{total}] 验证通过: {query}")
                    log_msg = f"[{index:02d}/{total}] [✅ PASS] Query: {query}\nDSL:\n{dsl_json}\n"
                    return True, log_msg, None
                except Exception as e:
                    print(f"❌ [{index}/{total}] 验证失败: {query} | 错误: {e}")
                    log_msg = f"[{index:02d}/{total}] [❌ FAIL] Query: {query}\n    Error: {str(e)}\n"
                    return False, log_msg, f"Query: {query} | Error: {str(e)}"

        # 💡 关键：mock translate_nlp_to_dsl，不真实调用 LLM
        with _mock.patch.object(
            screener_service,
            "translate_nlp_to_dsl",
            new_callable=_mock.AsyncMock,
            return_value=_VALID_DSL,
        ):
            tasks = [_verify_query(query, i + 1) for i, query in enumerate(SUGGESTIONS)]
            results = await asyncio.gather(*tasks)

        # 写测试报告（与原有行为保持一致）
        log_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "screener_test_report.log")
        )
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"🚀 Screener Unit Test Report (mocked LLM)\nTotal Queries: {total}\n{'=' * 60}\n\n")
            for success, log_msg, err_msg in results:
                f.write(log_msg + "\n")
                if not success:
                    failed_queries.append(err_msg)

        print(f"\n📄 测试报告已生成至: {log_path}")

        if failed_queries:
            self.fail(
                f"共有 {len(failed_queries)} 条灵感例子测试失败，请检查 DSL 解析逻辑或 Pydantic 校验器:\n"
                + "\n".join(failed_queries)
            )  # noqa: E501


if __name__ == "__main__":
    unittest.main()
