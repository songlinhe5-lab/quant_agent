"""
AGENT-02 · 工具执行中间件管线
AGENT-09 · 工具结果正交分类

职责链模式（dsh waterfall 语义）：
  pre_execute → execute → post_execute
  每个中间件必须调用 next() 委托，不调即终止。

中间件默认顺序（ToolRegistry.build_pipeline）：
  1. circuit_breaker  — 失败熔断（AGENT-02 §4.4：同一 Tool 连续失败 3 次中止）
  2. result_classifier — 结果正交分类（AGENT-09）
  3. execution_timer  — 执行耗时记录
  4. core_execute     — 实际的 tool.run() 调用（终节点，不可移除）

正交分类标志（AGENT-09 · dsh defensive-patterns 首条）：
  success / empty / stale / rate_limited / error / circuit_breaker
  各自独立成标志，禁止嵌套在彼此的分支里。
  限流（rate_limited）不计入失败熔断计数（AGENTS.md §10.8）。
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

# ========================================================================
# AGENT-09: 正交结果分类
# ========================================================================


class ToolResultStatus(str, enum.Enum):
    """
    工具结果正交分类（AGENT-09）。

    各标志独立，禁止嵌套在彼此的分支里（dsh: "a process can time out AND exit 0"）。
    限流（rate_limited）不计入失败熔断计数（AGENTS.md §10.8）。
    """

    SUCCESS = "success"  # 正常返回有效数据
    EMPTY = "empty"  # 合法空结果（盘后无数据 / 查询无匹配）
    STALE = "stale"  # 数据过期（时间戳超阈值）
    RATE_LIMITED = "rate_limited"  # 被下游限流（429 / quota）
    ERROR = "error"  # 真正的执行失败
    CIRCUIT_BREAKER = "circuit_breaker"  # 本工具连续失败达阈值，熔断中止


# 限流类状态 — 不计入失败熔断计数（AGENTS.md §10.8）
_NON_FAILURE_STATUSES = frozenset(
    {
        ToolResultStatus.RATE_LIMITED,
        ToolResultStatus.SUCCESS,
        ToolResultStatus.EMPTY,
        ToolResultStatus.STALE,
        ToolResultStatus.CIRCUIT_BREAKER,
    }
)


@dataclass
class ToolContext:
    """中间件管线上下文 — 贯穿 pre → execute → post 全链路。"""

    tool_name: str
    kwargs: Dict[str, Any]
    attempt: int = 0  # 当前是第几次尝试（熔断器用于判断）
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """
    中间件管线标准化输出。

    所有中间件均可修改 result（post_execute 阶段），
    最终由 _safe_execute_tool 转为 dict 返回给 _react_loop。
    """

    status: ToolResultStatus
    data: Any = None
    message: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        转为向后兼容的 dict 格式（供 LLM 上下文 + SSE tool_result 事件）。

        当 data 为 dict 且不含自有 status 时，扁平化合并：
          ToolResult(SUCCESS, data={"price": 150}) → {"status": "success", "price": 150}
        当 data 为 dict 且含 status（工具原始返回）时，保留原始结构：
          ToolResult(SUCCESS, data={"status":"success","data":{"n":1}}) → 原样保留
        """
        if isinstance(self.data, dict) and "status" not in self.data:
            # 扁平化：data dict 的内容提升到顶层
            d: Dict[str, Any] = {**self.data}
            d["status"] = self.status.value  # 正交 status 始终覆盖
        else:
            d = {"status": self.status.value}
            if self.data is not None:
                d["data"] = self.data

        if self.message:
            d["message"] = self.message
        if self.execution_time > 0:
            d["execution_time"] = round(self.execution_time, 3)
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# ========================================================================
# 中间件协议（dsh waterfall 语义）
# ========================================================================

NextFn = Callable[[ToolContext], Awaitable[ToolResult]]
MiddlewareFn = Callable[[ToolContext, NextFn], Awaitable[ToolResult]]


class ToolMiddleware(Protocol):
    """工具中间件协议。

    实现者必须：
    1. 接收 (ctx, next) 参数
    2. 在 pre 阶段做检查/拦截
    3. 调用 await next(ctx) 委托给下游
    4. 在 post 阶段处理/转换结果
    5. 不调 next() 即终止链路（如熔断器触发时）
    """

    async def __call__(self, ctx: ToolContext, next: NextFn) -> ToolResult: ...  # pragma: no cover


# ========================================================================
# 中间件管线
# ========================================================================


