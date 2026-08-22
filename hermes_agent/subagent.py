"""
==========================================================
AGENT-14 · 子代理并行编排（多标的横截面分析加速）
==========================================================

对标 hermes `subagent_lifecycle.py` + dsh `subsystems/subagent.md`。
隔离上下文的子代理并行跑各标的，主代理只收汇总。

核心思想：
  多标的横截面分析（如"分析 AAPL、MSFT、GOOGL"）目前串行执行，
  叠加 S11 的 1 req/s 限流更慢。通过子代理并行编排，
  每个子代理负责一个标的的独立分析，主代理只负责汇总。

安全约束（不可妥协）：
  1. 子代理继承父级的 ToolRegistry — 同一工具白名单/黑名单
  2. 子代理继承父级的审批策略 — 不得提权
  3. 子代理继承父级的 scope 过滤 — 同一场景过滤规则
  4. 子代理的上下文完全隔离 — 不污染父级对话历史
  5. 子代理的 ReAct 循环迭代次数受限（MAX_SUBAGENT_ITERATIONS=4）

与现有架构的协同：
  - AGENT-02: 子代理工具执行经同一 ToolRegistry.execute()（含中间件管线）
  - AGENT-03: 子代理继承同一 ToolScope 过滤
  - AGENT-05: 子代理可复用批量执行能力
  - AGENT-07: 子代理继承同一审批策略（check_trade_approval）
  - AGENT-10: 子代理结果脱敏后才返回父级
  - AGENT-12: 子代理受重复/停滞守卫保护

使用示例：
  orchestrator = SubAgentOrchestrator(tool_registry=registry)
  tasks = [
      SubAgentTask(task_id="aapl", target="AAPL", instruction="分析 AAPL 技术面"),
      SubAgentTask(task_id="msft", target="MSFT", instruction="分析 MSFT 技术面"),
  ]
  report = await orchestrator.run_parallel(tasks)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hermes_agent.scopes import ToolScope

logger = logging.getLogger(__name__)

# ========================================================================
# 配置常量
# ========================================================================

# 子代理 ReAct 最大迭代次数（比父级的 8 次更保守）
MAX_SUBAGENT_ITERATIONS: int = 4

# 最大并发子代理数（防止资源耗尽）
MAX_CONCURRENT_SUBAGENTS: int = 5

# 单个子代理超时（秒）
SUBAGENT_TIMEOUT: float = 60.0

# 整体编排超时（秒）
ORCHESTRATION_TIMEOUT: float = 120.0

# 子代理工具执行心跳间隔（秒）
SUBAGENT_HEARTBEAT_INTERVAL: float = 10.0


# ========================================================================
# 数据结构
# ========================================================================


@dataclass
class SubAgentTask:
    """子代理任务定义"""

    task_id: str  # 唯一任务标识
    target: str  # 分析标的（如 "AAPL"）
    instruction: str  # 具体指令（如"分析技术面"）
    scopes: Optional[List[str]] = None  # 限定 scope（None=继承父级）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 扩展元数据


@dataclass
class SubAgentResult:
    """子代理执行结果"""

    task_id: str
    target: str
    status: str  # success / error / timeout / cancelled
    content: str = ""  # 子代理最终输出文本
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # 工具调用记录
    iterations: int = 0  # 实际迭代次数
    execution_time: float = 0.0  # 执行耗时（秒）
    error_message: str = ""  # 错误消息（如有）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "target": self.target,
            "status": self.status,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "iterations": self.iterations,
            "execution_time": round(self.execution_time, 3),
            "error_message": self.error_message,
        }


@dataclass
class SubAgentOrchestratorReport:
    """编排器汇总报告"""

    orchestration_id: str
    total_tasks: int
    completed: int
    failed: int
    timed_out: int
    results: List[SubAgentResult] = field(default_factory=list)
    total_execution_time: float = 0.0  # 总耗时（并行取最慢）
    parallelism_speedup: float = 1.0  # 并行加速比

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "summary": {
                "total_tasks": self.total_tasks,
                "completed": self.completed,
                "failed": self.failed,
                "timed_out": self.timed_out,
            },
            "total_execution_time": round(self.total_execution_time, 3),
            "parallelism_speedup": round(self.parallelism_speedup, 2),
            "results": [r.to_dict() for r in self.results],
        }


# ========================================================================
# SubAgent — 隔离上下文的轻量级代理
# ========================================================================


class SubAgent:
    """
    子代理：隔离上下文的轻量级代理实例。

    安全约束：
    1. 共享父级 ToolRegistry（同一安全约束）
    2. 独立的消息上下文（不污染父级）
    3. 受限的 ReAct 迭代次数（MAX_SUBAGENT_ITERATIONS=4）
    4. 继承父级审批策略（不得提权）
    """

    def __init__(
        self,
        tool_registry,
        system_prompt: str,
        task: SubAgentTask,
        provider_router=None,
    ):
        """
        初始化子代理。

        Args:
            tool_registry: 父级 ToolRegistry（共享，不拷贝）
            system_prompt: 父级系统指令（继承）
            task: 子代理任务定义
            provider_router: 父级 LLM provider router（共享）
        """
        self._registry = tool_registry
        self._task = task
        self._provider_router = provider_router

        # 隔离的消息上下文（不污染父级）
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"你是主脑 Agent 派出的子代理，专门负责分析标的 **{task.target}**。\n\n"
                    f"任务指令：{task.instruction}\n\n"
                    f"请调用相关工具获取数据，然后给出简洁的分析结论。"
                    f"不要输出冗余的寒暄，直接给出数据和分析。"
                ),
            },
        ]

        # 工具调用记录（审计用）
        self._tool_call_log: List[Dict[str, Any]] = []

    async def run(self) -> SubAgentResult:
        """
        执行子代理 ReAct 循环（简化版，最多 MAX_SUBAGENT_ITERATIONS 轮）。

        Returns:
            SubAgentResult: 执行结果
        """
        t_start = time.monotonic()
        collected_content = ""
        iterations = 0

        try:
            for i in range(MAX_SUBAGENT_ITERATIONS):
                iterations = i + 1

                # ── 1. LLM 推理 ──────────────────────────────────────
                request_kwargs = self._build_request_kwargs()

                if self._provider_router is not None:
                    request_kwargs["model"] = self._provider_router.get_active_model()

                    async def _create_func(client, model):
                        kwargs = dict(request_kwargs)
                        kwargs["model"] = model
                        return await client.chat.completions.create(**kwargs)

                    response, _ = await self._provider_router.execute_with_failover(_create_func)
                else:
                    # 无 provider_router 时直接调用（测试场景）
                    break

                msg = response.choices[0].message

                # 收集文本内容
                if msg.content:
                    collected_content += msg.content

                # ── 2. 工具执行 ──────────────────────────────────────
                if msg.tool_calls:
                    # 组装 tool_calls
                    assembled = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ]

                    # 加入 assistant 消息
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": assembled,
                        }
                    )

                    # 并行执行工具调用
                    tool_results = await asyncio.gather(
                        *[self._execute_tool(tc) for tc in assembled],
                        return_exceptions=True,
                    )

                    # 加入工具结果消息
                    for tc, result in zip(assembled, tool_results):
                        if isinstance(result, Exception):
                            result_dict = {"status": "error", "message": str(result)}
                        else:
                            result_dict = result

                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tc["function"]["name"],
                                "content": json.dumps(result_dict, ensure_ascii=False, default=str),
                            }
                        )

                        # 记录工具调用
                        self._tool_call_log.append(
                            {
                                "tool": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                                "status": result_dict.get("status", "unknown"),
                            }
                        )
                else:
                    # 无工具调用 → 子代理完成
                    break

            elapsed = time.monotonic() - t_start
            return SubAgentResult(
                task_id=self._task.task_id,
                target=self._task.target,
                status="success",
                content=collected_content.strip(),
                tool_calls=self._tool_call_log,
                iterations=iterations,
                execution_time=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t_start
            return SubAgentResult(
                task_id=self._task.task_id,
                target=self._task.target,
                status="timeout",
                content=collected_content.strip(),
                tool_calls=self._tool_call_log,
                iterations=iterations,
                execution_time=elapsed,
                error_message=f"子代理执行超时 ({SUBAGENT_TIMEOUT}s)",
            )

        except Exception as e:
            elapsed = time.monotonic() - t_start
            return SubAgentResult(
                task_id=self._task.task_id,
                target=self._task.target,
                status="error",
                content=collected_content.strip(),
                tool_calls=self._tool_call_log,
                iterations=iterations,
                execution_time=elapsed,
                error_message=str(e),
            )

    def _build_request_kwargs(self) -> dict:
        """构建子代理的 LLM 请求参数"""
        kwargs = {
            "messages": self.messages,
            "temperature": 0.0,
            "stream": False,
        }

        # scope 过滤（继承父级或任务指定）
        if self._task.scopes:
            schemas = self._registry.get_schemas_by_scopes(self._task.scopes)
        else:
            # 子代理默认只使用只读数据 scope（安全约束：不得访问交易类工具）
            safe_scopes = [
                ToolScope.QUOTE.value,
                ToolScope.INDICATORS.value,
                ToolScope.FUND_FLOW.value,
                ToolScope.FUNDAMENTAL.value,
                ToolScope.MACRO.value,
                ToolScope.NEWS.value,
            ]
            schemas = self._registry.get_schemas_by_scopes(safe_scopes)

        if schemas:
            kwargs["tools"] = schemas

        return kwargs

    async def _execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个工具调用（经 ToolRegistry 中间件管线）"""
        tool_name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError:
            return {"status": "error", "message": f"工具参数 JSON 解析失败: {tool_call['function']['arguments'][:200]}"}

        # 经 ToolRegistry.execute()（含 AGENT-02 中间件管线）
        result = await self._registry.execute(tool_name, **args)
        return result


