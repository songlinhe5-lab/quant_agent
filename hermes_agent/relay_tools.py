"""
==========================================================
AGENT-05 · 脚本经 RPC 批量调工具（零上下文成本轮次）
==========================================================

对标 hermes README "collapsing multi-step pipelines into zero-context-cost turns"
+ dsh `packages/sandbox` 分级安全思想。

核心思想：
  把 N 次带 LLM 上下文的工具往返（N × ~2000 tokens/轮）压成 1 轮批量执行。
  脚本（或前端批量请求）通过 RPC 协议一次性提交多个工具调用，
  服务端并发执行后聚合返回，全程不经过 LLM 上下文窗口。

安全约束（不可妥协）：
  1. 白名单仅限只读数据工具 — 严禁触达交易类（broker_trade_tool / EMERGENCY_LIQUIDATION）
  2. 依赖 AGENT-10 的环境擦洗（scrub_subprocess_env）
  3. 并发上限 + 超时保护，防止资源耗尽
  4. 每个工具调用仍走 AGENT-02 中间件管线（熔断/分类/缓存）

与 AGENT-03 的协同：
  白名单基于 ToolScope 过滤 — 只允许 quote/indicators/fund_flow/fundamental/macro/news/search
  明确排除 trade/system scope 的工具。

与 AGENT-02 的协同：
  批量执行中的每个工具调用仍经过 ToolRegistry.execute()（含中间件管线），
  保证熔断/分类/缓存等安全机制不失效。

与 AGENT-10 的协同：
  批量执行结果经 redact_obj 脱敏后才返回，防止凭据泄漏到脚本层。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from hermes_agent.scopes import ToolScope

# ========================================================================
# 批量安全白名单 — 仅允许只读数据工具
# ========================================================================

# 允许批量调用的 scope 集合（只读数据类）
BATCH_SAFE_SCOPES: Set[ToolScope] = frozenset(  # type: ignore[assignment]
    {
        ToolScope.QUOTE,  # 盘口实时价
        ToolScope.INDICATORS,  # 技术指标
        ToolScope.FUND_FLOW,  # 资金流
        ToolScope.FUNDAMENTAL,  # 基本面财务
        ToolScope.MACRO,  # 宏观数据
        ToolScope.NEWS,  # 新闻舆情
    }
)

# 明确禁止的 scope（交易/系统类 — 即使工具名伪装也不放行）
BLOCKED_SCOPES: Set[ToolScope] = frozenset(  # type: ignore[assignment]
    {
        ToolScope.TRADE,  # OMS 交易执行 — 绝对禁止
        ToolScope.SYSTEM,  # 系统工具 — 不允许批量调用
        ToolScope.BACKTEST,  # 回测引擎 — 计算密集，不适合批量
        ToolScope.STRATEGY,  # 策略实验室 — 同上
    }
)

# 额外硬编码黑名单（即使 scope 匹配也不允许批量调用）
# 理由：删除操作 / 写操作 / 高耗时操作
HARDCODED_BLOCKLIST: Set[str] = frozenset(
    {
        "delete_global_knowledge",  # 删除操作 — AGENT-14 安全约束
        "manage_broker_orders_and_account",  # 交易执行 — 绝对禁止
        "batch_backtest",  # 批量回测 — 计算密集
        "optimize_strategy",  # 策略寻优 — 计算密集
        "option_strategy_lab",  # 期权实验室 — 计算密集
        "option_volatility",  # 期权波动率 — 计算密集
        "send_notification",  # 推送通知 — 写操作
        "track_stock",  # 股票监控 — 写操作
        "download_report",  # 研报下载 — I/O 密集
    }
)

# ========================================================================
# 并发控制参数
# ========================================================================

# 单次批量请求最大工具调用数
MAX_BATCH_SIZE: int = 200

# 单个工具调用的超时时间（秒）
SINGLE_CALL_TIMEOUT: float = 30.0

# 整个批量请求的超时时间（秒）
BATCH_TIMEOUT: float = 120.0

# 最大并发数（防止同时发起过多请求）
MAX_CONCURRENCY: int = 20


# ========================================================================
# 数据结构
# ========================================================================


@dataclass
class BatchToolCall:
    """单次工具调用请求"""

    tool_name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None  # 可选的调用标识（用于结果关联）


@dataclass
class BatchToolResult:
    """单次工具调用结果"""

    call_id: str
    tool_name: str
    status: str  # success / error / timeout / blocked
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time: float = 0.0


@dataclass
class BatchExecutionReport:
    """批量执行报告 — 聚合所有调用结果"""

    batch_id: str
    total_calls: int
    successful: int
    failed: int
    blocked: int
    timed_out: int
    results: List[BatchToolResult] = field(default_factory=list)
    total_execution_time: float = 0.0
    wall_clock_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的 dict"""
        return {
            "batch_id": self.batch_id,
            "summary": {
                "total": self.total_calls,
                "successful": self.successful,
                "failed": self.failed,
                "blocked": self.blocked,
                "timed_out": self.timed_out,
            },
            "timing": {
                "total_execution_time": round(self.total_execution_time, 3),
                "wall_clock_time": round(self.wall_clock_time, 3),
            },
            "results": [
                {
                    "call_id": r.call_id,
                    "tool_name": r.tool_name,
                    "status": r.status,
                    "result": r.result,
                    "error_message": r.error_message,
                    "execution_time": round(r.execution_time, 3),
                }
                for r in self.results
            ],
        }


