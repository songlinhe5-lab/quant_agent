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
from typing import Any, AsyncGenerator, Dict, Optional, Type, TypeVar

import httpx
from openai import AsyncOpenAI, RateLimitError
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
        # Ollama 可达性缓存 (None=未探测, True/False=探测结果)。防降级到死路。
        self._ollama_available: Optional[bool] = None

    def _get_primary_client(self) -> AsyncOpenAI:
        if self._primary_client is None:
            key = self.api_key or "sk-not-configured"
            self._primary_client = AsyncOpenAI(
                api_key=key,
                base_url=self.base_url,
                timeout=30.0,
                max_retries=2,  # 网络抖动透明重试, 缓解瞬时 Connection error (由 router 统一管理重试)
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

    def _probe_ollama_sync(self) -> bool:
        """同步短超时探测 Ollama 可达性 (结果缓存, 防阻塞主调用链)。

        用于降级前确认降级目标可用, 避免无 Ollama 环境降级到死路形成死锁。
        """
        if self._ollama_available is not None:
            return self._ollama_available
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(self.ollama_base_url.rstrip("/") + "/models")
                self._ollama_available = r.status_code < 500
        except Exception:
            self._ollama_available = False
        if not self._ollama_available:
            logger.warning(f"[LLMRouter] Ollama 不可达 ({self.ollama_base_url})，降级目标无效，维持主链路")
        return self._ollama_available

    def get_model(self, tier: ModelTier = ModelTier.STANDARD) -> str:
        """返回指定 tier 的钉定模型版本号"""
        return self._models[tier]

    def get_client(self, tier: ModelTier = ModelTier.STANDARD) -> AsyncOpenAI:
        """
        获取客户端。若主供应商已触发降级且 fallback 开启，返回 Ollama 客户端。

        STRAT/RISK 加固: 降级前探测 Ollama 可达性, 若降级目标本身不可达则维持主链路,
        避免"降级到死路"导致 `_in_fallback` 无法恢复的死锁。
        """
        if self._in_fallback and self.fallback_enabled:
            if self._probe_ollama_sync():
                return self._get_ollama_client()
            logger.warning("[LLMRouter] Ollama 不可达，跳过降级，继续使用主供应商")
            return self._get_primary_client()
        return self._get_primary_client()

    def record_success(self, tier: ModelTier = ModelTier.STANDARD) -> None:
        """记录成功调用，重置失败计数，若处于降级状态则尝试恢复"""
        self._failure_counts[tier] = 0
        if self._in_fallback:
            logger.info("[LLMRouter] 主供应商恢复，切回正常路由")
            self._in_fallback = False

    def record_failure(self, tier: ModelTier = ModelTier.STANDARD) -> None:
        """记录失败调用，达到阈值后触发降级。

        加固: 触发降级前探测 Ollama, 不可达则不降级 (避免进入无恢复可能的死路)。
        """
        self._failure_counts[tier] += 1
        if self._failure_counts[tier] >= self.fallback_threshold:
            if self.fallback_enabled and not self._in_fallback:
                if not self._probe_ollama_sync():
                    logger.warning(
                        f"[LLMRouter] 主供应商连续失败 {self._failure_counts[tier]} 次但 Ollama 不可达，"
                        "不降级，保持主链路重试"
                    )
                    return
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

        # Ollama (同步写入可达性缓存, 供 get_client/record_failure 降级决策复用)
        try:
            client = self._get_ollama_client()
            await client.models.list()
            results["ollama"] = True
            self._ollama_available = True
        except Exception:
            results["ollama"] = False
            self._ollama_available = False

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

        # SVC-06: 离线 stub 模式开关（None=按环境自动判定，True/False=强制覆盖）。
        # 用于测试注入或本地显式离线。默认 None → 由 llm_stub.is_offline_llm_enabled() 决定。
        self._offline_override: Optional[bool] = None

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

    def _is_offline(self) -> bool:
        """SVC-06: 是否走 LLM 离线 stub（不触网）。

        优先级：实例 _offline_override 显式覆盖 > 环境变量自动判定。
        """
        if self._offline_override is not None:
            return self._offline_override
        from backend.services.ai_narrator.llm_stub import is_offline_llm_enabled

        return is_offline_llm_enabled()

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

        # SVC-06: 离线 stub 短路（不触网，返回确定性最小合法 JSON，供调用方校验）
        if self._is_offline():
            from backend.services.ai_narrator.llm_stub import llm_stub_provider

            response = llm_stub_provider.make_json_response(response_model)
            # 走真实 token 计量插桩，验证 SVC-05 计量链路（异常安全）
            await self._record_token_usage(response)
            content = response.choices[0].message.content or ""
            try:
                return response_model.model_validate_json(content)
            except ValidationError as e:
                raise ValueError(f"LLM 离线 stub 输出未通过校验: {e}")

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

    async def _record_token_usage(self, response: Any) -> None:
        """从 OpenAI 响应提取 token 消耗并异步记录（异常安全，不拖累热路径）。

        store.record 已是异常安全的轻量 Redis hincrby，直接 await 即可，
        无需 fire-and-forget（避免任务调度不确定性，且 record 不抛回业务层）。
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        try:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            total = getattr(usage, "total_tokens", 0) or 0
            from backend.services.ai_narrator.token_usage_store import token_usage_store

            store = token_usage_store
            if not store.enabled:
                return
            await store.record(prompt, completion, total)
        except Exception:  # noqa: BLE001
            pass

    async def generate_stream(
        self,
        user_prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        tier: Optional[ModelTier] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """真·token 流式文本生成（SSE 场景）：逐增量片段 yield。

        与 generate 同构，但 stream=True。调用方应在首个片段到达前就给用户展示进度，
        避免生成期间长时间空白。离线 stub 模式分段回放同一段确定性文本。
        """
        # SVC-06: 离线 stub 短路（分段回放，保证离线时流式消费方逻辑一致）
        if self._is_offline():
            from backend.services.ai_narrator.llm_stub import llm_stub_provider

            response = llm_stub_provider.make_text_response(
                f"[离线stub] 已为 prompt 生成确定性解说：{user_prompt[:40]}…"
            )
            await self._record_token_usage(response)
            text = response.choices[0].message.content or ""
            for i in range(0, len(text), 8):
                yield text[i : i + 8]
            return

        client = self.get_client(tier)
        model = self.get_model(tier)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 优先请求计量 (include_usage)；个别兼容端点不支持该参数时去掉它重试，不阻断生成。
        # 流式响应的 usage 挂在最后一个 chunk 上（delta 为空，不产生 yield）。
        async def _create_stream():
            """建立流式连接；先带 include_usage，失败则去掉该参数重试（兼容旧端点）。"""
            err: Optional[Exception] = None
            for use_usage in (True, False):
                try:
                    kwargs: Dict[str, Any] = {"stream": True}
                    if use_usage:
                        kwargs["stream_options"] = {"include_usage": True}
                    return await client.chat.completions.create(
                        model=model,
                        temperature=temperature,
                        messages=messages,
                        **kwargs,
                    )
                except Exception as e:  # noqa: BLE001
                    err = e
            if err is not None:
                raise err

        def _is_rate_limit(err: Exception) -> bool:
            """判断是否为限流(429)：覆盖 openai RateLimitError / httpx 429 / 文本匹配。"""
            if isinstance(err, RateLimitError):
                return True
            status = getattr(err, "status_code", None)
            if status == 429:
                return True
            return "429" in str(err)

        # 429 限流指数退避重试：最多额外重试 3 次（退避 2/4/8s），仍失败再上抛。
        # 仅在"尚未收到首个 token"的建立阶段重试，避免重复消费已流出的内容；
        # 限流不计入 router 失败计数（Ollama 不可达时误降级无意义）。
        MAX_RETRY = 3
        backoff = 2.0
        stream = None
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRY + 1):
            try:
                stream = await _create_stream()
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if not _is_rate_limit(e):
                    raise
                if attempt < MAX_RETRY:
                    await asyncio.sleep(backoff * (2**attempt))
                    continue
                raise
        if stream is None:
            if last_err is not None:
                raise last_err
            raise RuntimeError("流式连接建立失败")

        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    await self._record_token_usage(chunk)
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            if tier is not None:
                self.router.record_success(tier)
        except Exception:
            if tier is not None:
                self.router.record_failure(tier)
            raise

    async def generate(
        self,
        user_prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: Optional[str] = None,
        tier: Optional[ModelTier] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        """通用纯文本生成（非结构化）。供 AI-01 异动解说员、盘前早报等调用。

        与 generate_pydantic 同构，但返回裸文本字符串；失败时抛出异常，
        由调用方（AI-01 / 早报）自身的降级逻辑接管。
        """
        client = self.get_client(tier)
        model_name = model or self.get_model(tier)

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # SVC-06: 离线 stub 短路（不触网，返回确定性文本，供调用方降级逻辑消费）
        if self._is_offline():
            from backend.services.ai_narrator.llm_stub import llm_stub_provider

            response = llm_stub_provider.make_text_response(
                f"[离线stub] 已为 prompt 生成确定性解说：{user_prompt[:40]}…"
            )
            await self._record_token_usage(response)
            return response.choices[0].message.content.strip()

        try:
            response = await client.chat.completions.create(
                model=model_name,
                temperature=temperature,
                messages=messages,
                **kwargs,
            )
            if tier is not None:
                self.router.record_success(tier)
        except Exception:
            if tier is not None:
                self.router.record_failure(tier)
            raise

        content = response.choices[0].message.content or ""
        await self._record_token_usage(response)
        return content.strip()


# 导出全局单例
llm_service = LLMService()
