"""验证 LLMService.generate 纯文本生成路径（mock OpenAI 客户端）。

这是修复 AI-01 异动解说员 / 盘前早报运行时 500 的核心：此前二者调用
self.llm.generate(...) 但 LLMService 并无该方法。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai_narrator.llm_service import LLMService, ModelTier


@pytest.fixture(autouse=True)
def _force_online_llm(monkeypatch):
    """强制关闭 SVC-06 离线 stub，验证真实 OpenAI client 调用路径（见同名说明）。"""
    monkeypatch.setattr(
        "backend.services.ai_narrator.llm_service.LLMService._is_offline",
        lambda self: False,
    )


@pytest.mark.asyncio
async def test_generate_returns_stripped_text(monkeypatch):
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="  你好世界  "))])
    )
    monkeypatch.setattr("backend.services.ai_narrator.llm_service.AsyncOpenAI", lambda **k: fake)
    svc = LLMService()
    out = await svc.generate("hi", tier=ModelTier.STANDARD)
    assert out == "你好世界"


@pytest.mark.asyncio
async def test_generate_builds_messages_with_system_prompt(monkeypatch):
    fake = MagicMock()
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    fake.chat.completions.create = fake_create
    monkeypatch.setattr("backend.services.ai_narrator.llm_service.AsyncOpenAI", lambda **k: fake)
    svc = LLMService()
    await svc.generate("user", system_prompt="sys", tier=ModelTier.STANDARD, temperature=0.3)
    msgs = captured["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "user"}
    assert captured["temperature"] == 0.3


@pytest.mark.asyncio
async def test_generate_raises_on_failure(monkeypatch):
    fake = MagicMock()

    async def boom(**kwargs):
        raise RuntimeError("upstream dead")

    fake.chat.completions.create = boom
    monkeypatch.setattr("backend.services.ai_narrator.llm_service.AsyncOpenAI", lambda **k: fake)
    svc = LLMService()
    with pytest.raises(RuntimeError):
        await svc.generate("hi", tier=ModelTier.STANDARD)
