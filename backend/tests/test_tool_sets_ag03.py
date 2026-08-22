"""
AGENT-03: 工具集按场景分发 - 单元测试

验证 ToolScope 枚举、decorator factory pattern、get_schemas_by_scopes() 过滤逻辑。
"""

import pytest

from hermes_agent.scopes import ToolScope, get_scope_names, resolve_scope
from hermes_agent.tool_registry import ToolRegistry


class TestToolScopeEnum:
    """ToolScope 枚举定义测试"""

    def test_scope_enum_values(self):
        """验证所有 scope 枚举值"""
        assert ToolScope.QUOTE.value == "quote"
        assert ToolScope.INDICATORS.value == "indicators"
        assert ToolScope.FUND_FLOW.value == "fund_flow"
        assert ToolScope.FUNDAMENTAL.value == "fundamental"
        assert ToolScope.MACRO.value == "macro"
        assert ToolScope.NEWS.value == "news"
        assert ToolScope.TRADE.value == "trade"
        assert ToolScope.SEARCH.value == "search"
        assert ToolScope.BACKTEST.value == "backtest"
        assert ToolScope.STRATEGY.value == "strategy"
        assert ToolScope.SYSTEM.value == "system"

    def test_resolve_scope_valid(self):
        """验证合法 scope 名称解析"""
        assert resolve_scope("quote") == ToolScope.QUOTE
        assert resolve_scope("fundamental") == ToolScope.FUNDAMENTAL
        assert resolve_scope("macro") == ToolScope.MACRO

    def test_resolve_scope_invalid(self):
        """验证非法 scope 名称抛出异常"""
        with pytest.raises(ValueError, match="Unknown tool scope"):
            resolve_scope("invalid_scope")

    def test_get_scope_names(self):
        """获取所有有效 scope 名称列表"""
        names = get_scope_names()
        assert "quote" in names
        assert "fundamental" in names
        assert len(names) == 11  # 11 scopes defined


class TestToolRegistryScopes:
    """ToolRegistry scope 过滤测试"""

    @pytest.fixture
    def registry(self):
        """创建 ToolRegistry 实例"""
        return ToolRegistry()

    def test_get_schemas_by_single_scope(self, registry):
        """测试单 scope 过滤"""
        quote_schemas = registry.get_schemas_by_scopes(["quote"])
        assert len(quote_schemas) > 0
        assert len(quote_schemas) <= 12  # AGENT-03 目标：单步注入 schema 数 ≤12

        fundamental_schemas = registry.get_schemas_by_scopes(["fundamental"])
        assert len(fundamental_schemas) > 0
        assert len(fundamental_schemas) <= 12

    def test_get_schemas_by_multi_scope(self, registry):
        """测试多 scope union 过滤"""
        multi_schemas = registry.get_schemas_by_scopes(["quote", "macro"])
        quote_schemas = registry.get_schemas_by_scopes(["quote"])
        macro_schemas = registry.get_schemas_by_scopes(["macro"])

        # Union should be >= each individual scope
        assert len(multi_schemas) >= len(quote_schemas)
        assert len(multi_schemas) >= len(macro_schemas)

    def test_get_schemas_empty_scope_returns_all(self, registry):
        """测试空 scope 列表返回全部工具（带 warning）"""
        with pytest.warns(UserWarning, match="returns all tools"):
            all_schemas = registry.get_schemas_by_scopes([])
            assert len(all_schemas) == 32  # 32 tools registered

    def test_get_schemas_none_scope_returns_all(self, registry):
        """测试 None scope 返回全部工具（带 warning）"""
        with pytest.warns(UserWarning, match="returns all tools"):
            all_schemas = registry.get_schemas_by_scopes(None)
            assert len(all_schemas) == 32

    def test_get_all_schemas_deprecated(self, registry):
        """测试 get_all_schemas() 废弃警告"""
        with pytest.warns(DeprecationWarning, match="deprecated"):
            all_schemas = registry.get_all_schemas()
            assert len(all_schemas) == 32

    def test_get_schemas_invalid_scope_returns_empty(self, registry):
        """测试非法 scope 返回空列表"""
        invalid_schemas = registry.get_schemas_by_scopes(["invalid_scope"])
        assert len(invalid_schemas) == 0

    def test_tool_scopes_attribute_exists(self, registry):
        """验证工具类具有 _tool_scopes 属性"""
        # Get any tool from registry
        all_tools = registry.get_schemas_by_scopes(None)
        assert len(all_tools) > 0

        # Check that tools have _tool_scopes attribute
        for tool_name in list(registry.tools.keys())[:5]:  # Check first 5 tools
            tool_cls = registry.tools[tool_name]
            assert hasattr(tool_cls, "_tool_scopes")
            assert isinstance(tool_cls._tool_scopes, list)


