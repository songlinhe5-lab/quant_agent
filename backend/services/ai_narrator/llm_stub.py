"""
==========================================================
LLM 离线 Stub 提供器 (SVC-06)
==========================================================

量化主脑重度依赖 LLM（DeepSeek / OpenAI / Ollama）做盘前早报、异动解说、
研报摘要。CI 与本地开发绝不应真实发 HTTP 到外部 API（耗时、不稳定、烧钱、
且破坏测试确定性）。

本模块提供「离线 stub」：在 QUANT_ENV ∈ {offline, testing, dev} 或显式
LLM_STUB=1 时，LLMService 直接短路到 stub，返回确定性内容 + 模拟的
CompletionUsage（token 数），既保证零网络、可重复，又让 SVC-05 的 token
计量插桩能在测试中被验证。

stub 行为：
- 文本模式：返回可配置的确定性摘要文本（默认中文占位，含标的名便于断言）。
- JSON 模式：返回传入 pydantic schema 的「全默认/最小合法」实例的 JSON 字符串，
  确保 generate_pydantic 的 model_validate_json 能通过（不破坏调用方校验逻辑）。
- token 数：prompt_tokens / completion_tokens 可配置（默认按 prompt 长度估算），
  供 QuotaCostMonitor 预算告警链路测试使用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def is_offline_llm_enabled() -> bool:
    """是否启用 LLM 离线 stub。

    触发条件（任一满足）：
    - QUANT_ENV ∈ {offline, testing, dev}
    - LLM_STUB=1
    """
    env = os.getenv("QUANT_ENV", "").lower()
    if env in ("offline", "testing", "dev"):
        return True
    return os.getenv("LLM_STUB", "0").lower() in ("1", "true", "yes", "on")


@dataclass
class _Usage:
    """模拟 OpenAI CompletionUsage。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _StubResponse:
    """模拟 OpenAI chat.completions.create 返回对象。"""

    choices: list[_Choice]
    usage: _Usage


class LLMStubProvider:
    """
    LLM 离线 stub 提供器。

    提供 _make_response(text, prompt_tokens, completion_tokens) 构造一个
    与 OpenAI 响应结构兼容的假对象，可直接喂给 LLMService 的既有解析逻辑
    （choices[0].message.content / usage.prompt_tokens 等）。
    """

    def __init__(
        self,
        default_prompt_tokens: int = 120,
        default_completion_tokens: int = 80,
    ):
        self.default_prompt_tokens = default_prompt_tokens
        self.default_completion_tokens = default_completion_tokens

    def make_text_response(
        self, text: str, prompt_tokens: Optional[int] = None, completion_tokens: Optional[int] = None
    ) -> _StubResponse:
        pt = prompt_tokens or self.default_prompt_tokens
        ct = completion_tokens or self.default_completion_tokens
        return _StubResponse(
            choices=[_Choice(message=_Message(content=text))],
            usage=_Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
        )

    def make_json_response(
        self,
        model: Type[T],
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> _StubResponse:
        """构造一个「最小合法」的 pydantic 实例 JSON 响应，确保 model_validate_json 通过。"""
        pt = prompt_tokens or self.default_prompt_tokens
        ct = completion_tokens or self.default_completion_tokens
        try:
            instance = model.model_construct()  # 不校验地构造默认实例
            payload = instance.model_dump(mode="json")
        except Exception:
            # 极端兜底：返回空对象（调用方校验失败时由其自身降级逻辑接管，不致命）
            payload = {}
        text = json.dumps(payload, ensure_ascii=False)
        return _StubResponse(
            choices=[_Choice(message=_Message(content=text))],
            usage=_Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
        )


# 全局单例（默认配置）
llm_stub_provider = LLMStubProvider()
