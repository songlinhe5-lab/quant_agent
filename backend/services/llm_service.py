import json
import os
from typing import Type, TypeVar

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from backend.core.middleware import httpx_log_request, httpx_log_response

T = TypeVar('T', bound=BaseModel)

class LLMService:
    """
    统一的大语言模型 (LLM) 服务收口。
    负责管理 OpenAI 兼容 API 客户端的生命周期，方便未来一键切换至 GPT-4o, Claude 或其他开源模型。
    """  # noqa: E501
    def __init__(self):
        # 优先读取统一的 LLM 环境变量，如果未配置则向后兼容读取 DEEPSEEK 的配置
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.model_name = os.getenv("LLM_MODEL", "deepseek-chat")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            # 🚨 致命隐患修复：OpenAI SDK 默认 timeout 高达 10 分钟 (600秒)！
            # 若大模型供应商发生静默挂起，后台所有高频的情感分析和选股协程将被卡死 10 分钟。  # noqa: E501
            timeout=30.0,
            max_retries=2,
            http_client=httpx.AsyncClient(event_hooks={'request': [httpx_log_request], 'response': [httpx_log_response]})  # noqa: E501
        )

    def get_client(self) -> AsyncOpenAI:
        """获取异步的大模型客户端实例"""
        return self.client

    async def close(self):
        """安全关闭 OpenAI 客户端底层的 HTTP 连接池"""
        await self.client.close()

    def get_model(self) -> str:
        """获取默认配置的大模型名称"""
        return self.model_name

    async def generate_pydantic(self, prompt: str, response_model: Type[T], system_prompt: str = "You are a helpful assistant.", **kwargs) -> T:  # noqa: E501
        """
        通用结构化输出提取工具函数。
        自动将 Pydantic 模型转换为 JSON Schema 提示词，并强制校验大模型返回的结果。
        """
        # 1. 自动提取 Pydantic 模型的 JSON Schema
        schema_str = json.dumps(response_model.model_json_schema(), ensure_ascii=False)

        # 2. 动态增强 System Prompt
        enhanced_system_prompt = f"{system_prompt}\n\nYou MUST output ONLY a valid JSON object that strictly adheres to the following JSON Schema:\n{schema_str}"  # noqa: E501

        # 3. 发起请求，强制要求 JSON 返回格式
        response = await self.client.chat.completions.create(
            model=self.get_model(),
            temperature=kwargs.get("temperature", 0.0),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": enhanced_system_prompt},
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content or ""

        # 4. 容错处理：清理大模型可能带上的 Markdown 代码块标记 (如 ```json ... ```)
        content = content.strip()
        if content.startswith("```json"): content = content[7:]  # noqa: E701
        elif content.startswith("```"): content = content[3:]  # noqa: E701
        if content.endswith("```"): content = content[:-3]  # noqa: E701
        content = content.strip()

        # 5. 反序列化与强校验
        try:
            return response_model.model_validate_json(content)
        except ValidationError as e:
            print(f"⚠️ [LLMService] 结构化输出校验失败: {e}\n👉 原始输出: {content}")
            raise ValueError(f"LLM 输出未通过 Pydantic 校验: {e}")

# 导出全局单例
llm_service = LLMService()
