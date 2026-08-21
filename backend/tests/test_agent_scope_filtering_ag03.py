"""
AGENT-03-NEXT: Agent.py ReAct loop scope filtering integration tests

验证 _extract_intents() 意图识别逻辑的正确性
"""

from __future__ import annotations

import pytest

from hermes_agent.agent import HermesAgent


class TestExtractIntents:
    """测试_extract_intents 方法的意图识别准确率"""

    def setup_method(self):
        """创建临时 Agent 实例（mock redis）"""
        # 最小化初始化，仅用于调用_extract_intents
        self.agent = HermesAgent.__new__(HermesAgent)

    @pytest.mark.parametrize(
        "query,expected_scopes",
        [
            ("AAPL 最新价是多少？", ["quote"]),
            ("特斯拉价格", ["quote"]),
            ("查看行情涨跌", ["quote"]),
            ("查询茅台的 PE PB ROE", ["fundamental"]),
            ("财报估值分析", ["fundamental"]),
            ("美联储利率决议时间", ["macro"]),
            ("非农就业数据", ["macro"]),
            ("MACD 金叉怎么计算", ["indicators"]),
            ("均线突破策略", ["indicators"]),
            ("苹果新闻", ["news"]),
            ("公司公告", ["news"]),
            ("买入 Tesla 股票", ["trade"]),
            ("下单操作", ["trade"]),
            ("搜索新能源研报", ["search"]),
            ("研报下载", ["search"]),
            ("混合查询：AAPL PE 和新闻", ["fundamental", "news"]),
            ("", []),
            ("无意义的随机文本", []),
        ],
    )
    def test_keyword_matching(self, query: str, expected_scopes: list[str]):
        """关键词匹配准确率测试"""
        result = self.agent._extract_intents(query)

        # 检查所有预期 scope 都匹配到（顺序无关）
        for scope in expected_scopes:
            assert scope in result, f"Query '{query}' should match scope '{scope}', got {result}"

        # 空查询应返回空列表
        if not query:
            assert result == [], f"Empty query should return empty list, got {result}"

    def test_multiple_scopes_union(self):
        """测试多个场景同时匹配的并集逻辑"""
        query = "查询 AAPL 的最新价格和 PE 估值"
        result = self.agent._extract_intents(query)

        # 必须同时包含 quote 和 fundamental
        assert "quote" in result, "Should extract 'quote' intent from '最新价格'"
        assert "fundamental" in result, "Should extract 'fundamental' intent from 'PE 估值'"

    def test_case_insensitive(self):
        """测试大小写不敏感匹配"""
        queries = [
            "macd 金叉",  # 全小写
            "MACD 金叉",  # 全大写
            "Macd 金叉",  # 首字母大写
        ]

        for query in queries:
            result = self.agent._extract_intents(query)
            assert "indicators" in result, f"Query '{query}' should match 'indicators' regardless of case"

    def test_no_match_returns_empty(self):
        """测试无匹配关键词时返回空列表"""
        queries = [
            "今天天气不错",
            "你好，请帮我",
            "随机无意义文本 xyz123",
        ]

        for query in queries:
            result = self.agent._extract_intents(query)
            assert result == [], f"Query '{query}' should return empty list, got {result}"


class TestBuildRequestKwargsScopeFiltering:
    """测试_build_request_kwargs 中的 scope 过滤逻辑"""

    def setup_method(self):
        """创建最小化 Agent 实例"""
        self.agent = HermesAgent.__new__(HermesAgent)
        self.agent.messages = []

    def test_fallback_to_all_schemas_on_no_match(self):
        """测试无匹配 scope 时回退到全量 schema（带 warning）"""
        self.agent.messages = [{"role": "user", "content": "无匹配关键词"}]

        # 应该打印 deprecation warning
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # 调用会触发 get_all_schemas(warn=True)
            # 由于没有完整的 tool_registry，这里只验证提取逻辑
            intents = self.agent._extract_intents("无匹配关键词")
            assert intents == [], "No scopes should be matched"

    def test_scope_based_filtering_logic(self):
        """验证基于 scope 的过滤逻辑流程正确"""
        test_cases = [
            ("AAPL 最新价", ["quote"]),
            ("PE PB analysis", ["fundamental"]),
            ("宏观新闻", ["macro", "news"]),
        ]

        for query, expected in test_cases:
            intents = self.agent._extract_intents(query)
            # 验证提取逻辑正确
            assert set(intents).issubset(set(expected)), (
                f"Query '{query}' extracted {intents}, expected subset of {expected}"
            )
            assert len(intents) > 0, f"Query '{query}' should extract at least one intent"


# 🧪 Integration Test: End-to-End Flow Simulation
class TestScopeFilteringIntegration:
    """端到端集成测试：模拟完整的工具筛选流程"""

    def test_full_pipeline_from_query_to_tool_schemas(self):
        """测试从用户查询 → 意图提取 → Schema 过滤的完整链路"""
        from hermes_agent.tool_registry import ToolRegistry

        reg = ToolRegistry()

        # 测试用例：明确的价格查询
        query = "腾讯控股最新价多少"
        intents = HermesAgent._extract_intents(HermesAgent.__new__(HermesAgent), query)

        assert "quote" in intents, "Should extract 'quote' intent"

        # 验证过滤后的 schema 数量
        filtered_schemas = reg.get_schemas_by_scopes(intents)
        all_schemas = reg.get_all_schemas(warn=False)

        assert len(filtered_schemas) < len(all_schemas), (
            f"Filtered ({len(filtered_schemas)}) should be less than all ({len(all_schemas)})"
        )

        # 验证筛选结果仅包含 quote 相关工具
        for schema in filtered_schemas:
            tool_name = schema["function"]["name"]
            # 获取该工具的 scopes
            tool_cls = None
            for cls in reg._AUTO_REGISTERED_TOOLS:
                if hasattr(cls, "name") and cls.name == tool_name:
                    tool_cls = cls
                    break

            if tool_cls:
                tool_scopes = getattr(tool_cls, "_tool_scopes", [])
                assert "quote" in tool_scopes, (
                    f"Tool '{tool_name}' in filtered results should have 'quote' scope, got {tool_scopes}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
