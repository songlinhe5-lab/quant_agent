"""WebSearchTool 单元测试：覆盖后端 {code,msg,data} 信封剥离逻辑。

不依赖真实网络/Redis，全程 mock SecureAsyncClient 与缓存方法。
"""

from unittest.mock import AsyncMock, patch

import pytest

from hermes_agent.tools.web_search_tool import WebSearchTool


def _fake_resp(json_body: dict, status_code: int = 200):
    resp = AsyncMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = "err"
    return resp


@pytest.fixture
def tool():
    t = WebSearchTool()
    # 隔离缓存，避免触碰 Redis
    t.get_cached_data = AsyncMock(return_value=None)
    t.set_cached_data = AsyncMock()
    return t


@pytest.mark.asyncio
async def test_strips_backend_envelope(tool):
    """后端返回 {code,msg,data:{status,data}} 信封时，应剥出内层 payload。"""
    envelope = {
        "code": 0,
        "msg": "ok",
        "data": {
            "status": "success",
            "data": [{"title": "阅文", "url": "http://x", "content": "y"}],
        },
    }
    with patch("hermes_agent.tools.web_search_tool.SecureAsyncClient") as cli_cls:
        cli_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=_fake_resp(envelope))
        res = await tool.run(query="阅文 中金 目标价", max_results=5)

    assert res.get("status") == "success"
    assert isinstance(res.get("data"), list) and res["data"]
    tool.set_cached_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_result_passthrough(tool):
    """后端返回空 data（限流/无结果）时，透传 status=success + 空列表。"""
    envelope = {
        "code": 0,
        "msg": "ok",
        "data": {"status": "success", "data": [], "message": "未找到相关结果"},
    }
    with patch("hermes_agent.tools.web_search_tool.SecureAsyncClient") as cli_cls:
        cli_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=_fake_resp(envelope))
        res = await tool.run(query="不可能存在的词zzz", max_results=5)

    assert res.get("status") == "success"
    assert res.get("data") == []
    tool.set_cached_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_error_envelope(tool):
    """后端 HTTP 非 200 时返回 error。"""
    with patch("hermes_agent.tools.web_search_tool.SecureAsyncClient") as cli_cls:
        cli_cls.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=_fake_resp({"code": 1, "msg": "boom"}, status_code=500)
        )
        res = await tool.run(query="x", max_results=5)

    assert res.get("status") == "error"
