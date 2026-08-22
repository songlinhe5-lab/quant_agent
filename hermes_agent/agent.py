import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

import redis.asyncio as redis
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator
from rich.console import Console
from rich.markdown import Markdown

from backend.services.ai_narrator.repetition_guard import repetition_guard
from backend.services.ai_narrator.token_usage_store import token_usage_store
from backend.services.ai_narrator.usage_pricing import usage_pricing_calculator
from hermes_agent.llm_provider import LLMProvider, LLMProviderRouter
from hermes_agent.memory_ops import MemoryOperationsMixin
from hermes_agent.relay_tools import BatchToolCall, BatchToolExecutor
from hermes_agent.subagent import SubAgentTask, run_parallel_analysis

# 盘中主脑 prompt（与 IDE 编码宪法 AGENTS.md 分离）
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SYSTEM_PROMPT_PATH = os.path.join(_REPO_ROOT, "prompts", "system", "HERMES.md")


# ── AGENT-17: Prometheus 指标（延迟初始化）────────────────────────────
_TURN_DURATION_HISTOGRAM: Any = None


def _init_prometheus_metrics():
    """延迟初始化 Prometheus 指标（避免未安装 prometheus_client 时崩溃）"""
    global _TURN_DURATION_HISTOGRAM
    if _TURN_DURATION_HISTOGRAM is not None:
        return
    try:
        from prometheus_client import Histogram

        _TURN_DURATION_HISTOGRAM = Histogram(
            "agent_turn_duration_seconds",
            "ReAct 轮次延迟分布（按阶段分解）",
            ["phase", "model"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )
    except Exception:
        pass  # prometheus_client 未安装时静默跳过


def _observe_turn_duration(phase: str, model: str, duration_seconds: float):
    """观测轮次延迟（秒）"""
    _init_prometheus_metrics()
    if _TURN_DURATION_HISTOGRAM is not None:
        _TURN_DURATION_HISTOGRAM.labels(phase=phase, model=model).observe(duration_seconds)


# A-3.1: LLM 调用归一化结果（AGENT-04）
# AGENT-06: 扩展多 provider 归一化（failover_event）
@dataclass
class LLMResult:
    """
    LLM 调用的归一化结果。

    统一非流式/流式两条路径的返回结构，屏蔽 OpenAI SDK 的 response 对象差异。
    AGENT-06: 携带 failover_event，当主 provider 故障切换时通知上层 yield SSE 事件。
    """

    content: Optional[str]  # 文本内容
    tool_calls: Optional[List[Dict[str, Any]]]  # 工具调用列表（已归一化为 dict 格式）
    usage: Any  # token 使用量对象（可传给 _record_usage）
    reasoning_content: Optional[str] = None  # CoT 推理内容（DeepSeek 等模型的深度思考字段）
    failover_event: Optional[Any] = None  # AGENT-06: 故障切换事件（FailoverEvent or None）


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
    # AGENT-03-NEXT: 引入意图识别 + scope 过滤

    def _extract_intents(self, user_query: str) -> List[str]:
        """
        基于关键词匹配提取用户意图对应的工具场景（scope）。

        简单启发式规则（未来可升级为 LLM-based 分类器或 embedding 语义检索）：
        - quote: 最新价/价格/涨跌/行情/tick
        - fundamental: PE/PB/ROE/财报/估值/基本面
        - macro: 美债/VIX/非农/FOMC/利率决议/宏观
        - indicators: MA/均线/MACD/RSI/布林带/指标
        - news: 新闻/公告/舆情/头条
        - trade: 买入/卖出/下单/交易/订单
        - search: 搜索/研报/下载/网页/Knowledge

        Args:
            user_query: 用户原始查询文本
        Returns:
            匹配到的 scopes 列表（去重）
        """
        if not user_query:
            return []

        query = user_query.lower()
        keyword_map = {
            "quote": ["最新价", "价格", "报价", "tick", "盘口", "买卖档", "行情", "涨", "跌", "上涨", "下跌", "跌幅"],
            "fundamental": ["pe", "pb", "roe", "财报", "财务报表", "估值", "市盈率", "市净率", "基本面"],
            "macro": ["美债", "vix", "非农", "失业率", "fomc", "利率决议", "宏观", "gdp", "通胀"],
            "indicators": ["ma", "均线", "macd", "rsi", "布林带", "指标", "kdj", "adx"],
            "news": ["新闻", "公告", "舆情", "头条", "消息", "要闻"],
            "trade": ["买入", "卖出", "下单", "订单", "oms", "交易", "平仓", "建仓"],
            "search": ["搜索", "研报", "下载", "知识", "网页", "internet"],
        }

        matched_scopes = set()
        for scope, keywords in keyword_map.items():
            if any(kw in query for kw in keywords):
                matched_scopes.add(scope)

        return list(matched_scopes)

    def _build_request_kwargs(self, stream: bool = False):
        """
        构建统一的 LLM 请求参数。

        Args:
            stream: 是否开启流式输出

        Returns:
            dict: 包含 model/messages/temperature/stream/stream_options/tools 的请求参数字典
        """
        model_to_use = self.model  # 暂时禁用视觉模型，强制使用文本模型

        # AGENT-03-NEXT: 基于用户查询的最近一条消息提取意图 scopes
        last_user_message = ""
        for msg in reversed(self.messages):
            if msg.get("role") == "user" and msg.get("content"):
                last_user_message = msg.get("content", "")
                break

        matched_scopes = self._extract_intents(last_user_message)
        if matched_scopes:
            schemas = self.tool_registry.get_schemas_by_scopes(matched_scopes)
        else:
            # 无匹配 → 全量（向后兼容 + warning）
            schemas = self.tool_registry.get_all_schemas(warn=True)

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
    # AGENT-11: 扩展为成本计量 + 缓存边界管理 + reasoning_content 隔离的统一挂点
    async def _record_usage(self, usage, model: str = "unknown", session_id: str = "default"):
        """
        统一的 token 使用量记录辅助函数。

        Args:
            usage: OpenAI API 返回的 usage 对象（包含 prompt_tokens/completion_tokens/total_tokens）
            model: 模型名称（用于成本计算）
            session_id: 会话 ID（用于成本统计）
        """
        if usage is None:
            return

        prompt_tokens = getattr(usage, "prompt_tokens", 0)
        completion_tokens = getattr(usage, "completion_tokens", 0)
        total_tokens = getattr(usage, "total_tokens", 0)

        # 1. Token 使用量记录（原有逻辑）
        await token_usage_store.record(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        # 2. AGENT-11: 成本计量
        await usage_pricing_calculator.record_session_cost(
            session_id=session_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        # 3. AGENT-11: 缓存边界管理（可选，需要 system_prompt 和 tool_schemas 上下文）
        # TODO: 从 _react_loop 传入 system_prompt 和 tool_schemas，调用 split_messages()
        # 当前仅记录缓存命中统计，实际拆分逻辑需要重构 _react_loop 的 messages 构建
        # await prompt_cache_manager.record_cache_hit(session_id, is_hit=True)

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
            result = await self.tool_registry.execute(tool_name, **args)

            # AGENT-12: 记录工具调用到重复守卫（用于停滞检测）
            await repetition_guard.record_tool_call(
                tool_name=tool_name,
                arguments=args,
                result=result,
                output_summary=str(result)[:200],  # 取前 200 字符作为摘要
            )

            return result
        except Exception as e:
            # AGENT-10: 异常消息脱敏，防止凭据泄漏进模型上下文
            from hermes_agent.redact import redact_exception

            return {"status": "error", "message": f"工具执行异常: {redact_exception(e)}"}

    # AGENT-05: 脚本经 RPC 批量调工具（零上下文成本轮次）
    async def batch_execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        batch_id: str = "default",
    ) -> Dict[str, Any]:
        """
        批量执行工具调用（不经过 LLM 上下文窗口）。

        将 N 次带上下文的工具往返压成 1 轮批量执行，大幅节省 token 成本。
        安全约束：白名单仅限只读数据工具，交易类工具被硬编码拒绝。

        Args:
            tool_calls: 工具调用列表 [{"tool_name": "...", "arguments": {...}}, ...]
            batch_id: 批次标识（用于追踪和日志）

        Returns:
            批量执行报告 dict（含 summary + results）
        """
        executor = BatchToolExecutor(self.tool_registry)
        report = await executor.execute_batch(
            calls=[
                BatchToolCall(
                    tool_name=tc.get("tool_name", ""),
                    arguments=tc.get("arguments", {}),
                    call_id=tc.get("call_id"),
                )
                for tc in tool_calls
            ],
            batch_id=batch_id,
        )
        return report.to_dict()

    # AGENT-14: 子代理并行编排（多标的横截面分析加速）
    async def parallel_analyze(
        self,
        tasks: List[Dict[str, Any]],
        orchestration_id: str = "default",
    ) -> Dict[str, Any]:
        """
        并行编排子代理执行多标的横截面分析。

        每个子代理拥有隔离的上下文，继承父级的 ToolRegistry 和审批策略，
        不得提权。子代理执行完毕后汇总结果返回。

        Args:
            tasks: 子代理任务列表
                [{"task_id": "aapl", "target": "AAPL", "instruction": "分析技术面", "scopes": ["quote", "indicators"]}, ...]
            orchestration_id: 编排标识

        Returns:
            编排报告 dict（含 summary + results）
        """
        subagent_tasks = [
            SubAgentTask(
                task_id=t.get("task_id", f"task_{i}"),
                target=t.get("target", ""),
                instruction=t.get("instruction", ""),
                scopes=t.get("scopes"),
                metadata=t.get("metadata", {}),
            )
            for i, t in enumerate(tasks)
        ]

        report = await run_parallel_analysis(
            tool_registry=self.tool_registry,
            tasks=subagent_tasks,
            system_prompt=self.system_prompt,
            provider_router=self.provider_router,
            orchestration_id=orchestration_id,
        )
        return report.to_dict()

    # A-3.2: 抽 _call_llm 统一 LLM 调用逻辑（AGENT-04）
    # AGENT-06: 接入 provider_router 故障降级链
    async def _call_llm(self, request_kwargs: dict) -> LLMResult:
        """
        统一的 LLM 调用辅助函数（非流式）。

        封装 provider_router.execute_with_failover + token 计量 + 响应 debug 输出，
        返回归一化的 LLMResult。主 provider 故障时自动切到备用，并携带 failover_event。
        """
        # AGENT-06: 用 router 的活跃 provider 覆盖 model（保证与活跃 provider 一致）
        request_kwargs["model"] = self.provider_router.get_active_model()

        async def _create_func(client, model):
            """适配函数：将 router 的 (client, model) 映射到 request_kwargs 调用"""
            kwargs = dict(request_kwargs)
            kwargs["model"] = model
            return await client.chat.completions.create(**kwargs)

        response, failover_event = await self.provider_router.execute_with_failover(_create_func)
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
            failover_event=failover_event,  # AGENT-06: 故障切换事件
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
            # AGENT-12: 停滞检测 — 在每轮开始前检查是否陷入死循环
            stuck_result = await repetition_guard.check_stuck(
                current_iteration=i,
                max_iterations=max_iterations,
            )
            if stuck_result.is_stuck:
                # 检测到停滞，提前退出循环
                session_id = getattr(self, "session_id", "default")
                await repetition_guard.record_stuck_detection(
                    session_id=session_id,
                    reason=stuck_result.reason,
                    iterations_saved=stuck_result.iterations_saved,
                )
                yield {
                    "type": "error",
                    "message": f"🛑 [RepetitionGuard] 检测到停滞模式，提前终止循环。原因: {stuck_result.reason}",
                    "details": stuck_result.details,
                }
                return  # 提前退出循环

            # AGENT-17: 生成轮次唯一 ID（uuid4）
            turn_id = str(uuid.uuid4())[:8]  # 短 ID 便于日志阅读
            current_model = self.provider_router.get_active_model()

            # AGENT-01 + AGENT-17: 轮次开始事件（携带 turn_id + model + 血缘预留）
            self.event_log.record_turn_start(
                iteration=i + 1,
                turn_id=turn_id,
                model=current_model,
                # AGENT-14 血缘预留（当前为空，未来子 Agent 调用时填充）
                parent_turn_id="",
                root_turn_id="",
            )
            # 💡 心跳保活：每轮 ReAct 开始前发送心跳
            yield {"type": "heartbeat", "tick": i + 1}
            print(f"🤖 [Agent] 思考中 (第 {i + 1} 轮, turn_id={turn_id})...")

            # AGENT-17: 计时初始化
            inference_ms = 0.0
            tool_ms = 0.0
            save_ms = 0.0
            prompt_tokens = 0
            completion_tokens = 0

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

                # AGENT-06: 用 router 的活跃 provider 覆盖 model
                request_kwargs["model"] = self.provider_router.get_active_model()
                current_model = request_kwargs["model"]  # AGENT-17: 用于 Prometheus 标签

                # AGENT-17: LLM 推理计时开始
                inference_start = time.monotonic()

                async def do_llm_inference():
                    try:
                        # AGENT-06: 经 provider_router 执行，支持自动故障切换
                        async def _create_func(client, model):
                            kwargs = dict(request_kwargs)
                            kwargs["model"] = model
                            return await client.chat.completions.create(**kwargs)

                        resp, failover_evt = await self.provider_router.execute_with_failover(_create_func)
                        await llm_response_queue.put(("ok", resp, failover_evt))
                    except Exception as e:
                        await llm_response_queue.put(("error", e, None))

                inference_task = asyncio.create_task(do_llm_inference())
                llm_heartbeat_count = 0
                status, response_or_error, failover_event = None, None, None

                while not inference_task.done():
                    try:
                        status, response_or_error, failover_event = await asyncio.wait_for(
                            llm_response_queue.get(), timeout=15.0
                        )
                        break
                    except asyncio.TimeoutError:
                        llm_heartbeat_count += 1
                        yield {"type": "heartbeat", "tick": f"llm-{llm_heartbeat_count}"}
                        self.console.print(f"💓 [Heartbeat] LLM 推理中... 已等待 {llm_heartbeat_count * 15}s")

                # 兆底：如果循环因 task 完成而退出但还没拿到结果
                if status is None:
                    status, response_or_error, failover_event = await llm_response_queue.get()
                if status == "error":
                    raise response_or_error

                # AGENT-06: 如果发生了故障切换，yield SSE 降级事件通知前端
                if failover_event is not None:
                    yield failover_event.to_sse_dict()

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

                # AGENT-17: LLM 推理计时结束
                inference_ms = (time.monotonic() - inference_start) * 1000

                # 📊 Token 计量
                await self._record_usage(_last_usage)

                # AGENT-17: 提取 token 计数
                if _last_usage:
                    prompt_tokens = getattr(_last_usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(_last_usage, "completion_tokens", 0) or 0

                # 组装 message dict 并加入上下文
                msg_dict = {"role": "assistant", "content": iter_content if iter_content else None}
                if assembled_tool_calls:
                    msg_dict["tool_calls"] = assembled_tool_calls
                self.messages.append({k: v for k, v in msg_dict.items() if v is not None})

                # AGENT-01: 助手消息/工具调用意图入事件日志（append-only）
                if iter_content:
                    self.event_log.record_assistant_message(iter_content)
                if assembled_tool_calls:
                    for tc in assembled_tool_calls:
                        self.event_log.record_tool_call(tc["id"], tc["function"]["name"], tc["function"]["arguments"])

                if self.debug_mode and assembled_tool_calls:
                    self.console.print("\n[dim magenta]--- 🐛 [Debug] LLM Response Assembled ---[/dim magenta]")
                    self.console.print(f"[dim]{json.dumps(msg_dict, ensure_ascii=False, indent=2, default=str)}[/dim]")
                    self.console.print("[dim magenta]------------------------------------------------[/dim magenta]\n")

                # ── 4. 工具执行（含心跳保活）──────────────────────────────
                if assembled_tool_calls:
                    # AGENT-17: 工具执行计时开始
                    tool_start = time.monotonic()

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
                            # AGENT-01 + AGENT-17: 工具返回入事件日志（携带 turn_id 便于归组）
                            _ev_content = json.dumps(final_res, ensure_ascii=False)
                            if len(_ev_content) > 4096:
                                _ev_content = _ev_content[:4096] + "...[truncated]"
                            self.event_log.record_tool_result(
                                tc["id"], tc["function"]["name"], _ev_content, turn_id=turn_id
                            )
                            yield {"type": "tool_result", "name": tc["function"]["name"], "result": final_res}

                    if tool_tasks:
                        await asyncio.gather(*tool_tasks, return_exceptions=True)

                    # AGENT-17: 工具执行计时结束
                    tool_ms = (time.monotonic() - tool_start) * 1000

                    # AGENT-17: 会话保存计时
                    save_start = time.monotonic()
                    await self._save_session()
                    save_ms = (time.monotonic() - save_start) * 1000

                else:
                    # ── 5. 无工具调用 → 参考文献自愈 + 输出 ──────────────
                    if not iter_content:
                        # AGENT-01 + AGENT-17: 轮次结束事件（携带计时）
                        self.event_log.record_turn_end(
                            i + 1,
                            content_len=len(collected_content),
                            turn_id=turn_id,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            inference_ms=inference_ms,
                            tool_ms=tool_ms,
                            save_ms=save_ms,
                        )

                        # AGENT-17: 观测 Prometheus 指标（early exit，仅保存时间）
                        _observe_turn_duration("early_exit", current_model, save_ms / 1000)

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
                            # AGENT-01: 系统注入的自愈指令同样入事件日志（模型可见即已记录）
                            self.event_log.record_user_message(self.messages[-1]["content"])
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

                    # AGENT-01 + AGENT-17: 正常结束的轮次记录 turn_end（携带完整计时）
                    self.event_log.record_turn_end(
                        i + 1,
                        content_len=len(collected_content),
                        turn_id=turn_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        inference_ms=inference_ms,
                        tool_ms=tool_ms,
                        save_ms=save_ms,
                    )

                    # AGENT-17: 观测 Prometheus 指标（仅 phase=start+inference，不含 tool/save 因分属独立路径）
                    _observe_turn_duration("start_inference", current_model, (inference_ms + save_ms) / 1000)

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
            # AGENT-01: 熔断恢复的系统注入指令入事件日志
            self.event_log.record_user_message(self.messages[-1]["content"])

            await self._guard_before_llm(max_input_tokens=150000)
            cb_kwargs = self._build_request_kwargs_model(self.pro_model, stream=True)
            response = await self.client.chat.completions.create(**cb_kwargs)

            _f_usage = None
            final_content = ""

            # AGENT-17: 熔断恢复路径计时开始（inference）
            recovery_inference_start = time.monotonic()

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

            # AGENT-17: 熔断恢复推理计时结束
            recovery_inference_ms = (time.monotonic() - recovery_inference_start) * 1000
            self.messages.append({"role": "assistant", "content": final_content if final_content else None})
            # AGENT-01 + AGENT-17: 熔断恢复的最终回复入事件日志（携带计时）
            if final_content:
                self.event_log.record_assistant_message(final_content)
            # AGENT-17: 熔断恢复轮次结束事件（仅 inference，无 tool/save）
            self.event_log.record_turn_end(
                max_iterations,
                content_len=len(final_content or ""),
                turn_id=turn_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                inference_ms=recovery_inference_ms,
                tool_ms=0.0,
                save_ms=0.0,
            )

            # 📥 对话事实沉淀
            if final_content:
                await self._sink_to_kb(final_content)

            # AGENT-17: 保存会话也计入时间
            save_start = time.monotonic()
            await self._save_session()
            save_ms = (time.monotonic() - save_start) * 1000

            # AGENT-17: 观测 Prometheus 指标
            _observe_turn_duration("recovery_fallback", current_model, (recovery_inference_ms + save_ms) / 1000)
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

        # 💡 初始化 LLM 客户端 + AGENT-06 Provider 适配缝
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

        # AGENT-06: LLM Provider 适配缝（故障降级链）
        # 主 provider 复用上面的 self.client + self.model
        primary_provider = LLMProvider(
            name=f"primary-{self.model}",
            client=self.client,
            model=self.model,
            priority=0,
        )
        self.provider_router = LLMProviderRouter(primary_provider)
        # 如果环境变量配置了 fallback，自动添加
        fallback_api_key = os.getenv("LLM_FALLBACK_API_KEY")
        if fallback_api_key:
            fallback_base_url = os.getenv("LLM_FALLBACK_BASE_URL", "https://api.openai.com/v1")
            fallback_model = os.getenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")
            fallback_client = AsyncOpenAI(api_key=fallback_api_key, base_url=fallback_base_url)
            self.provider_router.add_fallback(
                LLMProvider(
                    name=f"fallback-{fallback_model}",
                    client=fallback_client,
                    model=fallback_model,
                    priority=1,
                )
            )

        # 1. 加载盘中主脑指令 (prompts/system/HERMES.md)
        self.system_prompt = self._load_system_prompt()

        # 2. 初始化对话记忆 (Context Window)
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

        # AGENT-01: append-only 会话事件日志（压缩/自愈不改写日志，只影响投影）
        from hermes_agent.event_log import SessionEventLog

        self.event_log = SessionEventLog(session_id=self.session_id)

        print(f"🧠 [Agent Brain] 初始化完成。主推理: {self.model} | 深度分析: {self.pro_model}")

    async def initialize(self):
        """
        异步初始化：从三轨存储加载历史记忆 + 写入 SessionMeta。
        AGENT-15: 新增 SessionMeta 写入（Rollout 首行）
        """
        await self._load_session()

        # AGENT-15: 写入 SessionMeta（仅新会话时写入，幂等）
        if self.session_id and self.session_id != "default":
            try:
                from datetime import datetime, timezone

                from hermes_agent.rollout_storage import RolloutStorage, SessionMeta

                storage = RolloutStorage()
                meta = SessionMeta(
                    session_id=self.session_id,
                    model=self.model,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    event_count=len(self.event_log) if hasattr(self, "event_log") else 0,
                )
                storage.save_session_meta(self.session_id, meta)
            except Exception as e:
                print(f"⚠️ [Agent] SessionMeta 写入失败: {e}")

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
                    self.event_log.reset()  # AGENT-01: 用户显式清空 → 事件日志同步重置
                    await self._save_session()
                    self.console.print("\n[bold yellow]🧹 [Memory] 历史记忆已彻底清空，大脑已重置！[/bold yellow]")
                    continue

                if not user_input:
                    continue

                await self._heal_memory()
                self.messages.append({"role": "user", "content": user_input})
                self.event_log.record_user_message(user_input)  # AGENT-01
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
            self.event_log.reset()  # AGENT-01
            await self._save_session()
            return "🧹 历史记忆已彻底清空，大脑已重置！"

        await self._heal_memory()

        if user_input.strip():
            self.messages.append({"role": "user", "content": user_input.strip()})
            self.event_log.record_user_message(user_input.strip())  # AGENT-01
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
            self.event_log.reset()  # AGENT-01
            await self._save_session()
            yield {"type": "text_chunk", "content": "🧹 历史记忆已彻底清空，大脑已重置！"}
            return

        await self._heal_memory()

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
            # AGENT-01: 记录注入宏观上下文后的完整用户消息（模型实际看到的内容）
            self.event_log.record_user_message(enriched_user_input)

        await self._save_session()

        if len(self.messages) <= 1:
            self.console.print("⚠️ [Agent Stream] 上下文为空 (或仅含 System 指令)，拒绝发起大模型请求。")
            return

        # A-4: 转发统一 _react_loop 的 SSE 事件（过滤内部 _done 控制事件）
        async for event in self._react_loop():
            if event.get("type") != "_done":
                yield event
