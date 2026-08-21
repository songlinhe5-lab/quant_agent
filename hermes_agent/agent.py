import asyncio
import functools
import json
import os
import re
from typing import Any, Dict, List, Optional, cast

import redis.asyncio as redis
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator
from rich.console import Console
from rich.markdown import Markdown

from backend.services.ai_narrator.token_usage_store import token_usage_store
from hermes_agent.memory_ops import MemoryOperationsMixin

# 盘中主脑 prompt（与 IDE 编码宪法 AGENTS.md 分离）
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SYSTEM_PROMPT_PATH = os.path.join(_REPO_ROOT, "prompts", "system", "HERMES.md")


class SessionTitleValidator(BaseModel):
    """Pydantic 模型：用于校验和清洗大模型生成的会话标题"""

    title: str

    @field_validator("title")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        # 1. 违禁词库拦截 (可扩展为从 Redis 动态读取)
        banned_words = ["测试违禁", "色情", "暴力", "政治敏感"]
        if any(banned in v for banned in banned_words):
            raise ValueError("触发敏感词风控拦截")

        # 2. 乱码清洗：仅保留中文、英文字母、数字和基础空格/横线，过滤非法语义字符
        cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s\-]", "", v)
        if not cleaned.strip():
            raise ValueError("标题清洗后为空(疑似大模型产生纯乱码幻觉)")

        # 3. 长度硬限制拦截
        return cleaned[:15].strip()