# ========================================================================
# SubAgentOrchestrator — 并行编排器
# ========================================================================


class SubAgentOrchestrator:
    """
    子代理并行编排器。

    负责：
    1. 接收任务列表
    2. 并行启动子代理（并发控制 Semaphore）
    3. 超时保护（per-task + overall）
    4. 汇总结果并计算加速比
    """

    def __init__(
        self,
        tool_registry,
        system_prompt: str = "",
        provider_router=None,
    ):
        self._registry = tool_registry
        self._system_prompt = system_prompt
        self._provider_router = provider_router
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)

    async def run_parallel(
        self,
        tasks: List[SubAgentTask],
        orchestration_id: str = "default",
    ) -> SubAgentOrchestratorReport:
        """
        并行执行多个子代理任务。

        Args:
            tasks: 子代理任务列表
            orchestration_id: 编排标识（用于追踪）

        Returns:
            SubAgentOrchestratorReport: 汇总报告
        """
        if not tasks:
            return SubAgentOrchestratorReport(
                orchestration_id=orchestration_id,
                total_tasks=0,
                completed=0,
                failed=0,
                timed_out=0,
            )

        t_start = time.monotonic()
        logger.info(
            f"🚀 [SubAgent Orchestrator] 启动并行编排 {orchestration_id}，"
            f"共 {len(tasks)} 个子任务，并发上限 {MAX_CONCURRENT_SUBAGENTS}"
        )

        # 并行执行所有子代理任务
        async def _run_with_semaphore(task: SubAgentTask) -> SubAgentResult:
            async with self._semaphore:
                subagent = SubAgent(
                    tool_registry=self._registry,
                    system_prompt=self._system_prompt,
                    task=task,
                    provider_router=self._provider_router,
                )
                try:
                    result = await asyncio.wait_for(
                        subagent.run(),
                        timeout=SUBAGENT_TIMEOUT,
                    )
                    return result
                except asyncio.TimeoutError:
                    return SubAgentResult(
                        task_id=task.task_id,
                        target=task.target,
                        status="timeout",
                        error_message=f"子代理超时 ({SUBAGENT_TIMEOUT}s)",
                    )
                except Exception as e:
                    return SubAgentResult(
                        task_id=task.task_id,
                        target=task.target,
                        status="error",
                        error_message=str(e),
                    )

        # 使用 wait_for 包裹整体编排（总超时保护）
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_run_with_semaphore(t) for t in tasks], return_exceptions=True),
                timeout=ORCHESTRATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏰ [SubAgent Orchestrator] 整体编排超时 ({ORCHESTRATION_TIMEOUT}s)")
            results = [
                SubAgentResult(
                    task_id=t.task_id,
                    target=t.target,
                    status="timeout",
                    error_message=f"整体编排超时 ({ORCHESTRATION_TIMEOUT}s)",
                )
                for t in tasks
            ]

        # 处理 gather 返回的异常
        processed_results: List[SubAgentResult] = []
        for task, result in zip(tasks, results):
            if isinstance(result, Exception):
                processed_results.append(
                    SubAgentResult(
                        task_id=task.task_id,
                        target=task.target,
                        status="error",
                        error_message=str(result),
                    )
                )
            else:
                processed_results.append(result)

        # 统计
        completed = sum(1 for r in processed_results if r.status == "success")
        failed = sum(1 for r in processed_results if r.status == "error")
        timed_out = sum(1 for r in processed_results if r.status == "timeout")
        total_time = time.monotonic() - t_start

        # 计算加速比（串行总耗时 / 并行实际耗时）
        serial_time = sum(r.execution_time for r in processed_results)
        speedup = serial_time / total_time if total_time > 0 else 1.0

        report = SubAgentOrchestratorReport(
            orchestration_id=orchestration_id,
            total_tasks=len(tasks),
            completed=completed,
            failed=failed,
            timed_out=timed_out,
            results=processed_results,
            total_execution_time=total_time,
            parallelism_speedup=speedup,
        )

        logger.info(
            f"✅ [SubAgent Orchestrator] 编排 {orchestration_id} 完成: "
            f"{completed}/{len(tasks)} 成功, {failed} 失败, {timed_out} 超时, "
            f"加速比 {speedup:.1f}x"
        )

        return report


# ========================================================================
# 便捷函数
# ========================================================================


async def run_parallel_analysis(
    tool_registry,
    tasks: List[SubAgentTask],
    system_prompt: str = "",
    provider_router=None,
    orchestration_id: str = "default",
) -> SubAgentOrchestratorReport:
    """
    便捷函数：创建编排器并并行执行子代理任务。

    Args:
        tool_registry: ToolRegistry 实例
        tasks: 子代理任务列表
        system_prompt: 系统指令
        provider_router: LLM provider router
        orchestration_id: 编排标识

    Returns:
        SubAgentOrchestratorReport: 汇总报告
    """
    orchestrator = SubAgentOrchestrator(
        tool_registry=tool_registry,
        system_prompt=system_prompt,
        provider_router=provider_router,
    )
    return await orchestrator.run_parallel(tasks, orchestration_id=orchestration_id)
