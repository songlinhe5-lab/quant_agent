"""
LLM 服务 + 多模型路由 (AI-02)

- ModelTier 分级路由: LIGHTWEIGHT → 小模型 / STANDARD → 默认 / FLAGSHIP → 旗舰
- 版本钉定: 配置文件锁定精确版本号，防静默升级
- Ollama 降级: 主供应商连续失败 N 次后自动切换本地 Ollama
"""

import json
import logging
import os
from enum import Enum
from typing import Dict, Optional, Type, TypeVar

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from backend.core.middleware import httpx_log_request, httpx_log_response

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ModelTier(str, Enum):
    """模型分级：轻量任务 / 标准 / 旗舰"""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    FLAGSHIP = "flagship"


class LLMRouter:
    """
    多模型路由器。

    - 按 tier 返回对应的钉定版本客户端
    - 主供应商连续失败 threshold 次后自动降级至 Ollama
    - 定期探测主供应商恢复后自动切回
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com",
        standard_model: str = "deepseek-v4-flash",
        lightweight_model: str = "deepseek-v4-flash",
        flagship_model: str = "deepseek-v4-pro",
        ollama_base_url: str = "http://localhost:11434/v1",
        fallback_enabled: bool = True,
        fallback_threshold: int = 3,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self._models: Dict[ModelTier, str] = {
            ModelTier.LIGHTWEIGHT: lightweight_model,
            ModelTier.STANDARD: standard_model,
            ModelTier.FLAGSHIP: flagship_model,
        }
        self.ollama_base_url = ollama_base_url
        self.fallback_enabled = fallback_enabled
        self.fallback_threshold = fallback_threshold

        # 主供应商客户端 (延迟初始化)
        self._primary_client: Optional[AsyncOpenAI] = None
        # Ollama 降级客户端 (延迟初始化)
        self._ollama_client: Optional[AsyncOpenAI] = None

        # 每个 tier 独立的失败计数器
        self._failure_counts: Dict[ModelTier, int] = {t: 0 for t in ModelTier}
        # 是否处于降级状态
        self._in_fallback: bool = False

    def _get_primary_client(self) -> AsyncOpenAI:
        if self._primary_client is None:
            key = self.api_key or "sk-not-configured"
            self._primary_client = AsyncOpenAI(
                api_key=key,
                base_url=self.base_url,
                timeout=30.0,
                max_retries=0,  # 由 router 自行管理重试
                http_client=httpx.AsyncClient(
                    event_hooks={
                        "request": [httpx_log_request],
                        "response": [httpx_log_response],
                    }
                ),
            )
        return self._primary_client

    def _get_ollama_client(self) -> AsyncOpenAI:
        if self._ollama_client is None:
            self._ollama_client = AsyncOpenAI(
                api_key="ollama",  # Ollama 不需要真实 key
                base_url=self.ollama_base_url,
                timeout=60.0,
                max_retries=1,
            )
        return self._ollama_client

    def get_model(self, tier: ModelTier = ModelTier.STANDARD) -> str:
        """返回指定 tier 的钉定模型版本号"""
        return self._models[tier]

    def get_client(self, tier: ModelTier = ModelTier.STANDARD) -> AsyncOpenAI:
        """
        获取客户端。若主供应商已触发降级且 fallback 开启，返回 Ollama 客户端。
        """
        if self._in_fallback and self.fallback_enabled:
            return self._get_ollama_client()
        return self._get_primary_client()

    def record_success(self, tier: ModelTier = ModelTier.STANDARD) -> None:
        """记录成功调用，重置失败计数，若处于降级状态则尝试恢复"""
        self._failure_counts[tier] = 0
        if self._in_fallback:
            logger.info("[LLMRouter] 主供应商恢复，切回正常路由")
            self._in_fallback = False

    def record_failure(self, tier: ModelTier = ModelTier.STANDARD) -> None:
        """记录失败调用，达到阈值后触发降级"""
        self._failure_counts[tier] += 1
        if self._failure_counts[tier] >= self.fallback_threshold:
            if self.fallback_enabled and not self._in_fallback:
                logger.warning(f"[LLMRouter] 主供应商连续失败 {self._failure_counts[tier]} 次，降级至 Ollama")
                self._in_fallback = True

    async def health_check(self) -> Dict[str, bool]:
        """探测各供应商可用性"""
        results: Dict[str, bool] = {}

        # 主供应商
        try:
            client = self._get_primary_client()
            await client.models.list()
            results["primary"] = True
        except Exception:
            results["primary"] = False

        # Ollama
        try:
            client = self._get_ollama_client()
            await client.models.list()
            results["ollama"] = True
        except Exception:
            results["ollama"] = False

        return results

    @property
    def is_fallback_active(self) -> bool:
        return self._in_fallback


class LLMService:
    """
    统一的大语言模型 (LLM) 服务收口。
    负责管理 OpenAI 兼容 API 客户端的生命周期，方便未来一键切换至 GPT-4o, Claude 或其他开源模型。

    AI-02 升级：内置 LLMRouter 支持多模型分级路由 + Ollama 降级。
    """

    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.model_name = os.getenv("LLM_MODEL", "deepseek-v4-flash")

        # AI-02: 初始化路由器
        self.router = LLMRouter(
            api_key=self.api_key,
            base_url=self.base_url,
            standard_model=self.model_name,
            lightweight_model=os.getenv("LLM_LIGHTWEIGHT_MODEL", "deepseek-v4-flash"),
            flagship_model=os.getenv("LLM_PRO_MODEL", "deepseek-v4-pro"),
            ollama_base_url=os.getenv("LLM_OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            fallback_enabled=os.getenv("LLM_FALLBACK_ENABLED", "true").lower() == "true",
            fallback_threshold=int(os.getenv("LLM_FALLBACK_THRESHOLD", "3")),
        )

        # 向后兼容：默认客户端
        self._client = None
        if self.api_key:
            self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端（需要已设置 api_key）"""
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=30.0,
            max_retries=2,
            http_client=httpx.AsyncClient(
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                }
            ),
        )

    @property
    def client(self) -> AsyncOpenAI:
        """懒加载客户端：首次访问时若未初始化则尝试初始化"""
        if self._client is None:
            if self.api_key:
                self._init_client()
            else:
                self.api_key = "sk-not-configured"
                self._init_client()
        return self._client

    def get_client(self, tier: Optional[ModelTier] = None) -> AsyncOpenAI:
        """获取客户端。传入 tier 时走路由器，否则返回默认客户端"""
        if tier is not None:
            return self.router.get_client(tier)
        return self.client

    def get_model(self, tier: Optional[ModelTier] = None) -> str:
        """获取模型名称。传入 tier 时返回对应钉定版本，否则返回默认模型"""
        if tier is not None:
            return self.router.get_model(tier)
        return self.model_name

    async def close(self):
        """安全关闭 OpenAI 客户端底层的 HTTP 连接池"""
        if self._client:
            await self._client.close()
        if self.router._primary_client:
            await self.router._primary_client.close()
        if self.router._ollama_client:
            await self.router._ollama_client.close()

    async def generate_pydantic(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str = "You are a helpful assistant.",
        tier: Optional[ModelTier] = None,
        **kwargs,
    ) -> T:
        """
        通用结构化输出提取工具函数。
        自动将 Pydantic 模型转换为 JSON Schema 提示词，并强制校验大模型返回的结果。

        AI-02: 支持 tier 参数选择模型级别。
        """
        schema_str = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        enhanced_system_prompt = f"{system_prompt}\n\nYou MUST output ONLY a valid JSON object that strictly adheres to the following JSON Schema:\n{schema_str}"  # noqa: E501

        client = self.get_client(tier)
        model = self.get_model(tier)

        try:
            response = await client.chat.completions.create(
                model=model,
                temperature=kwargs.get("temperature", 0.0),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": enhanced_system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            if tier is not None:
                self.router.record_success(tier)
        except Exception:
            if tier is not None:
                self.router.record_failure(tier)
            raise

        content = response.choices[0].message.content or ""
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]  # noqa: E701
        elif content.startswith("```"):
            content = content[3:]  # noqa: E701
        if content.endswith("```"):
            content = content[:-3]  # noqa: E701
        content = content.strip()

        try:
            return response_model.model_validate_json(content)
        except ValidationError as e:
            print(f"⚠️ [LLMService] 结构化输出校验失败: {e}\n👉 原始输出: {content}")
            raise ValueError(f"LLM 输出未通过 Pydantic 校验: {e}")


# 导出全局单例
llm_service = LLMService()
