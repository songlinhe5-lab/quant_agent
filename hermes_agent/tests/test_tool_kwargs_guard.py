"""
LLM 幻觉参数容错测试（2026-08-30 S1 实战回归）。

背景：LLM 习惯性给 get_broker_market_data 传 ``prefer_sources``（该参数只属于
少数工具），而 BrokerMarketTool.run() 未声明该形参 → 抛
``TypeError: run() got an unexpected keyword argument 'prefer_sources'``
→ 工具执行失败、Agent 表现为「调用后无响应」。

修复点：``hermes_agent.middleware.core_tool_execute`` 执行前按
run() 形参 ∪ tool.parameters.properties 白名单裁剪入参。
"""

from __future__ import annotations

import pytest

from hermes_agent.middleware import ToolContext, core_tool_execute


class _BrokerLikeTool:
    """模拟 BrokerMarketTool：只声明 action/ticker 等，不接受 prefer_sources。"""

    name = "get_broker_market_data"
    parameters = {
        "type": "object",
        "properties": {"action": {}, "ticker": {}},
        "required": ["action", "ticker"],
    }

    def __init__(self):
        self.calls = []

    async def run(self, action: str, ticker: str) -> dict:
        self.calls.append({"action": action, "ticker": ticker})
        return {"status": "success", "action": action, "ticker": ticker}


class _LooseTool:
    """带 **kwargs 的工具：应原样透传，不做裁剪。"""

    name = "loose_tool"
    parameters = {"type": "object", "properties": {"ticker": {}}}

    def __init__(self):
        self.seen = None

    async def run(self, ticker: str, **kwargs) -> dict:
        self.seen = {"ticker": ticker, "extra": kwargs}
        return {"status": "success", "seen": self.seen}


@pytest.mark.asyncio
async def test_unexpected_kwarg_is_dropped_instead_of_typeerror():
    """LLM 多传 prefer_sources 时，工具仍正常执行且只收到声明内参数。"""
    tool = _BrokerLikeTool()
    ctx = ToolContext(
        tool_name="get_broker_market_data",
        kwargs={"action": "QUOTE", "ticker": "US.AAPL", "prefer_sources": "futu"},
    )

    result = await core_tool_execute(ctx, {"get_broker_market_data": tool})

    assert result["status"] == "success"
    assert tool.calls == [{"action": "QUOTE", "ticker": "US.AAPL"}]


@pytest.mark.asyncio
async def test_declared_kwargs_pass_through_untouched():
    """白名单内参数必须原样透传，不能误伤。"""
    tool = _BrokerLikeTool()
    ctx = ToolContext(
        tool_name="get_broker_market_data",
        kwargs={"action": "HISTORY", "ticker": "US.NVDA"},
    )

    await core_tool_execute(ctx, {"get_broker_market_data": tool})

    assert tool.calls == [{"action": "HISTORY", "ticker": "US.NVDA"}]


@pytest.mark.asyncio
async def test_var_keyword_tool_receives_everything():
    """run() 带 **kwargs 的工具不做裁剪（本身不会 TypeError）。"""
    tool = _LooseTool()
    ctx = ToolContext(
        tool_name="loose_tool",
        kwargs={"ticker": "US.TSLA", "prefer_sources": "futu"},
    )

    await core_tool_execute(ctx, {"loose_tool": tool})

    assert tool.seen == {"ticker": "US.TSLA", "extra": {"prefer_sources": "futu"}}


@pytest.mark.asyncio
async def test_missing_tool_returns_error_envelope():
    """工具未注册时返回标准错误信封，不抛异常。"""
    ctx = ToolContext(tool_name="not_exist", kwargs={"a": 1})

    result = await core_tool_execute(ctx, {})

    assert result["status"] == "error"
    assert "not_exist" in result["message"]