# ========================================================================
# 白名单验证器
# ========================================================================


class BatchToolValidator:
    """
    批量调用安全验证器。

    三层防护：
    1. 硬编码黑名单检查（最高优先级）
    2. scope 白名单检查（基于 AGENT-03 的 ToolScope）
    3. 未知工具拒绝（fail-closed 原则）
    """

    def __init__(self, tool_registry):
        """
        Args:
            tool_registry: ToolRegistry 实例（用于查询工具 scope）
        """
        self._registry = tool_registry

    def validate_tool(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """
        验证单个工具是否允许批量调用。

        Returns:
            (is_allowed, rejection_reason)
        """
        # Layer 1: 硬编码黑名单
        if tool_name in HARDCODED_BLOCKLIST:
            return False, f"工具 '{tool_name}' 在批量调用黑名单中（写操作/交易类/计算密集）"

        # Layer 2: 工具必须已注册（fail-closed）
        if tool_name not in self._registry.tools:
            return False, f"工具 '{tool_name}' 未注册或不存在"

        # Layer 3: scope 白名单检查
        tool = self._registry.tools[tool_name]
        tool_scopes = getattr(tool, "_tool_scopes", [])

        if not tool_scopes:
            # 无 scope 标注的工具 — fail-closed，不允许批量调用
            return False, f"工具 '{tool_name}' 无 scope 标注，拒绝批量调用（fail-closed）"

        # 检查是否有任何 scope 在禁止集合中
        for scope_str in tool_scopes:
            try:
                scope = ToolScope(scope_str)
            except ValueError:
                continue

            if scope in BLOCKED_SCOPES:
                return False, f"工具 '{tool_name}' 属于禁止 scope '{scope.value}'（交易/系统/回测类）"

        # 检查是否至少有一个 scope 在允许集合中
        has_allowed_scope = False
        for scope_str in tool_scopes:
            try:
                scope = ToolScope(scope_str)
            except ValueError:
                continue
            if scope in BATCH_SAFE_SCOPES:
                has_allowed_scope = True
                break

        if not has_allowed_scope:
            return False, f"工具 '{tool_name}' 不属于任何批量安全 scope"

        return True, None

    def validate_batch(self, calls: List[BatchToolCall]) -> tuple[List[BatchToolCall], List[BatchToolResult]]:
        """
        批量验证 — 分离合法调用和被拒绝的调用。

        Returns:
            (allowed_calls, blocked_results)
        """
        allowed = []
        blocked = []

        for i, call in enumerate(calls):
            call_id = call.call_id or f"call_{i}"
            is_allowed, reason = self.validate_tool(call.tool_name)

            if is_allowed:
                allowed.append(call)
            else:
                blocked.append(
                    BatchToolResult(
                        call_id=call_id,
                        tool_name=call.tool_name,
                        status="blocked",
                        error_message=reason,
                    )
                )

        return allowed, blocked


# ========================================================================
# 批量执行引擎
# ========================================================================


class BatchToolExecutor:
    """
    批量工具执行器。

    核心能力：
    1. 接收批量调用请求（List[BatchToolCall]）
    2. 安全验证（白名单 + scope 检查）
    3. 并发执行（asyncio.gather + 信号量限流）
    4. 结果聚合（BatchExecutionReport）
    5. 脱敏处理（AGENT-10 redact_obj）

    使用示例：
        executor = BatchToolExecutor(tool_registry)
        calls = [
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "AAPL"}),
            BatchToolCall("get_broker_market_data", {"action": "QUOTE", "ticker": "TSLA"}),
            BatchToolCall("get_fundamental_data", {"ticker": "MSFT"}),
        ]
        report = await executor.execute_batch(calls, batch_id="batch_001")
    """

    def __init__(self, tool_registry):
        self._registry = tool_registry
        self._validator = BatchToolValidator(tool_registry)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def execute_batch(
        self,
        calls: List[BatchToolCall],
        batch_id: str = "default",
    ) -> BatchExecutionReport:
        """
        执行批量工具调用。

        Args:
            calls: 工具调用列表
            batch_id: 批次标识（用于追踪）

        Returns:
            BatchExecutionReport — 包含所有调用结果的聚合报告
        """
        t_start = time.monotonic()

        # 0. 批量大小检查
        if len(calls) > MAX_BATCH_SIZE:
            return BatchExecutionReport(
                batch_id=batch_id,
                total_calls=len(calls),
                successful=0,
                failed=0,
                blocked=len(calls),
                timed_out=0,
                results=[
                    BatchToolResult(
                        call_id=call.call_id or f"call_{i}",
                        tool_name=call.tool_name,
                        status="blocked",
                        error_message=f"批量大小 {len(calls)} 超过上限 {MAX_BATCH_SIZE}",
                    )
                    for i, call in enumerate(calls)
                ],
                wall_clock_time=time.monotonic() - t_start,
            )

        # 1. 安全验证 — 分离合法/被拒调用
        allowed_calls, blocked_results = self._validator.validate_batch(calls)

        # 2. 并发执行合法调用
        execution_tasks = [
            self._execute_single(call, call.call_id or f"call_{i}") for i, call in enumerate(allowed_calls)
        ]
        execute_results = await asyncio.gather(*execution_tasks)

        # 3. 聚合结果
        all_results = list(blocked_results) + list(execute_results)

        # 4. AGENT-10: 结果脱敏
        from hermes_agent.redact import redact_obj

        for r in all_results:
            if r.result is not None:
                r.result = redact_obj(r.result)

        # 5. 统计
        successful = sum(1 for r in all_results if r.status == "success")
        failed = sum(1 for r in all_results if r.status == "error")
        blocked = sum(1 for r in all_results if r.status == "blocked")
        timed_out = sum(1 for r in all_results if r.status == "timeout")
        total_exec_time = sum(r.execution_time for r in all_results)

        t_end = time.monotonic()

        report = BatchExecutionReport(
            batch_id=batch_id,
            total_calls=len(calls),
            successful=successful,
            failed=failed,
            blocked=blocked,
            timed_out=timed_out,
            results=all_results,
            total_execution_time=total_exec_time,
            wall_clock_time=t_end - t_start,
        )

        print(
            f"📦 [BatchExecutor] batch={batch_id}: "
            f"{successful}✅ {failed}❌ {blocked}🚫 {timed_out}⏱️ "
            f"(wall={report.wall_clock_time:.2f}s, total_exec={total_exec_time:.2f}s)"
        )

        return report

    async def _execute_single(self, call: BatchToolCall, call_id: str) -> BatchToolResult:
        """
        执行单个工具调用（带并发限制 + 超时保护）。

        Args:
            call: 工具调用请求
            call_id: 调用标识

        Returns:
            BatchToolResult
        """
        t_start = time.monotonic()

        try:
            # 并发限制
            async with self._semaphore:
                # 超时保护
                result = await asyncio.wait_for(
                    self._registry.execute(call.tool_name, **call.arguments),
                    timeout=SINGLE_CALL_TIMEOUT,
                )

            t_end = time.monotonic()

            # 判断结果状态
            status = "success"
            error_msg = None
            if isinstance(result, dict):
                st = str(result.get("status", "")).lower()
                if st in ("error", "failed"):
                    status = "error"
                    error_msg = result.get("message", "未知错误")
                elif st == "circuit_breaker":
                    status = "error"
                    error_msg = result.get("message", "工具已熔断")

            return BatchToolResult(
                call_id=call_id,
                tool_name=call.tool_name,
                status=status,
                result=result,
                error_message=error_msg,
                execution_time=t_end - t_start,
            )

        except asyncio.TimeoutError:
            t_end = time.monotonic()
            return BatchToolResult(
                call_id=call_id,
                tool_name=call.tool_name,
                status="timeout",
                error_message=f"工具调用超时（>{SINGLE_CALL_TIMEOUT}s）",
                execution_time=t_end - t_start,
            )
        except Exception as e:
            t_end = time.monotonic()
            # AGENT-10: 异常消息脱敏
            from hermes_agent.redact import redact_exception

            return BatchToolResult(
                call_id=call_id,
                tool_name=call.tool_name,
                status="error",
                error_message=f"工具执行异常: {redact_exception(e)}",
                execution_time=t_end - t_start,
            )


# ========================================================================
# 便捷函数
# ========================================================================


async def execute_batch_tools(
    tool_registry,
    tool_calls: List[Dict[str, Any]],
    batch_id: str = "default",
) -> Dict[str, Any]:
    """
    便捷函数：接受 dict 列表，返回 dict 报告。

    Args:
        tool_registry: ToolRegistry 实例
        tool_calls: [{"tool_name": "...", "arguments": {...}}, ...]
        batch_id: 批次标识

    Returns:
        序列化的 BatchExecutionReport dict
    """
    calls = [
        BatchToolCall(
            tool_name=tc.get("tool_name", ""),
            arguments=tc.get("arguments", {}),
            call_id=tc.get("call_id"),
        )
        for tc in tool_calls
    ]

    executor = BatchToolExecutor(tool_registry)
    report = await executor.execute_batch(calls, batch_id=batch_id)
    return report.to_dict()
