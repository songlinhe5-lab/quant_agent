import asyncio
import json
import os
import re
from dataclasses import dataclass
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


# A-3.1: LLM 调用归一化结果（AGENT-04）
@dataclass
class LLMResult:
    """
    LLM 调用的归一化结果。

    统一非流式/流式两条路径的返回结构，屏蔽 OpenAI SDK 的 response 对象差异。
    后续 AGENT-06 (LLM Provider 适配缝) 可在此基础上扩展多 provider 归一化。
    """

    content: Optional[str]  # 文本内容
    tool_calls: Optional[List[Dict[str, Any]]]  # 工具调用列表（已归一化为 dict 格式）
    usage: Any  # token 使用量对象（可传给 _record_usage）
    reasoning_content: Optional[str] = None  # CoT 推理内容（DeepSeek 等模型的深度思考字段）


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
            # AGENT-10: 异常消息脱敏，防止凭据泄漏进模型上下文
            from hermes_agent.redact import redact_exception

            return {"status": "error", "message": f"工具执行异常: {redact_exception(e)}"}

    # A-3.2: 抽 _call_llm 统一 LLM 调用逻辑（AGENT-04）
    async def _call_llm(self, request_kwargs: dict) -> LLMResult:
        """
        统一的 LLM 调用辅助函数（非流式）。

        封装 client.chat.completions.create + token 计量 + 响应 debug 输出，
        返回归一化的 LLMResult。
        """
        response = await self.client.chat.completions.create(**request_kwargs)
        msg = response.choices[0].message

        # 📊 Token 计量埋点：A-3.2 统一在 _call_llm 内记录（AGENT-04）
        await self._record_usage(getattr(response, "usage", None))

        if self.debug_mode:
            self.console.print("\n[dim magenta]--- 🐛 [Debug] LLM Response ---[/dim magenta]")
            self.console.print(
                f"[dim]{json.dumps(msg.model_dump(exclude_none=True), ensure_ascii=False, indent=2, default=str)}[/dim]"
            )
            self.console.print("[dim magenta]-------------------------------[/dim magenta]\n")

        # 归一化 tool_calls 为 dict 格式，与流式路径的 tool_calls_dict 结构对齐
        tool_calls_list = None
        if msg.tool_calls:
            tool_calls_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]

        return LLMResult(
            content=msg.content,
            tool_calls=tool_calls_list,
            usage=getattr(response, "usage", None),
            reasoning_content=getattr(msg, "reasoning_content", None),
        )

    # A-3.2: 支持熔断恢复路径的模型覆盖（AGENT-04）
    def _build_request_kwargs_model(self, model_override: str, stream: bool = False) -> dict:
        """构建 LLM 请求参数，但使用指定的模型覆盖（熔断恢复路径用 pro 模型）。"""
        kwargs = self._build_request_kwargs(stream=stream)
        kwargs["model"] = model_override
        return kwargs

    # ========================================================================
    # A-4: 统一 ReAct 驱动循环 (AGENT-04)
    # ========================================================================

    async def _react_loop(self):
        """
        A-4: 统一 ReAct 驱动循环 — 唯一循环语义实现（AGENT-04）。

        异步生成器：yield 事件给流式消费者（chat_stream_async），
        非流式消费者（chat/run_cli）忽略中间事件，仅收集最终内容。

        统一事件类型（SSE 契约冻结）：
          heartbeat / reasoning_chunk / text_chunk / tool_start / tool_result /
          strategy_code / chart_annotation / iteration_limit_reached / error

        统一逻辑（不再分叉）：
          - 参考文献自愈（原 @with_reference_check + 流式 inline check → 唯一实现）
          - 熔断恢复（原两处 → 唯一实现）
          - 策略代码 / 图表标注检测（流式差异化事件，非流式消费者忽略）
        """
        max_iterations = self._MAX_REACT_ITERATIONS
        collected_content = ""

        for i in range(max_iterations):
            # 💡 心跳保活：每轮 ReAct 开始前发送心跳
            yield {"type": "heartbeat", "tick": i + 1}
            print(f"🤖 [Agent] 思考中 (第 {i + 1} 轮)...")

            try:
                # ── 1. 构建请求 & 调试输出 ──────────────────────────────
                request_kwargs = self._build_request_kwargs(stream=True)

                if self.debug_mode:
                    self.console.print("\n[dim cyan]--- 🐛 [Debug] LLM Request ---[/dim cyan]")
                    self.console.print(
                        f"[dim]Messages: {json.dumps(request_kwargs['messages'], ensure_ascii=False, indent=2, default=str)}[/dim]"
                    )
                    if "tools" in request_kwargs:
                        self.console.print(f"[dim]Tools Configured: {len(request_kwargs['tools'])}[/dim]")
                    self.console.print("[dim cyan]------------------------------[/dim cyan]\n")

                # 🛡️ TokenGuard：每次 ReAct 迭代发 LLM 前做限流 + 预算护栏
                await self._guard_before_llm()

                # ── 2. LLM 推理（心跳保活 + 流式 chunk 拼接）─────────────
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
                        break
                    except asyncio.TimeoutError:
                        llm_heartbeat_count += 1
                        yield {"type": "heartbeat", "tick": f"llm-{llm_heartbeat_count}"}
                        self.console.print(f"💓 [Heartbeat] LLM 推理中... 已等待 {llm_heartbeat_count * 15}s")

                # 兜底：如果循环因 task 完成而退出但还没拿到结果
                if status is None:
                    status, response_or_error = await llm_response_queue.get()
                if status == "error":
                    raise response_or_error

                response = response_or_error
                self.console.print("✅ [Chat API] 已接收到大模型流式响应，开始处理数据流...")

                # ── 3. 流式 chunk 拼接 ──────────────────────────────────
                iter_content = ""
                tool_calls_dict = {}
                chunk_count = 0
                _last_usage = None

                async for chunk in response:
                    chunk_count += 1
                    if not chunk.choices:
                        continue

                    _chunk_usage = getattr(chunk, "usage", None)
                    if _chunk_usage is not None:
                        _last_usage = _chunk_usage

                    delta = chunk.choices[0].delta

                    # CoT 推理流
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        yield {"type": "reasoning_chunk", "content": reasoning_content}

                    content_val = delta.content
                    if content_val:
                        iter_content += content_val
                        collected_content += content_val
                        yield {"type": "text_chunk", "content": content_val}

                    if delta.tool_calls:
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

                # 组装 tool_calls 列表
                assembled_tool_calls = None
                if tool_calls_dict:
                    assembled_tool_calls = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                        }
                        for idx, tc in sorted(tool_calls_dict.items())
                    ]

                self.console.print(f"✅ [Chat API] 本轮流式接收完毕，共解析 {chunk_count} 个 Chunk。")

                # 📊 Token 计量
                await self._record_usage(_last_usage)

                # 组装 message dict 并加入上下文
                msg_dict = {"role": "assistant", "content": iter_content if iter_content else None}
                if assembled_tool_calls:
                    msg_dict["tool_calls"] = assembled_tool_calls
                self.messages.append({k: v for k, v in msg_dict.items() if v is not None})

                if self.debug_mode and assembled_tool_calls:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug] LLM Response Assembled ---[/dim magenta]")
                    self.console.print(f"[dim]{json.dumps(msg_dict, ensure_ascii=False, indent=2, default=str)}[/dim]")
                    self.console.print("[dim magenta]------------------------------------------------[/dim magenta]\n")

                # ── 4. 工具执行（含心跳保活）──────────────────────────────
                if assembled_tool_calls:
                    for tc in msg_dict["tool_calls"]:
                        yield {
                            "type": "tool_start",
                            "name": tc["function"]["name"],
                            "input": tc["function"]["arguments"],
                        }

                    result_queue: asyncio.Queue = asyncio.Queue()

                    async def run_and_queue(tc):
                        res = await self._safe_execute_tool(tc["function"]["name"], tc["function"]["arguments"])
                        await result_queue.put((tc, res))

                    tool_tasks = [asyncio.create_task(run_and_queue(tc)) for tc in msg_dict["tool_calls"]]
                    heartbeat_count = 0
                    expected_results = len(msg_dict["tool_calls"])
                    received_results = 0

                    while received_results < expected_results:
                        try:
                            tc, res = await asyncio.wait_for(result_queue.get(), timeout=15.0)
                        except asyncio.TimeoutError:
                            heartbeat_count += 1
                            yield {"type": "heartbeat", "tick": heartbeat_count}
                            continue

                        received_results += 1
                        final_res = {"status": "error", "message": str(res)} if isinstance(res, Exception) else res

                        # AGENT-02: 熔断检测 — 同一 Tool 连续失败 3 次后返回 circuit_breaker
                        if final_res.get("status") == "circuit_breaker":
                            yield {
                                "type": "circuit_breaker",
                                "name": tc["function"]["name"],
                                "report": {
                                    "tool": final_res.get("tool", tc["function"]["name"]),
                                    "reason": final_res.get("reason", ""),
                                    "suggestion": final_res.get("suggestion", ""),
                                },
                                "message": final_res.get("message", ""),
                            }
                        else:
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "name": tc["function"]["name"],
                                    "content": json.dumps(final_res, ensure_ascii=False),
                                }
                            )
                            yield {"type": "tool_result", "name": tc["function"]["name"], "result": final_res}

                    if tool_tasks:
                        await asyncio.gather(*tool_tasks, return_exceptions=True)
                    await self._save_session()

                else:
                    # ── 5. 无工具调用 → 参考文献自愈 + 输出 ──────────────
                    if not iter_content:
                        yield {"type": "_done", "content": collected_content}
                        return

                    # A-4: 参考文献自愈（统一实现，替代 @with_reference_check + 流式 inline check）
                    is_correction_turn = len(self.messages) >= 2 and "系统校验拦截" in str(
                        self.messages[-2].get("content", "")
                    )
                    if not is_correction_turn:
                        parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", iter_content)
                        if len(parts) > 1:
                            main_text = parts[0]
                            ref_text = parts[-1]
                        else:
                            main_text = iter_content
                            ref_text = ""

                        citations = set(re.findall(r"\[(\d+)\]", main_text))
                        references = set(re.findall(r"\[(\d+)\]", ref_text))
                        missing = citations - references

                        if missing and i < max_iterations - 1:
                            self.console.print(
                                f"\n[bold yellow]⚠️ [Auto-Correction] 检测到遗漏参考文献 {missing}，触发自愈...[/bold yellow]"
                            )
                            yield {
                                "type": "text_chunk",
                                "content": f"\n\n> 🔄 *系统自检：正在自动补充遗漏的参考文献 {missing}...*\n\n",
                            }
                            self.messages.append(
                                {
                                    "role": "user",
                                    "content": f"⚠️ 系统校验拦截：你在刚才的回答中引用了 {', '.join([f'[{m}]' for m in missing])}，但文末缺失对应文献。请**仅补充输出**遗漏的参考文献条目（无需任何开头客套话和重复正文）。",
                                }
                            )
                            continue  # 继续下一轮循环

                    await self._save_session()

                    # ── 6. 策略代码 / 图表标注检测（流式差异化事件）──────
                    if collected_content:
                        strategy_pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
                        for match in strategy_pattern.finditer(collected_content):
                            code = match.group(1).strip()
                            if any(kw in code for kw in ["backtest", "deploy", "Backtest", "Deploy"]):
                                yield {"type": "strategy_code", "code": code}

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

                    yield {"type": "_done", "content": collected_content}
                    return

            except Exception as e:
                import traceback

                from hermes_agent.redact import redact_exception

                self.console.print("\n[bold red]❌ [Agent API Error] 底层调用发生异常:[/bold red]")
                self.console.print(f"[red]{traceback.format_exc()}[/red]")
                # AGENT-10: SSE error 事件内容脱敏
                yield {"type": "error", "content": f"\n❌ [Agent API Error]: {redact_exception(e)}"}
                yield {"type": "_done", "content": collected_content}
                return

        # ── 7. 熔断恢复（唯一实现，替代原两处分叉）──────────────────────
        print("⚠️ [Agent] 达到最大思考循环次数，启动强制熔断恢复策略。")
        yield {"type": "iteration_limit_reached", "max_iterations": max_iterations}

        try:
            self.messages.append(
                {
                    "role": "user",
                    "content": "⚠️ 系统强制指令：你的思考与工具调用次数已达上限。请立即停止尝试使用工具，仅根据当前上下文中已获取到的数据，给出一个最终的分析总结。",
                }
            )

            await self._guard_before_llm(max_input_tokens=150000)
            cb_kwargs = self._build_request_kwargs_model(self.pro_model, stream=True)
            response = await self.client.chat.completions.create(**cb_kwargs)

            _f_usage = None
            final_content = ""
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

            await self._record_usage(_f_usage)
            self.messages.append({"role": "assistant", "content": final_content if final_content else None})

            # 📥 对话事实沉淀
            if final_content:
                await self._sink_to_kb(final_content)

            await self._save_session()
            yield {"type": "_done", "content": final_content}
            return

        except Exception as e:
            from hermes_agent.redact import redact_exception

            # AGENT-10: 强制恢复失败的日志与 SSE 事件脱敏
            print(f"❌ [Agent] 强制恢复失败: {redact_exception(e)}")
            yield {"type": "error", "content": f"\n❌ 强制恢复失败: {redact_exception(e)}"}
            yield {"type": "_done", "content": ""}
            return

    # ========================================================================
    # 非流式 / 流式 wrapper（A-4: 均委托给 _react_loop）
    # ========================================================================

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
        """读取盘中主脑指令（HERMES.md）。代码生成/图表风控已写入此文件 §9，不再在此拼接。"""
        if os.path.exists(self.system_prompt_path):
            with open(self.system_prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        print(f"⚠️ 警告: 未找到系统指令文件 {self.system_prompt_path}")
        return "你是一个专业的量化交易 Agent。"

    async def run_cli(self):
        """启动交互终端"""
        self.console.print("\n[bold green]🟢 [Terminal] 量化网关 CLI 启动。输入 'exit' 退出。[/bold green]")
        while True:
            try:
                user_input = self.console.input("\n[bold cyan][Trader] 👤:[/bold cyan] ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    break

                if user_input.lower() == "/clear":
                    self.messages = [{"role": "system", "content": self.system_prompt}]
                    await self._save_session()
                    self.console.print("\n[bold yellow]🧹 [Memory] 历史记忆已彻底清空，大脑已重置！[/bold yellow]")
                    continue

                if not user_input:
                    continue

                self._heal_memory()
                self.messages.append({"role": "user", "content": user_input})
                await self._save_session()

                # A-4: CLI 也使用统一 _react_loop，带 Rich Markdown 格式化输出
                async for event in self._react_loop():
                    pass  # CLI 不消费 SSE 事件
                # 从 messages 中提取最后的 assistant 内容进行格式化输出
                for msg in reversed(self.messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        self.console.print("\n[bold green]💬 [Agent Output]:[/bold green]")
                        self.console.print(Markdown(msg["content"]))
                        break

            except KeyboardInterrupt:
                print("\n\n[System] 收到强制中断信号，正在安全关闭...")
                break
            except Exception as e:
                print(f"\n❌ [System Fatal] 核心循环异常: {e}")

    async def chat(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        异步单轮对话接口，专门提供给 FastAPI / WebSocket 等外部程序调用。
        A-4: 委托给统一 _react_loop，收集文本内容返回。
        """
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            return "🧹 历史记忆已彻底清空，大脑已重置！"

        self._heal_memory()

        if user_input.strip():
            self.messages.append({"role": "user", "content": user_input.strip()})
        await self._save_session()

        if len(self.messages) <= 1:
            return ""

        try:
            # A-4: 消费统一 _react_loop，收集文本内容
            collected = ""
            final_content = ""
            async for event in self._react_loop():
                if event["type"] == "text_chunk":
                    collected += event["content"]
                elif event["type"] == "_done":
                    final_content = event.get("content", "")

            # 优先使用 _done 事件携带的最终内容（排除自愈轮次的多余文本）
            result = final_content or collected
            final = result if result else "⚠️ 思考完成，但未返回任何内容。"
            if final and not final.startswith("⚠️") and not final.startswith("❌"):
                await self._sink_to_kb(final)
            return final
        except Exception as e:
            return f"❌ [Agent Runtime Error] 运行异常: {e}"

    async def chat_stream_async(self, user_input: str = "", attachments: Optional[List[Dict[str, Any]]] = None):
        """
        异步流式对话接口 (供 FastAPI 与支持异步的 CLI 终端调用)
        A-4: 委托给统一 _react_loop，直接转发所有 SSE 事件。
        """
        if user_input.strip().lower() == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            await self._save_session()
            yield {"type": "text_chunk", "content": "🧹 历史记忆已彻底清空，大脑已重置！"}
            return

        self._heal_memory()

        # MRKT-05: 个股分析时自动注入宏观判因上下文
        # 💡 [Prefix-Cache 优化] market_ctx 折叠进 user message 末尾
        enriched_user_input = user_input.strip() if user_input.strip() else ""
        if user_input.strip():
            try:
                from backend.services.market_review.context_injector import try_inject_market_context

                market_ctx = await try_inject_market_context(user_input.strip())
                if market_ctx:
                    enriched_user_input = f"{user_input.strip()}\n\n{market_ctx}"
            except Exception:
                pass

        if enriched_user_input:
            self.messages.append({"role": "user", "content": enriched_user_input})

        await self._save_session()

        if len(self.messages) <= 1:
            self.console.print("⚠️ [Agent Stream] 上下文为空 (或仅含 System 指令)，拒绝发起大模型请求。")
            return

        # A-4: 转发统一 _react_loop 的 SSE 事件（过滤内部 _done 控制事件）
        async for event in self._react_loop():
            if event.get("type") != "_done":
                yield event