class ToolMiddlewarePipeline:
    """
    工具执行中间件管线。

    用法：
        pipeline = ToolMiddlewarePipeline()
        pipeline.use(circuit_breaker_middleware)
        pipeline.use(result_classifier_middleware)
        result = await pipeline.execute(ctx, core_execute_fn)
    """

    def __init__(self) -> None:
        self._middlewares: List[MiddlewareFn] = []

    def use(self, middleware: MiddlewareFn) -> None:
        """追加中间件到管线尾部（执行顺序 = 注册顺序）。"""
        self._middlewares.append(middleware)

    async def execute(
        self,
        ctx: ToolContext,
        core: Callable[[ToolContext], Awaitable[ToolResult]],
    ) -> ToolResult:
        """
        执行管线：从第一个中间件开始，层层委托到 core。

        如果管线为空，直接执行 core。
        """
        if not self._middlewares:
            return await core(ctx)

        # 从内到外构建调用链：core 是最内层
        chain = core
        for mw in reversed(self._middlewares):
            prev_chain = chain

            async def make_next(middleware, inner):
                async def next_fn(c: ToolContext) -> ToolResult:
                    return await middleware(c, inner)

                return next_fn

            chain = await make_next(mw, prev_chain)

        return await chain(ctx)


# ========================================================================
# 内建中间件
# ========================================================================


class FailureTracker:
    """
    每工具连续失败计数器（AGENT-02 §4.4）。

    - 同一 Tool 连续失败 3 次 → 熔断
    - 成功 / 限流 / 空结果 → 重置计数（不计入失败）
    - 限流（rate_limited）明确不计入（AGENTS.md §10.8）
    """

    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold
        self._counts: Dict[str, int] = {}
        self._last_errors: Dict[str, str] = {}

    @property
    def threshold(self) -> int:
        return self._threshold

    def get_count(self, tool_name: str) -> int:
        return self._counts.get(tool_name, 0)

    def get_last_error(self, tool_name: str) -> str:
        return self._last_errors.get(tool_name, "")

    def record_failure(self, tool_name: str, error_msg: str) -> None:
        """记录一次失败。"""
        self._counts[tool_name] = self._counts.get(tool_name, 0) + 1
        self._last_errors[tool_name] = error_msg

    def record_success(self, tool_name: str) -> None:
        """成功时重置计数。"""
        self._counts.pop(tool_name, None)
        self._last_errors.pop(tool_name, None)

    def is_tripped(self, tool_name: str) -> bool:
        """检查是否已熔断。"""
        return self.get_count(tool_name) >= self._threshold

    def reset_all(self) -> None:
        """重置所有计数器（新会话 / 新 ReAct 轮次时调用）。"""
        self._counts.clear()
        self._last_errors.clear()

    def build_breaker_report(self, tool_name: str) -> Dict[str, str]:
        """
        生成 AGENTS.md §4.4 三要素熔断报告：
        1. 失败 Tool 名
        2. 错误原因
        3. 建议检查配置项
        """
        return {
            "tool": tool_name,
            "reason": self.get_last_error(tool_name) or "未知错误",
            "suggestion": _suggest_config_check(tool_name),
            "consecutive_failures": str(self.get_count(tool_name)),
        }


def _suggest_config_check(tool_name: str) -> str:
    """根据工具名生成建议检查项。"""
    _KNOWN_SUGGESTIONS = {
        "get_broker_market_data": "检查 Futu OpenD 连接状态 / 券商 API 密钥是否过期 / 网络连通性",
        "calculate_technical_indicators": "检查 K 线数据源可用性 / 标的是否存在",
        "get_fundamental_data": "检查 FMP/Tushare API Key / 标的代码格式是否正确",
        "get_macro_news": "检查 Finnhub WebSocket 连接 / API 配额",
        "get_company_news": "检查新闻数据源 API Key / 标的代码格式",
        "web_search": "检查搜索引擎 API Key / 配额 / 网络连通性",
        "fetch_webpage": "检查目标 URL 可达性 / 反爬策略",
        "screen_stocks": "检查选股数据源连接 / 筛选条件是否合法",
    }
    # 前缀匹配（工具名可能带后缀）
    for prefix, suggestion in _KNOWN_SUGGESTIONS.items():
        if tool_name.startswith(prefix):
            return suggestion
    return f"检查 {tool_name} 的数据源连接 / API 密钥 / 输入参数格式"