class TestScopeDistribution:
    """Scope 分布统计测试"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_scope_distribution(self, registry):
        """验证各 scope 的工具分布"""
        scope_counts = {}
        for scope in ["quote", "fundamental", "macro", "trade", "search", "news", "indicators", "system"]:
            schemas = registry.get_schemas_by_scopes([scope])
            scope_counts[scope] = len(schemas)

        # Verify expected distribution (based on AGENT-03 implementation)
        assert scope_counts["quote"] == 6
        assert scope_counts["fundamental"] == 7
        assert scope_counts["macro"] == 7
        assert scope_counts["trade"] == 5
        assert scope_counts["search"] == 6
        assert scope_counts["news"] == 5

    def test_context_reduction_achieved(self, registry):
        """验证 Context 压缩目标达成"""
        # Before AGENT-03: 32 tools injected every time
        all_tools_count = len(registry.get_schemas_by_scopes(None))

        # After AGENT-03: average 6-8 tools per scope
        avg_tools_per_scope = (
            sum(
                [
                    len(registry.get_schemas_by_scopes(["quote"])),
                    len(registry.get_schemas_by_scopes(["fundamental"])),
                    len(registry.get_schemas_by_scopes(["macro"])),
                ]
            )
            / 3
        )

        # Verify 75% reduction target
        reduction_ratio = avg_tools_per_scope / all_tools_count
        assert reduction_ratio < 0.30  # <30% of original = 70%+ reduction
        print(
            f"✅ Context reduction achieved: {reduction_ratio:.2%} of original ({all_tools_count} → {avg_tools_per_scope:.1f} avg)"
        )


class TestIntentRecognition:
    """意图识别测试（agent.py _extract_intents）"""

    def test_extract_intents_quote(self):
        """测试 quote scope 意图识别"""
        from hermes_agent.agent import HermesAgent
        from hermes_agent.tool_registry import ToolRegistry

        agent = HermesAgent(tool_registry=ToolRegistry())
        intents = agent._extract_intents("AAPL 最新价格是多少？")
        assert "quote" in intents

    def test_extract_intents_fundamental(self):
        """测试 fundamental scope 意图识别"""
        from hermes_agent.agent import HermesAgent
        from hermes_agent.tool_registry import ToolRegistry

        agent = HermesAgent(tool_registry=ToolRegistry())
        intents = agent._extract_intents("分析一下 TSLA 的 PE 和 PB 估值")
        assert "fundamental" in intents

    def test_extract_intents_macro(self):
        """测试 macro scope 意图识别"""
        from hermes_agent.agent import HermesAgent
        from hermes_agent.tool_registry import ToolRegistry

        agent = HermesAgent(tool_registry=ToolRegistry())
        intents = agent._extract_intents("美联储利率决议对美股的影响")
        assert "macro" in intents

    def test_extract_intents_multi(self):
        """测试多 scope 意图识别"""
        from hermes_agent.agent import HermesAgent
        from hermes_agent.tool_registry import ToolRegistry

        agent = HermesAgent(tool_registry=ToolRegistry())
        intents = agent._extract_intents("AAPL 最新价格和技术指标 MA 均线分析")
        assert "quote" in intents
        assert "indicators" in intents

    def test_extract_intents_no_match(self):
        """测试无匹配意图返回空列表"""
        from hermes_agent.agent import HermesAgent
        from hermes_agent.tool_registry import ToolRegistry

        agent = HermesAgent(tool_registry=ToolRegistry())
        intents = agent._extract_intents("今天天气怎么样？")
        assert len(intents) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