def with_reference_check(max_retries: int = 2):
    """
    Agent 专属输出自愈装饰器。
    校验大模型返回的最终内容中，正文引用的 [X] 是否都在文末的参考文献列表中。
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                result = await func(self, *args, **kwargs)
                if not isinstance(result, str):
                    return result

                # 💡 如果是自愈轮次（判断 self.messages[-2] 是否为拦截提示），跳过后续校验直接返回
                is_correction = len(self.messages) >= 2 and "系统校验拦截" in str(self.messages[-2].get("content", ""))
                if is_correction:
                    return result

                # 💡 使用正则兼容大模型花式的 Markdown 标题和冒号
                parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", result)
                if len(parts) > 1:
                    main_text = parts[0]
                    ref_text = parts[-1]
                else:
                    main_text = result
                    ref_text = ""

                # 提取正文和参考列表中的引用序号
                citations = set(re.findall(r"\[(\d+)\]", main_text))
                references = set(re.findall(r"\[(\d+)\]", ref_text))

                missing = citations - references
                if missing and attempt < max_retries - 1:
                    self.console.print(
                        f"\n[bold yellow]⚠️ [Auto-Correction] 检测到正文引用了 {missing} 但未列出参考文献，触发大模型自愈 (第 {attempt + 1} 次)...[/bold yellow]"
                    )

                    # 注入纠错提示
                    self.messages.append(
                        {
                            "role": "user",
                            "content": f"⚠️ 系统校验拦截：你在刚才的回答正文中使用了引用标号 {', '.join([f'[{m}]' for m in missing])}，但在文末并没有提供对应的「📚 参考文献」列表，或者列表中遗漏了这些序号。请补充完整的参考文献列表并重新输出完整的回答。",
                        }
                    )
                    await self._save_session()
                    continue  # 拦截本次返回，重新进入循环让 LLM 再生成一次

                return result

        return wrapper

    return decorator


class HermesAgent(MemoryOperationsMixin):
    """
    Hermes Agent 核心主脑类
    职责：维护上下文状态、对接大模型 API、调度 ReAct 工作流。
    """

    # AGENT-04: ReAct 最大迭代次数唯一收敛（两套循环共享，禁止重复字面量）
    _MAX_REACT_ITERATIONS = 8

    # A-2.1: 抽 _build_request_kwargs 辅助函数，统一 schema/model/temperature/tools 构造（AGENT-04）
    def _build_request_kwargs(self, stream: bool = False):
        """
        构建统一的 LLM 请求参数。

        Args:
            stream: 是否开启流式输出

        Returns:
            dict: 包含 model/messages/temperature/stream/stream_options/tools 的请求参数字典
        """
        model_to_use = self.model  # 暂时禁用视觉模型，强制使用文本模型
        schemas = self.tool_registry.get_all_schemas()

        request_kwargs = {
            "model": model_to_use,
            "messages": cast(Any, self.messages),
            "temperature": 0.0,  # 量化场景要求低随机性，确保结果确定性
            "stream": stream,
        }

        # 仅当启用流式时添加 stream_options（DeepSeek API 要求）
        if stream:
            request_kwargs["stream_options"] = {"include_usage": True}

        if schemas:
            request_kwargs["tools"] = schemas

        return request_kwargs

    # A-2.2: 抽 _record_usage 辅助函数，统一 token 计量埋点逻辑（AGENT-04）
    async def _record_usage(self, usage):
        """
        统一的 token 使用量记录辅助函数。

        Args:
            usage: OpenAI API 返回的 usage 对象（包含 prompt_tokens/completion_tokens/total_tokens）
        """
        if usage is not None:
            await token_usage_store.record(
                prompt_tokens=getattr(usage, "prompt_tokens", 0),
                completion_tokens=getattr(usage, "completion_tokens", 0),
                total_tokens=getattr(usage, "total_tokens", 0),
            )

    # A-2.3: 抽 _safe_execute_tool 辅助函数，统一工具执行逻辑（AGENT-04）
    # AGENT-02 middleware seam: 未来中间件管线（审批闸门 → 失败熔断 → 结果分类 → 脱敏 → 缓存 → 限流）
    # 的唯一挂点。当前仅做 json.loads + execute + try/except，后续 AGENT-02 实装时在此处
    # 插入 pre_execute → execute → post_execute 责任链
    async def _safe_execute_tool(self, tool_name: str, arguments_str: str):
        """
        统一的工具执行辅助函数。

        Args:
            tool_name: 工具名称
            arguments_str: JSON 格式的工具参数字符串

        Returns:
            dict: 工具执行结果，异常时返回 {"status": "error", "message": "..."}
        """
        try:
            args = json.loads(arguments_str)
            # 💡 核心修复：execute 是 async 函数，必须 await
            return await self.tool_registry.execute(tool_name, **args)
        except Exception as e:
            return {"status": "error", "message": f"工具执行异常: {str(e)}"}

    def __init__(
        self,
        tool_registry,
        system_prompt_path: Optional[str] = None,
        session_id: str = "default",
        llm_client: Optional[AsyncOpenAI] = None,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.console = Console()
        self.tool_registry = tool_registry
        self.system_prompt_path = system_prompt_path or DEFAULT_SYSTEM_PROMPT_PATH
        self.session_id = session_id
        self.memory_key = f"hermes:memory:{self.session_id}"

        # 💡 初始化同步 Redis 客户端 (极低延迟，可直接替换原有文件 I/O)
        if redis_client:
            self.redis_client = redis_client
        else:
            self.redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD") or "quant_redis_secret_2026",
                decode_responses=True,
            )

        # 💡 是否开启 Debug 模式
        self.debug_mode = os.getenv("QUANT_ENV") == "development"

        # 💡 初始化 DeepSeek 客户端 (复用 OpenAI SDK)
        if llm_client:
            self.client = llm_client
        else:
            api_key = os.getenv("LLM_API_KEY")
            if not api_key:
                print("⚠️ 警告: 未找到 LLM_API_KEY 环境变量，请在 .env 中配置。")
            api_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
            self.client = AsyncOpenAI(api_key=api_key, base_url=api_base_url)
        self.model = os.getenv("LLM_MODEL", "deepseek-v4-flash")
        self.pro_model = os.getenv("LLM_PRO_MODEL", "deepseek-v4-pro")
        self.vision_model = os.getenv("LLM_VISION_MODEL", "deepseek-v4-pro")  # 保留配置，但暂时禁用

        # 1. 加载盘中主脑指令 (prompts/system/HERMES.md)
        self.system_prompt = self._load_system_prompt()

        # 2. 初始化对话记忆 (Context Window)
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

        print(f"🧠 [Agent Brain] 初始化完成。主推理: {self.model} | 深度分析: {self.pro_model}")

    async def initialize(self):
        """异步初始化：从 Redis 加载历史记忆"""
        await self._load_session()

    def _apply_system_prompt(self, messages: list):
        """辅助方法：强制使用最新版本的系统指令覆盖历史记忆"""
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = self.system_prompt
        else:
            messages.insert(0, {"role": "system", "content": self.system_prompt})

    # 💡 COPILOT-11: 记忆管理方法已拆分至 memory_ops.py (MemoryOperationsMixin)
    # 包含: _load_session / _save_session / _heal_memory / _compress_memory
    #       _estimate_tokens / _guard_before_llm / _sink_to_kb / _async_db_upsert

    def _load_system_prompt(self) -> str:
        """读取盘中主脑指令（HERMES.md）。代码生成/图表风控已写入该文件 §9，不再在此拼接。"""
        if os.path.exists(self.system_prompt_path):
            with open(self.system_prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        print(f"⚠️ 警告: 未找到系统指令文件 {self.system_prompt_path}")
        return "你是一个专业的量化交易 Agent。"

    async def run_cli(self):
        """
        启动交互终端
        """
        self.console.print("\n[bold green]🟢 [Terminal] 量化网关 CLI 启动。输入 'exit' 退出。[/bold green]")
        while True:
            try:
                user_input = self.console.input("\n[bold cyan][Trader] 👤:[/bold cyan] ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    break

                # 新增快捷指令：一键清空历史记忆，防止旧报错导致大模型产生幻觉
                if user_input.lower() == "/clear":
                    self.messages = [{"role": "system", "content": self.system_prompt}]
                    await self._save_session()
                    self.console.print("\n[bold yellow]🧹 [Memory] 历史记忆已彻底清空，大脑已重置！[/bold yellow]")
                    continue

                if not user_input:
                    continue

                # 在加入新指令前，强制运行上下文体检自愈
                self._heal_memory()
                # 将用户输入加入上下文
                self.messages.append({"role": "user", "content": user_input})
                await self._save_session()

                # 触发大模型思考与工具调用循环
                await self._step_loop()

            except KeyboardInterrupt:
                print("\n\n[System] 收到强制中断信号，正在安全关闭...")
                break
            except Exception as e:
                print(f"\n❌ [System Fatal] 核心循环异常: {e}")

    async def chat(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        异步单轮对话接口，专门提供给 FastAPI / WebSocket 等外部程序调用。
        """
        # 新增快捷指令：一键清空历史记忆
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            return "🧹 历史记忆已彻底清空，大脑已重置！"

        self._heal_memory()

        # 💡 多模态支持：如果携带了图片等附件，采用 OpenAI 兼容的视觉/多模态消息数组格式
        if user_input.strip() or attachments:
            # 暂时禁用图片识别：attachments 不再作为消息内容的一部分发送给 LLM
            # 只发送文本内容
            if user_input.strip():
                self.messages.append({"role": "user", "content": user_input.strip()})
        await self._save_session()

        if len(self.messages) <= 1:
            return ""

        try:
            result = await self._step_loop()
            final = result if result else "⚠️ 思考完成，但未返回任何内容。"
            # 📥 对话事实沉淀：将明确数值/事实结论写入知识库 (PR-B)
            if final and not final.startswith("⚠️") and not final.startswith("❌"):
                await self._sink_to_kb(final)
            return final
        except Exception as e:
            return f"❌ [Agent Runtime Error] 运行异常: {e}"

    @with_reference_check(max_retries=2)
    async def _step_loop(self):
        """
        核心 ReAct 执行循环 (Plan -> Tool -> Verify -> Output)
        """
        max_iterations = self._MAX_REACT_ITERATIONS
        for i in range(max_iterations):
            print(f"🤖 [Agent] 思考中 (第 {i + 1} 轮)...")
            try:
                # 💡 动态模型切换：如果最新一条用户消息包含图片，自动切换至多模态视觉模型
                # A-2.1: 使用统一的 request_kwargs 构造逻辑（AGENT-04）
                request_kwargs = self._build_request_kwargs(stream=False)

                if self.debug_mode:
                    self.console.print("\n[dim cyan]--- 🐛 [Debug] LLM Request ---[/dim cyan]")
                    # 使用 default=str 防止遇到无法序列化的特殊对象导致崩溃
                    self.console.print(
                        f"[dim]Messages: {json.dumps(request_kwargs['messages'], ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    if "tools" in request_kwargs:
                        self.console.print(f"[dim]Tools Configured: {len(request_kwargs['tools'])}[/dim]")
                    self.console.print("[dim cyan]------------------------------[/dim cyan]\n")

                # 🛡️ TokenGuard：每次 ReAct 迭代真正发 LLM 前做限流 + 预算护栏
                await self._guard_before_llm()

                response = await self.client.chat.completions.create(**request_kwargs)
                msg = response.choices[0].message

                # 📊 Token 计量埋点：A-2.2 使用统一的 _record_usage 辅助函数（AGENT-04）
                await self._record_usage(getattr(response, "usage", None))

                if self.debug_mode:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug] LLM Response ---[/dim magenta]")
                    self.console.print(
                        f"[dim]{json.dumps(msg.model_dump(exclude_none=True), ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    self.console.print("[dim magenta]-------------------------------[/dim magenta]\n")

                # 将模型回复加入上下文 (使用 exclude_none 防止结构冗余)
                self.messages.append(msg.model_dump(exclude_none=True))
                # ❌ 移除这里的 self._save_session()，防止中途崩溃导致上下文未闭环就被写入硬盘

                # 如果模型决定调用工具
                if msg.tool_calls:
                    # A-2.3: 使用统一的 _safe_execute_tool 辅助函数（AGENT-04）
                    async def execute_tool(tc):
                        print(f"🧠 [Agent Plan] 决定调用工具: {tc.function.name}")
                        return await self._safe_execute_tool(tc.function.name, tc.function.arguments)

                    tasks = [execute_tool(tc) for tc in msg.tool_calls]
                    # 并发执行所有工具，并捕获底层的崩溃防止跳过组装步骤
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for tool_call, result in zip(msg.tool_calls, results):
                        if isinstance(result, Exception):
                            result = {"status": "error", "message": f"并发调度异常: {str(result)}"}
                        # 将工具执行结果作为 tool role 加入上下文
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                    await self._save_session()  # ✅ 工具结果全部安全追加完毕后，再进行本地保存
                    # 继续下一轮循环，让模型根据工具结果进行 Verify 和 Output
                else:
                    await self._save_session()  # ✅ 如果不需要调用工具，则证明推理完整结束，直接保存
                    # 模型没有调用工具的需求，得出最终结论 (Output)
                    self.console.print("\n[bold green]💬 [Agent Output]:[/bold green]")
                    self.console.print(Markdown(msg.content or ""))  # 加入 or "" 防止模型未输出内容导致 Rich 渲染报错
                    return msg.content or ""

            except Exception as e:
                print(f"❌ [Agent API Error] 大模型交互异常: {e}")
                return f"❌ 大模型交互异常: {e}"

        print("⚠️ [Agent Warning] 达到最大思考循环次数，启动强制熔断恢复策略。")
        try:
            # 强制恢复：向模型注入提示，要求其根据现有上下文强制输出结论
            self.messages.append(
                {
                    "role": "user",
                    "content": "⚠️ 系统强制指令：你的思考与工具调用次数已达上限。请立即停止尝试使用工具，仅根据当前上下文中已获取到的数据，给出一个最终的分析总结。",
                }
            )

            # 进行最后一次无 Tools 的 API 请求，强制剥夺模型的工具使用权
            # 💡 使用 pro 模型进行深度分析总结，提升最终结论质量
            # 🛡️ TokenGuard：最终总结前也做预算护栏，防止历史累积过大
            await self._guard_before_llm(max_input_tokens=150000)
            response = await self.client.chat.completions.create(
                model=self.pro_model, messages=cast(Any, self.messages), temperature=0.0
            )
            # 📊 Token 计量埋点：A-2.2 pro 最终总结（非流式）使用统一的 _record_usage（AGENT-04）
            await self._record_usage(getattr(response, "usage", None))
            final_msg = response.choices[0].message
            self.messages.append(final_msg.model_dump(exclude_none=True))
            await self._save_session()

            self.console.print("\n[bold yellow]💬 [Agent Output (强制总结)]:[/bold yellow]")
            self.console.print(Markdown(final_msg.content or ""))
            return final_msg.content or ""
        except Exception as e:
            print(f"❌ [Agent API Error] 强制恢复失败: {e}")
            return f"❌ 强制恢复失败: {e}"

    async def chat_stream_async(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None):
        """
        异步流式对话接口 (供 FastAPI 与支持异步的 CLI 终端调用)
        """
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            yield {"type": "text_chunk", "content": "🧹 历史记忆已彻底清空，大脑已重置！"}
            return

        self._heal_memory()

        # 💡 多模态支持：将 base64 附件拼装为支持视觉大模型的数组结构
        # MRKT-05: 个股分析时自动注入宏观判因上下文
        # 💡 [Prefix-Cache 优化] market_ctx 必须折叠进 user message 末尾，而非单独 append 为第二条 system 消息。
        # 原因：DeepSeek 上下文缓存按「相同输入前缀」自动命中，若把变化的 market_ctx 插在 system 之后，
        # 会打断稳定前缀导致缓存几乎全 miss（实测命中率仅 11%）。折叠进 user 轮后，
        # system(HERMES.md) 成为唯一稳定前缀，可复用到 ~100%，单轮 input token 重复费砍掉九成。
        enriched_user_input = user_input.strip() if user_input.strip() else ""
        if user_input.strip():
            try:
                from backend.services.market_review.context_injector import try_inject_market_context

                market_ctx = await try_inject_market_context(user_input.strip())
                if market_ctx:
                    enriched_user_input = f"{user_input.strip()}\n\n{market_ctx}"
            except Exception:
                pass  # 判因注入失败不阻断主流程

        if enriched_user_input or attachments:
            # 暂时禁用图片识别：attachments 不再作为消息内容的一部分发送给 LLM
            # 只发送文本内容
            if enriched_user_input:
                self.messages.append({"role": "user", "content": enriched_user_input})

        await self._save_session()

        if len(self.messages) <= 1:
            self.console.print("⚠️ [Agent Stream] 上下文为空 (或仅含 System 指令)，拒绝发起大模型请求。")
            return  # 仅有 system prompt 时不触发大模型请求

        max_iterations = self._MAX_REACT_ITERATIONS
        for i in range(max_iterations):
            # 💡 每轮 ReAct 开始前发送心跳，防止工具完成后到下一轮 LLM 响应前的空白期被 Cloudflare 掐断
            yield {"type": "heartbeat", "tick": i + 1}
            self.console.print(f"🤖 [Agent Stream] 流式思考中 (第 {i + 1} 轮)...")
            try:
                # 💡 动态模型切换：如果最新一条用户消息包含图片，自动切换至多模态视觉模型
                # A-2.1: 使用统一的 request_kwargs 构造逻辑（AGENT-04）
                request_kwargs = self._build_request_kwargs(stream=True)

                if self.debug_mode:
                    self.console.print("\n[dim cyan]--- 🐛 [Debug Stream] LLM Request Payload ---[/dim cyan]")
                    self.console.print(
                        f"[dim]{json.dumps(request_kwargs['messages'], ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    self.console.print("[dim cyan]----------------------------------------------[/dim cyan]\n")

                self.console.print("🌐 [Chat API] 正在向大模型发起流式请求 (等待首个 Token)...")

                # 🛡️ TokenGuard：流式 ReAct 迭代发 LLM 前做限流 + 预算护栏
                await self._guard_before_llm()

                # 💡 心跳保活：LLM 推理期间定期发送 heartbeat，防止 Cloudflare 100s 空闲超时掐断连接
                llm_response_queue: asyncio.Queue = asyncio.Queue()

                async def do_llm_inference():
                    try:
                        resp = await self.client.chat.completions.create(**request_kwargs)
                        await llm_response_queue.put(("ok", resp))
                    except Exception as e:
                        await llm_response_queue.put(("error", e))

                inference_task = asyncio.create_task(do_llm_inference())
                llm_heartbeat_count = 0
                status, response_or_error = None, None

                while not inference_task.done():
                    try:
                        status, response_or_error = await asyncio.wait_for(llm_response_queue.get(), timeout=15.0)
                        break  # 推理完成，跳出心跳循环
                    except asyncio.TimeoutError:
                        llm_heartbeat_count += 1
                        yield {"type": "heartbeat", "tick": f"llm-{llm_heartbeat_count}"}
                        self.console.print(f"💓 [Heartbeat] LLM 推理中... 已等待 {llm_heartbeat_count * 15}s")

                # 💡 兜底：如果循环因 task 完成而退出但还没拿到结果，再等一次
                if status is None:
                    status, response_or_error = await llm_response_queue.get()

                if status == "error":
                    raise response_or_error
                response = response_or_error

                self.console.print("✅ [Chat API] 已接收到大模型流式响应，开始处理数据流...")

                collected_content = ""
                tool_calls_dict = {}
                chunk_count = 0
                _last_usage = None  # 捕获流式最后一块携带的 usage（DeepSeek/OpenAI 语义）

                async for chunk in response:
                    chunk_count += 1
                    if not chunk.choices:
                        continue

                    # 📊 Token 计量埋点：流式 usage 通常在最后一个 chunk 上
                    _chunk_usage = getattr(chunk, "usage", None)
                    if _chunk_usage is not None:
                        _last_usage = _chunk_usage

                    delta = chunk.choices[0].delta

                    # 💡 兼容 DeepSeek 等带有 CoT (Chain of Thought) 模型的深度思考流
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        yield {"type": "reasoning_chunk", "content": reasoning_content}

                    content_val = delta.content
                    if content_val:
                        collected_content += content_val
                        # 向终端/前端抛出普通文本的流式切片
                        yield {"type": "text_chunk", "content": content_val}

                    if delta.tool_calls:
                        # 手动拼接流式的 Tool Call 碎片数据
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc_chunk.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc_chunk.function.name or "",
                                        "arguments": tc_chunk.function.arguments or "",
                                    },
                                }
                            else:
                                if tc_chunk.function.name:
                                    tool_calls_dict[idx]["function"]["name"] += tc_chunk.function.name
                                if tc_chunk.function.arguments:
                                    tool_calls_dict[idx]["function"]["arguments"] += tc_chunk.function.arguments

                msg_dict = {"role": "assistant", "content": collected_content if collected_content else None}
                if tool_calls_dict:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                        }
                        for idx, tc in sorted(tool_calls_dict.items())
                    ]

                self.console.print(f"✅ [Chat API] 本轮流式接收完毕，共解析 {chunk_count} 个 Chunk。")

                # 📊 Token 计量埋点：A-2.2 使用统一的 _record_usage 辅助函数（AGENT-04）
                await self._record_usage(_last_usage)

                if self.debug_mode:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug Stream] LLM Response Assembled ---[/dim magenta]")
                    self.console.print(f"[dim]{json.dumps(msg_dict, ensure_ascii=False, indent=2, default=str)}[/dim]")
                    self.console.print("[dim magenta]------------------------------------------------[/dim magenta]\n")

                self.messages.append({k: v for k, v in msg_dict.items() if v is not None})

                if tool_calls_dict:
                    for tc in msg_dict["tool_calls"]:
                        yield {
                            "type": "tool_start",
                            "name": tc["function"]["name"],
                            "input": tc["function"]["arguments"],
                        }

                    # A-2.3: 使用统一的 _safe_execute_tool 辅助函数（AGENT-04）
                    async def safe_execute(tc):
                        return await self._safe_execute_tool(tc["function"]["name"], tc["function"]["arguments"])

                    # 💡 心跳保活：工具执行期间定期发送 heartbeat，防止 Cloudflare 100s 空闲超时掐断连接
                    result_queue: asyncio.Queue = asyncio.Queue()

                    async def run_and_queue(tc):
                        res = await safe_execute(tc)
                        await result_queue.put((tc, res))

                    tool_tasks = [asyncio.create_task(run_and_queue(tc)) for tc in msg_dict["tool_calls"]]
                    heartbeat_count = 0
                    # 🐛 修复竞态：用「已接收结果计数」而非 task.done() 作为循环终止条件。
                    # 旧逻辑 `while tool_tasks` + `tool_tasks = [t for t in tool_tasks if not t.done()]`
                    # 存在竞态：当多个工具几乎同时完成时，处理完第一个结果后所有 task 均已 done，
                    # 导致 tool_tasks 被一次性清空、循环提前退出，剩余工具结果未写入 messages，
                    # 造成 assistant.tool_calls 与 tool 响应数量不匹配 → 下一轮 API 调用报 400。
                    expected_results = len(msg_dict["tool_calls"])
                    received_results = 0

                    while received_results < expected_results:
                        try:
                            tc, res = await asyncio.wait_for(result_queue.get(), timeout=15.0)
                        except asyncio.TimeoutError:
                            # 发送心跳保活，防止 Cloudflare/Nginx 空闲断连
                            heartbeat_count += 1
                            yield {"type": "heartbeat", "tick": heartbeat_count}
                            continue

                        received_results += 1
                        final_res = {"status": "error", "message": str(res)} if isinstance(res, Exception) else res
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tc["function"]["name"],
                                "content": json.dumps(final_res, ensure_ascii=False),
                            }
                        )
                        # 抛出执行结果给前端或 CLI 终端展示
                        yield {"type": "tool_result", "name": tc["function"]["name"], "result": final_res}

                    # 等待所有后台 task 收尾，避免悬挂任务泄漏
                    if tool_tasks:
                        await asyncio.gather(*tool_tasks, return_exceptions=True)
                    await self._save_session()
                else:
                    # 💡 流式输出时的自愈拦截
                    if collected_content:
                        # 💡 如果是系统自愈的补充回复，不需要再做文献完整性检查
                        is_correction_turn = len(self.messages) >= 2 and "系统校验拦截" in str(
                            self.messages[-2].get("content", "")
                        )
                        if not is_correction_turn:
                            # 💡 兼容大模型任意加粗格式的标题
                            parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", collected_content)
                            if len(parts) > 1:
                                main_text = parts[0]
                                ref_text = parts[-1]
                            else:
                                main_text = collected_content
                                ref_text = ""

                            citations = set(re.findall(r"\[(\d+)\]", main_text))
                            references = set(re.findall(r"\[(\d+)\]", ref_text))
                            missing = citations - references

                            if missing and i < max_iterations - 1:
                                self.console.print(
                                    f"\n[bold yellow]⚠️ [Stream Auto-Correction] 检测到遗漏参考文献 {missing}，触发流式自愈补充...[/bold yellow]"
                                )

                                # 向前端追加自愈提示的 UI 渲染
                                yield {
                                    "type": "text_chunk",
                                    "content": f"\n\n> 🔄 *系统自检：正在自动补充遗漏的参考文献 {missing}...*\n\n",
                                }

                                # 注入纠错提示，要求大模型仅输出补充内容
                                self.messages.append(
                                    {
                                        "role": "user",
                                        "content": f"⚠️ 系统校验拦截：你在刚才的回答中引用了 {', '.join([f'[{m}]' for m in missing])}，但文末缺失对应文献。为了防止前端重复渲染，请**仅补充输出**遗漏的参考文献条目（无需任何开头客套话和重复正文）。",
                                    }
                                )
                                continue  # 继续下一轮循环，直接将补充内容流式推送给前端

                    await self._save_session()

                    # 💡 策略代码块检测：扫描完整回复中的 Python 代码块，识别包含 backtest/deploy 关键字的策略代码
                    if collected_content:
                        strategy_pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
                        for match in strategy_pattern.finditer(collected_content):
                            code = match.group(1).strip()
                            if any(kw in code for kw in ["backtest", "deploy", "Backtest", "Deploy"]):
                                yield {"type": "strategy_code", "code": code}

                        # 💡 图表标注块检测 (PROD-02)：扫描完整回复中的 ```chart-annotations JSON 块，产出结构化标注事件
                        chart_ann_pattern = re.compile(r"```chart-annotations\s*\n(.*?)```", re.DOTALL)
                        for ann_match in chart_ann_pattern.finditer(collected_content):
                            raw = ann_match.group(1).strip()
                            try:
                                ann_data = json.loads(raw)
                            except Exception:
                                continue
                            if isinstance(ann_data, dict):
                                yield {"type": "chart_annotation", "data": ann_data}
                            elif isinstance(ann_data, list):
                                for item in ann_data:
                                    if isinstance(item, dict):
                                        yield {"type": "chart_annotation", "data": item}

                    return
            except Exception as e:
                import traceback

                self.console.print("\n[bold red]❌ [Agent API Error - Stream] 底层调用发生异常:[/bold red]")
                self.console.print(f"[red]{traceback.format_exc()}[/red]")

                yield {"type": "error", "content": f"\n❌ [Agent API Error]: {e}"}
                return

        # 💡 COPILOT-09: 迭代上限信号——通知前端渲染 amber 提示条
        print("⚠️ [Agent Stream] 达到最大思考循环次数，启动强制熔断恢复策略。")
        yield {"type": "iteration_limit_reached", "max_iterations": max_iterations}
        try:
            self.messages.append(
                {
                    "role": "user",
                    "content": "⚠️ 系统强制指令：你的思考与工具调用次数已达上限。请立即停止尝试使用工具，仅根据当前上下文中已获取到的数据，给出一个最终的分析总结。",
                }
            )

            final_content = ""
            # 💡 使用 pro 模型进行深度分析总结，提升最终结论质量
            # 🛡️ TokenGuard：最终流式总结前也做预算护栏
            await self._guard_before_llm(max_input_tokens=150000)
            response = await self.client.chat.completions.create(
                model=self.pro_model,
                messages=cast(Any, self.messages),
                temperature=0.0,
                stream=True,
                # 流式必须显式请求 usage，否则最后一个 chunk 不带 usage → token 漏计
                stream_options={"include_usage": True},
            )

            _f_usage = None  # 捕获流式总结最后一块的 usage
            async for chunk in response:
                if not chunk.choices:
                    continue
                _c_usage = getattr(chunk, "usage", None)
                if _c_usage is not None:
                    _f_usage = _c_usage
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield {"type": "reasoning_chunk", "content": reasoning}
                if delta.content:
                    final_content += delta.content
                    yield {"type": "text_chunk", "content": delta.content}

            # 📊 Token 计量埋点：A-2.2 pro 最终流式总结使用统一的 _record_usage（AGENT-04）
            await self._record_usage(_f_usage)

            self.messages.append({"role": "assistant", "content": final_content if final_content else None})

            # 📥 对话事实沉淀：将明确数值/事实结论写入知识库 (PR-B)
            if final_content:
                await self._sink_to_kb(final_content)

            await self._save_session()
        except Exception as e:
            print(f"❌ [Agent Stream] 强制恢复失败: {e}")
            yield {"type": "error", "content": f"\n❌ 强制恢复失败: {e}"}
