import asyncio
import os
import unittest
import warnings

from backend.routers.screener import SUGGESTIONS
from backend.services.screener_service import screener_service


class TestScreenerSuggestions(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # 忽略 asyncio 和 Pydantic 的一些无害警告
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        # 确保 RAG 语料库初始化完毕
        screener_service.reload_rag_corpus()

    @unittest.skipIf(
        os.getenv("QUANT_ENV") == "ci",
        "在 CI 环境中跳过极其耗时且消耗 API Token 的全量大模型转译测试",
    )  # noqa: E501
    async def test_all_suggestions_translation_and_parsing(self):
        """
        并发遍历验证 routers/screener.py 中的所有 SUGGESTIONS (灵感例子)。
        1. 验证大语言模型 (LLM) 能否正常理解并输出合法 JSON。
        2. 验证 Pydantic 模型 (ScreenerDecision) 能否顺利通过校验和容错纠偏。
        3. 验证能否成功转译为 Futu OpenD 底层引擎可接受的 filters 格式。
        """
        total = len(SUGGESTIONS)
        print(f"\n🚀 准备对 {total} 条选股灵感进行全量大模型转译与解析验证...")

        failed_queries = []

        # 限制并发量，防范大模型 API 触发 429 限流
        semaphore = asyncio.Semaphore(5)

        async def _verify_query(query: str, index: int):
            async with semaphore:
                try:
                    # 1. 调用大模型进行语义转译
                    dsl_json = await screener_service.translate_nlp_to_dsl(query)

                    # 2. 核心验证：DSL 能否被成功解析为 Futu API 格式
                    markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(dsl_json)  # noqa: E501

                    # 3. 断言有效性
                    self.assertIsInstance(markets, list, f"Markets 必须是列表: {dsl_json}")  # noqa: E501
                    self.assertTrue(len(markets) > 0, f"Markets 不能为空: {dsl_json}")
                    self.assertIsInstance(futu_filters, list, f"futu_filters 必须是列表: {dsl_json}")  # noqa: E501
                    self.assertIsInstance(post_filters, dict, f"post_filters 必须是字典: {dsl_json}")  # noqa: E501

                    print(f"✅ [{index:02d}/{total}] 验证通过: {query}")

                    log_msg = f"[{index:02d}/{total}] [✅ PASS] Query: {query}\nDSL:\n{dsl_json}\n"  # noqa: E501
                    return True, log_msg, None
                except Exception as e:
                    print(f"❌ [{index}/{total}] 验证失败: {query} | 错误: {e}")

                    log_msg = f"[{index:02d}/{total}] [❌ FAIL] Query: {query}\n    Error: {str(e)}\n"  # noqa: E501
                    return False, log_msg, f"Query: {query} | Error: {str(e)}"

        tasks = [_verify_query(query, i + 1) for i, query in enumerate(SUGGESTIONS)]
        results = await asyncio.gather(*tasks)

        # 将详细的转译结果和错误日志统一保存到本地文件中
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "screener_test_report.log"))  # noqa: E501
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"🚀 Screener E2E Test Report\nTotal Queries: {total}\n{'=' * 60}\n\n")  # noqa: E501
            for success, log_msg, err_msg in results:
                f.write(log_msg + "\n")
            if not success:
                failed_queries.append(err_msg)

        print(f"\n📄 详细测试报告已生成至: {log_path}")

        if failed_queries:
            self.fail(
                f"共有 {len(failed_queries)} 条灵感例子测试失败，请检查大模型解析逻辑或 Pydantic 校验器:\n"
                + "\n".join(failed_queries)
            )  # noqa: E501


if __name__ == "__main__":
    unittest.main()
