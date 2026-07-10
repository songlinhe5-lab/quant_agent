"""
Hermes Agent Tool 独立单元测试
TEST-10: mock 外部数据源响应，校验 Tool 入参解析、出参结构、异常分支
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("BACKEND_API_URL", "http://127.0.0.1:8000")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ─── BaseTool: normalize_ticker ─────────────────────────────────────
class TestBaseToolNormalizeTicker:
    """BaseTool.normalize_ticker 入参解析测试"""

    def setup_method(self):
        from hermes_agent.tools.base import BaseTool

        self.tool = BaseTool()

    def test_empty_ticker(self):
        assert self.tool.normalize_ticker("") == ""

    def test_hk_stock(self):
        assert self.tool.normalize_ticker("0700.HK") == "HK.00700"
        assert self.tool.normalize_ticker("HK.00700") == "HK.00700"

    def test_us_stock(self):
        assert self.tool.normalize_ticker("AAPL") == "US.AAPL"
        assert self.tool.normalize_ticker("US.AAPL") == "US.AAPL"

    def test_sh_stock(self):
        result = self.tool.normalize_ticker("600519")
        assert result.startswith("SH.") or result.startswith("SZ.")

    def test_cryptocurrency(self):
        result = self.tool.normalize_ticker("BTC:USDT")
        assert "BTC" in result

    def test_whitespace_handling(self):
        result = self.tool.normalize_ticker("  AAPL  ")
        assert result == "US.AAPL"


# ─── BaseTool: 缓存机制 ──────────────────────────────────────────────
class TestBaseToolCache:
    """BaseTool 双级缓存测试"""

    def setup_method(self):
        from hermes_agent.tools.base import BaseTool

        # 清空共享缓存
        BaseTool._shared_cache.clear()
        self.tool = BaseTool()

    def test_set_and_get_l1_cache(self):
        """测试 L1 内存缓存读写"""
        loop = asyncio.get_event_loop()

        async def _test():
            await self.tool.set_cached_data("test_key", {"value": 42})
            result = await self.tool.get_cached_data("test_key", ttl=60)
            return result

        result = loop.run_until_complete(_test())
        assert result == {"value": 42}

    def test_cache_expiry(self):
        """测试缓存过期"""
        import time

        from hermes_agent.tools.base import BaseTool

        loop = asyncio.get_event_loop()

        async def _test():
            await self.tool.set_cached_data("expire_key", {"value": 1})
            # 手动修改缓存时间为过去
            BaseTool._shared_cache["expire_key"] = (time.time() - 100, {"value": 1})
            result = await self.tool.get_cached_data("expire_key", ttl=60)
            return result

        result = loop.run_until_complete(_test())
        assert result is None  # 已过期

    def test_cache_max_size_eviction(self):
        """测试缓存大小限制"""
        from hermes_agent.tools.base import BaseTool

        loop = asyncio.get_event_loop()
        BaseTool._max_cache_size = 3

        async def _test():
            for i in range(5):
                await self.tool.set_cached_data(f"key_{i}", i)
            return len(BaseTool._shared_cache)

        size = loop.run_until_complete(_test())
        assert size <= 3

        # 恢复
        BaseTool._max_cache_size = 256
        BaseTool._shared_cache.clear()


# ─── FundamentalDataTool ─────────────────────────────────────────────
class TestFundamentalDataTool:
    """FundamentalDataTool 入参/出参/异常测试"""

    def test_missing_ticker_returns_error(self):
        """缺少 ticker 参数应返回错误"""
        from hermes_agent.tools.fundamental_data_tool import FundamentalDataTool

        tool = FundamentalDataTool()
        loop = asyncio.get_event_loop()

        result = loop.run_until_complete(tool.run(ticker=""))
        assert result["status"] == "error"
        assert "ticker" in result["message"].lower() or "代码" in result["message"]

    def test_tool_metadata(self):
        """Tool 元数据完整性"""
        from hermes_agent.tools.fundamental_data_tool import FundamentalDataTool

        tool = FundamentalDataTool()
        assert tool.name == "get_fundamental_data"
        assert tool.description
        assert "ticker" in tool.parameters["properties"]
        assert "ticker" in tool.parameters["required"]

    @patch("hermes_agent.tools.fundamental_data_tool.SecureAsyncClient")
    def test_successful_response(self, mock_client_class):
        """模拟成功响应"""
        from hermes_agent.tools.fundamental_data_tool import FundamentalDataTool

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"pe": 15.0, "pb": 2.5, "roe": 0.18}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        tool = FundamentalDataTool()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(tool.run(ticker="AAPL"))

        assert result.get("pe") == 15.0 or "status" not in result

    @patch("hermes_agent.tools.fundamental_data_tool.SecureAsyncClient")
    def test_network_error_returns_graceful(self, mock_client_class):
        """网络错误应返回优雅错误而非崩溃"""
        from hermes_agent.tools.fundamental_data_tool import FundamentalDataTool

        # Mock rate_limit_aware_request 直接返回错误，避免真实超时等待
        tool = FundamentalDataTool()
        tool.rate_limit_aware_request = AsyncMock(
            return_value={"status": "error", "message": "请求后端接口失败 (重试 3 次): Connection refused"}
        )

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(tool.run(ticker="AAPL"))

        assert result["status"] == "error"
        assert "message" in result


# ─── CompanyNewsTool ─────────────────────────────────────────────────
class TestCompanyNewsTool:
    """CompanyNewsTool 测试"""

    def test_tool_metadata(self):
        """Tool 元数据完整性"""
        from hermes_agent.tools.company_news_tool import GetCompanyNewsTool

        tool = GetCompanyNewsTool()
        assert tool.name
        assert tool.description
        assert tool.parameters


# ─── BrokerMarketTool ────────────────────────────────────────────────
class TestBrokerMarketTool:
    """BrokerMarketTool 测试"""

    def test_tool_metadata(self):
        """Tool 元数据完整性"""
        from hermes_agent.tools.broker_market_tool import BrokerMarketTool

        tool = BrokerMarketTool()
        assert tool.name == "get_broker_market_data"
        assert "action" in tool.parameters["properties"]


# ─── Tool Registry ───────────────────────────────────────────────────
class TestToolRegistry:
    """Tool 注册表测试"""

    def test_auto_registered_tools_not_empty(self):
        """自动注册列表应非空"""
        from hermes_agent.tool_registry import _AUTO_REGISTERED_TOOLS

        assert len(_AUTO_REGISTERED_TOOLS) > 0, "没有任何 Tool 被注册"

    def test_registry_has_core_tools(self):
        """注册表应包含核心 Tool"""
        from hermes_agent.tool_registry import _AUTO_REGISTERED_TOOLS

        tool_names = [cls.name for cls in _AUTO_REGISTERED_TOOLS if hasattr(cls, "name")]  # noqa: E501
        expected = ["get_broker_market_data", "get_fundamental_data"]
        for name in expected:
            assert name in tool_names, f"核心 Tool '{name}' 未注册"

    def test_all_tools_have_run_method(self):
        """所有注册的 Tool 必须有 run 方法"""
        from hermes_agent.tool_registry import _AUTO_REGISTERED_TOOLS

        for cls in _AUTO_REGISTERED_TOOLS:
            assert hasattr(cls, "run"), f"Tool '{getattr(cls, 'name', cls.__name__)}' 缺少 run 方法"  # noqa: E501

    def test_tool_registry_class(self):
        """ToolRegistry 类实例化测试"""
        from hermes_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = registry.get_all_schemas()
        assert len(schemas) > 0
        # 每个 schema 应有 function 字段
        for schema in schemas:
            assert "function" in schema
            assert "name" in schema["function"]