def make_circuit_breaker_middleware(tracker: FailureTracker) -> MiddlewareFn:
    """
    创建失败熔断中间件。

    pre_execute: 检查 tracker.is_tripped → 若已熔断则短路返回 circuit_breaker
    post_execute: 根据结果分类更新 tracker 计数
    """

    async def middleware(ctx: ToolContext, next: NextFn) -> ToolResult:
        # ── pre: 熔断检查 ──
        if tracker.is_tripped(ctx.tool_name):
            report = tracker.build_breaker_report(ctx.tool_name)
            return ToolResult(
                status=ToolResultStatus.CIRCUIT_BREAKER,
                data=report,
                message=(
                    f"⚠️ 工具 '{ctx.tool_name}' 连续失败 {report['consecutive_failures']} 次，"
                    f"已触发熔断保护。\n"
                    f"失败原因: {report['reason']}\n"
                    f"建议检查: {report['suggestion']}"
                ),
            )

        # ── delegate ──
        result = await next(ctx)

        # ── post: 原始结果透传（失败追踪由 execute() 后处理负责）──
        return result

    return middleware


def make_result_classifier_middleware() -> MiddlewareFn:
    """
    结果正交分类中间件（AGENT-09）。

    将 tool.run() 返回的原始 dict 分类为标准 ToolResultStatus。
    如果下游已返回 ToolResult（如熔断器短路），则直接透传。
    """

    async def middleware(ctx: ToolContext, next: NextFn) -> ToolResult:
        result = await next(ctx)

        # 如果已经是 ToolResult（由熔断器等中间件产生），直接透传
        if isinstance(result, ToolResult):
            return result

        # 对原始工具返回值进行分类
        return classify_raw_result(result)

    return middleware


def classify_raw_result(result: Any) -> ToolResult:
    """
    将原始工具返回值分类为 ToolResult。

    分类规则（按优先级）：
    1. None → EMPTY
    2. dict with status="error" → ERROR
    3. dict with status="rate_limited" / 429 相关 → RATE_LIMITED
    4. dict with empty data + no error → EMPTY
    5. dict with _stale flag → STALE
    6. 其他 dict / list / 基础类型 → SUCCESS
    """
    if result is None:
        return ToolResult(status=ToolResultStatus.EMPTY, message="工具返回空值")

    if isinstance(result, dict):
        status_val = str(result.get("status", "")).lower()

        # 限流检测（优先级高于 error，因为限流不计入失败）
        if status_val == "rate_limited" or result.get("rate_limited"):
            return ToolResult(
                status=ToolResultStatus.RATE_LIMITED,
                data=result,
                message=result.get("message", "下游限流"),
            )

        # 错误检测
        if status_val in ("error", "failed"):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                data=result,
                message=result.get("message", result.get("error", "执行失败")),
            )

        # 过期检测
        if result.get("_stale") or result.get("stale"):
            return ToolResult(
                status=ToolResultStatus.STALE,
                data=result,
                message=result.get("message", "数据已过期"),
            )

        # 空结果检测（有 status 但无实质数据）
        if result.get("error") and not result.get("data"):
            return ToolResult(
                status=ToolResultStatus.ERROR,
                data=result,
                message=result.get("error", "错误且无数据"),
            )

        # 成功（包含空数据但非错误的情况）
        return ToolResult(status=ToolResultStatus.SUCCESS, data=result)

    # 非 dict 类型（list / str / int 等）→ 视为成功
    return ToolResult(status=ToolResultStatus.SUCCESS, data=result)


def make_execution_timer_middleware() -> MiddlewareFn:
    """执行耗时记录中间件。"""

    async def middleware(ctx: ToolContext, next: NextFn) -> ToolResult:
        start = time.monotonic()
        result = await next(ctx)
        result.execution_time = time.monotonic() - start
        return result

    return middleware


# ========================================================================
# 核心执行函数（管线的终节点）
# ========================================================================


async def core_tool_execute(ctx: ToolContext, tools: Dict[str, Any]) -> Any:
    """
    实际调用 tool.run() — 管线最内层。

    返回原始工具结果（不做 ToolResult 包装），由上层 execute() 统一分类。
    异常时返回 {"status": "error", "message": "..."} 保持向后兼容。

    Args:
        ctx: 中间件上下文
        tools: ToolRegistry.tools 字典 {name: tool_instance}

    Returns:
        Any: 工具原始返回值（dict / list / 基础类型）
    """
    tool = tools.get(ctx.tool_name)
    if tool is None:
        return {"status": "error", "message": f"未找到名为 '{ctx.tool_name}' 的工具。"}

    try:
        if inspect.iscoroutinefunction(tool.run):
            return await tool.run(**ctx.kwargs)
        else:
            return await asyncio.to_thread(tool.run, **ctx.kwargs)
    except Exception as e:
        return {"status": "error", "message": f"工具执行异常: {str(e)}"}
