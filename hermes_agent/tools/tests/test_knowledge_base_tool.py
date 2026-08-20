"""KnowledgeBaseTool 全局知识库检索测试：覆盖本地 miss 时 web_search 兜底。

不依赖真实 PG/网络/Redis，全程 mock _search_pg 与 WebSearchTool.run。
"""

from unittest.mock import AsyncMock, patch

import pytest

from hermes_agent.tools.knowledge_base_tool import KnowledgeBaseTool


@pytest.mark.asyncio
async def test_hit_returns_kb_result():
    """本地知识库命中时直接返回, 不触发 web_search 兜底。"""
    tool = KnowledgeBaseTool()
    kb_summary = "🎯 根据查询 '阅文' 检索到 2 个相关片段：\n[1] ..."
    with (
        patch.object(tool, "_search_pg", return_value=kb_summary) as m,
        patch(
            "hermes_agent.tools.knowledge_base_tool.KnowledgeBaseTool._fallback_web_search",
            new=AsyncMock(),
        ) as fb,
    ):
        res = await tool.run(query="阅文 研报", limit=5)

    assert res["status"] == "success"
    assert res["skip_cache"] is False
    assert "检索到 2 个相关片段" in res["data"]["content"]
    m.assert_called_once()
    fb.assert_not_awaited()


@pytest.mark.asyncio
async def test_miss_falls_back_to_web_search():
    """本地 miss 时联动 web_search 兜底, 返回网络结果且不落缓存。"""
    tool = KnowledgeBaseTool()
    kb_summary = "未能在全局知识库中检索到与 '阅文集团 0772.HK 研报 目标价 盈利预测' 高度相关的内容。"
    fallback = (
        "🌐 全局知识库未命中，以下为网络搜索兜底结果（建议结合 download_report 下载研报后解析）：\n[1] 阅文集团目标价"
    )
    with (
        patch.object(tool, "_search_pg", return_value=kb_summary),
        patch.object(tool, "_fallback_web_search", new=AsyncMock(return_value=fallback)) as fb,
    ):
        res = await tool.run(query="阅文集团 0772.HK 研报 目标价 盈利预测", limit=5)

    assert res["status"] == "success"
    assert res["source"] == "web_search_fallback"
    assert res["skip_cache"] is True
    assert "网络搜索兜底" in res["data"]["content"]
    fb.assert_awaited_once()


@pytest.mark.asyncio
async def test_miss_web_search_unavailable_keeps_miss():
    """本地 miss 且 web_search 也不可用时, 保留原始 miss 提示并标记 skip_cache。"""
    tool = KnowledgeBaseTool()
    kb_summary = "未能在全局知识库中检索到与 'xxx' 高度相关的内容。"
    with (
        patch.object(tool, "_search_pg", return_value=kb_summary),
        patch.object(tool, "_fallback_web_search", new=AsyncMock(return_value=None)),
    ):
        res = await tool.run(query="xxx", limit=5)

    assert res["status"] == "success"
    assert res["skip_cache"] is True
    assert "未能在全局知识库中检索到" in res["data"]["content"]


@pytest.mark.asyncio
async def test_fallback_web_search_formats_hits():
    """_fallback_web_search 把 web_search 的 dict hits 格式化为可读文本。"""
    tool = KnowledgeBaseTool()
    fake_hits = [
        {"title": "阅文集团目标价", "url": "https://x.com/1", "snippet": "中金给予买入"},
        {"title": "第二篇", "url": "https://x.com/2", "snippet": "盈利预测上调"},
    ]
    with patch("hermes_agent.tools.web_search_tool.WebSearchTool") as ws_cls:
        ws_cls.return_value.run = AsyncMock(return_value={"status": "success", "data": fake_hits})
        out = await tool._fallback_web_search("阅文 研报", 5)

    assert out is not None
    assert "阅文集团目标价" in out
    assert "https://x.com/1" in out
