---
kind: external_dependency
name: DeepSeek 兼容 OpenAI 协议的 LLM 后端
slug: deepseek-api
category: external_dependency
category_hints:
    - vendor_identity
    - auth_protocol
scope:
    - '**'
---

项目通过 `openai` Python SDK（OpenAI 兼容协议）调用 DeepSeek，默认 base_url 为 `https://api.deepseek.com`，API Key 从环境变量 `LLM_API_KEY` 注入，模型名由 `LLM_MODEL`/`LLM_PRO_MODEL`/`LLM_LIGHTWEIGHT_MODEL` 配置。Agent ReAct 主循环、宏观推演、研究模块均经此客户端发起流式/非流式对话，并统一通过 `_record_usage` 上报 token 用量。熔断保护以 `openai_api` 为 key 注册在 circuit_breaker 中。生产部署时可通过 `LLM_BASE_URL` 切换至其他 OpenAI 兼容后端或本地 Ollama。