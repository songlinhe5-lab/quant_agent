"""
共享数据包采集器
根据场景模板的 data_requirements，通过 ToolRegistry 并行采集数据
所有专家复用同一份数据包，避免重复调用外部 API
"""

import asyncio
import os
import traceback
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass

# 数据类型 → 采集工具映射
# param_key: 标的代码映射（'ticker' 时从请求 ticker 传入；None 表示该工具不需要 ticker）
# default_kwargs: 工具的固定参数（如 BrokerMarketTool 需要 action）
_DATA_COLLECTORS: dict[str, dict[str, Any]] = {
    # serial_group: 同组数据项串行执行（避免同一上游被并发打爆），不同组并行。
    # 以下 4 项底层均打到 Futu OpenD，归入 "futu" 组排队执行。
    "quote": {
        "tool": "get_broker_market_data",
        "param_key": "ticker",
        "default_kwargs": {"action": "QUOTE"},
        "description": "实时行情报价",
        "serial_group": "futu",
    },
    "fundamental": {
        "tool": "get_fundamental_data",
        "param_key": "ticker",
        "description": "基本面财务数据",
        "serial_group": "futu",
    },
    "technicals": {
        "tool": "calculate_technical_indicators",
        "param_key": "ticker",
        "description": "技术指标",
        "serial_group": "futu",
    },
    "macro_news": {
        "tool": "get_macro_news",
        "param_key": None,  # 无需 ticker
        "description": "宏观新闻",
    },
    "sentiment": {
        "tool": "get_macro_sentiment_history",
        "param_key": None,
        "description": "市场情绪历史",
    },
    "market_review": {
        "tool": "get_market_review",
        "param_key": "market",
        "default_kwargs": {"market": "美股"},  # market 为必填参数，默认采集美股复盘（项目主市场）
        "description": "市场复盘(宏观判因)",
    },
    "fed_watch": {
        "tool": "get_fed_watch",
        "param_key": None,  # 市场级，无需 ticker
        "description": "FedWatch FOMC 目标利率隐含概率(Tier1 前瞻)",
        "serial_group": "futu",
    },
    "code_context": {
        "tool": None,  # 由请求直接提供，不需要工具采集
        "param_key": None,
        "description": "代码上下文",
    },
}

# 单个工具采集超时 (秒)
_COLLECT_TIMEOUT = 30.0

# ── 采集并发控制（EXPERT-TEAM-SERIAL）────────────────────────────────
# 背景：投研会开场会一次性并发发起 6 个数据项（quote/fundamental/technicals/...），
# 其中 4 个打到同一上游（Futu OpenD）。瞬时并发会把上游打爆 → 限流/超时 →
# 失败计入熔断 → 3 次即停 60s，表现就是用户感知的"数据源不稳定、经常失败"。
# 策略（三层，逐级收敛压力）：
#   1) serial_group 相同的数据项串行执行（同组排队，避免同一上游被并发冲击）
#   2) 不同组之间并行，但受全局并发上限 _COLLECT_CONCURRENCY 约束
#   3) EXPERT_TEAM_COLLECT_SERIAL=1 时强制全串行（压力最小，耗时最长）
# 正常路径下单请求多为亚秒级，串行化的耗时代价远小于失败重来的代价。
# 以下默认值即经验值，普通用户零配置；env 仅留作线上紧急调参入口，不在 .env.example 暴露。
_COLLECT_CONCURRENCY = int(os.getenv("EXPERT_TEAM_COLLECT_CONCURRENCY", "3"))
_COLLECT_FORCE_SERIAL = os.getenv("EXPERT_TEAM_COLLECT_SERIAL", "0") == "1"
# 失败重试：仅对超时/网络类瞬时错误重试，指数退避
_COLLECT_MAX_RETRIES = int(os.getenv("EXPERT_TEAM_COLLECT_MAX_RETRIES", "1"))
_COLLECT_RETRY_BACKOFF = float(os.getenv("EXPERT_TEAM_COLLECT_RETRY_BACKOFF", "1.5"))

# 熔断/限流冷却期内重试必然失败，且会加重上游负担 → 直接放弃，快速失败
_NON_RETRYABLE_KEYWORDS = (
    "熔断",
    "circuit",
    "限流",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "cooldown",
    "429",
)


async def collect_shared_data(
    data_requirements: list[str],
    tool_registry: Optional[Any] = None,
    ticker: Optional[str] = None,
    code_context: Optional[str] = None,
    extra_context: Optional[dict[str, Any]] = None,
    on_progress: Optional[Any] = None,
) -> dict[str, Any]:
    """
    并行采集共享数据包。

    Args:
        data_requirements: 场景模板定义的数据需求列表
        tool_registry: ToolRegistry 实例 (用于调用工具)
        ticker: 金融域标的代码
        code_context: 代码域代码片段
        extra_context: 额外上下文
        on_progress: 可选回调 (async callable)，每个数据项采集完成时调用
            on_progress({key, status, message})，用于逐步透传采集进度（如前端折叠思考过程）。

    Returns:
        dict: { data_type: result_or_error }
    """
    shared_data: dict[str, Any] = {}
    tasks: list[tuple[str, asyncio.Task]] = []
    kwargs_for_tasks: dict[asyncio.Task, dict[str, Any]] = {}

    # 串行组锁（同组内排队，避免同一上游被并发冲击）+ 全局并发槽（限制总并发数）
    group_locks: dict[str, asyncio.Lock] = {}
    sem = asyncio.Semaphore(max(1, _COLLECT_CONCURRENCY))

    async def _run_collect(
        req_key: str,
        tool: str,
        call_kwargs: dict[str, Any],
        group: Optional[str],
    ) -> Any:
        """按组串行 + 全局并发受限地执行一次采集（含瞬时错误重试）。

        加锁顺序固定为「先抢并发槽、再抢组内锁」，避免与同组任务形成死锁。
        """
        # 强制全串行：所有数据项共用一个锁，等价于整体排队
        lock_key = group or ("__all__" if _COLLECT_FORCE_SERIAL else None)
        lock = group_locks.setdefault(lock_key, asyncio.Lock()) if lock_key else None

        async with sem:
            if lock is not None:
                async with lock:
                    return await _collect_with_retry(tool_registry, tool, req_key, call_kwargs, _COLLECT_MAX_RETRIES)
            return await _collect_with_retry(tool_registry, tool, req_key, call_kwargs, _COLLECT_MAX_RETRIES)

    for req in data_requirements:
        collector = _DATA_COLLECTORS.get(req)
        if not collector:
            shared_data[req] = {"status": "skipped", "reason": f"未知数据类型: {req}"}
            if on_progress:
                await on_progress(
                    {
                        "key": req,
                        "status": "skipped",
                        "message": f"未知数据类型: {req}",
                        "request": {"data_type": req},
                        "response": f"未知数据类型: {req}",
                    }
                )
            continue

        # code_context 直接从请求获取
        if req == "code_context":
            shared_data["code_context"] = code_context or ""
            if on_progress:
                await on_progress({"key": req, "status": "success", "message": "已注入代码上下文"})
            continue

        # 需要工具采集
        tool_name = collector["tool"]
        if not tool_name or not tool_registry:
            shared_data[req] = {"status": "skipped", "reason": "工具不可用"}
            if on_progress:
                await on_progress(
                    {
                        "key": req,
                        "status": "skipped",
                        "message": "工具不可用",
                        "request": {"tool": tool_name},
                        "response": "工具不可用",
                    }
                )
            continue

        # 构建参数：固定参数(default_kwargs) + ticker（若工具需要且提供了）
        kwargs: dict[str, Any] = dict(collector.get("default_kwargs") or {})
        if collector["param_key"] == "ticker":
            if not ticker:
                # 无标的但该项需要个股代码：明确报错，而非静默跳过，避免后续流程误以为数据可用
                shared_data[req] = {"status": "error", "reason": "未绑定标的（ticker 缺失），个股数据无法采集"}
                if on_progress:
                    await on_progress(
                        {
                            "key": req,
                            "status": "error",
                            "message": "未绑定标的，个股数据无法采集",
                            "request": dict(collector.get("default_kwargs") or {}),
                            "response": "未绑定标的（ticker 缺失），个股数据无法采集",
                        }
                    )
                continue
            kwargs["ticker"] = ticker

        # 创建异步采集任务（记录请求参数，供折叠展示请求内容）
        # 串行组由 _DATA_COLLECTORS[x]["serial_group"] 声明 → 控制「串行到哪个任务」
        task = asyncio.create_task(_run_collect(req, tool_name, kwargs, collector.get("serial_group")))
        tasks.append((req, task))
        kwargs_for_tasks[task] = kwargs

    # 并行等待所有采集任务：每完成一个即回调，实现逐步透传（FIRST_COMPLETED 逐步取）
    if tasks:
        pending: set[asyncio.Task] = set(t for _, t in tasks)
        task_to_key = {t: r for r, t in tasks}
        task_to_kwargs = {t: kwargs_for_tasks.get(t) for t in tasks}
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for coro in done:
                req = task_to_key.get(coro)
                if req is None:
                    continue
                try:
                    result = coro.result()
                except Exception as e:  # noqa: BLE001
                    result = {"status": "error", "message": f"采集异常: {str(e)}"}
                shared_data[req] = result
                if on_progress:
                    req_kwargs = task_to_kwargs.get(coro) or {}
                    # 请求内容：补工具名，避免无参工具显示空 {}（如 macro_news/fed_watch）
                    _collector = _DATA_COLLECTORS.get(req, {})
                    req_show = {"tool": _collector.get("tool", req)}
                    if req_kwargs:
                        req_show.update(req_kwargs)
                    # 携带请求参数与响应摘要，供前端折叠展示"请求/响应内容"
                    await on_progress(
                        {
                            "key": req,
                            "status": "success"
                            if not (
                                isinstance(result, dict) and result.get("status") in ("error", "timeout", "skipped")
                            )
                            else result.get("status"),
                            "message": (
                                result.get("message")
                                if isinstance(result, dict) and result.get("message")
                                else f"{req} 采集完成"
                            ),
                            "request": req_show,
                            "response": _summarize_result(result),
                        }
                    )

    # 合并额外上下文
    if extra_context:
        shared_data["extra"] = extra_context

    return shared_data


async def _safe_collect(
    registry: Any,
    tool_name: str,
    data_type: str,
    kwargs: dict[str, Any],
) -> Any:
    """带超时保护的单工具采集"""
    try:
        result = await asyncio.wait_for(
            registry.execute(tool_name, **kwargs),
            timeout=_COLLECT_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "message": f"{data_type} 采集超时 ({_COLLECT_TIMEOUT}s)",
        }
    except Exception as e:
        print(f"⚠️ [DataCollector] {data_type} 采集失败: {e}\n{traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"{data_type} 采集失败: {str(e)}",
        }


def _is_retryable(result: Any) -> bool:
    """判定采集结果是否值得重试。

    仅超时/网络类瞬时错误值得重试；熔断/限流冷却期内重试必然失败，
    且会持续消耗上游额度、延长恢复时间，故直接放弃、快速失败。
    """
    if not isinstance(result, dict):
        return False
    if result.get("status") not in ("timeout", "error"):
        return False
    text = f"{result.get('message', '')} {result.get('reason', '')}".lower()
    return not any(k in text for k in _NON_RETRYABLE_KEYWORDS)


async def _collect_with_retry(
    registry: Any,
    tool_name: str,
    data_type: str,
    kwargs: dict[str, Any],
    max_retries: int,
) -> Any:
    """带重试的单工具采集：仅对瞬时错误做指数退避重试，避免抖动直接判死。"""
    result: Any = None
    for attempt in range(max(0, max_retries) + 1):
        result = await _safe_collect(registry, tool_name, data_type, kwargs)
        if not _is_retryable(result) or attempt >= max(0, max_retries):
            return result
        delay = _COLLECT_RETRY_BACKOFF * (2**attempt)
        print(f"↻ [DataCollector] {data_type} 瞬时失败，{delay:.1f}s 后第 {attempt + 1} 次重试")
        await asyncio.sleep(delay)
    return result


def _summarize_result(result: Any, max_chars: int = 600) -> str:
    """把工具返回结果摘要成短文本（供前端折叠展示响应内容），避免把超大数据整包透传。"""
    import json as _json

    try:
        if isinstance(result, dict):
            # 错误/超时：返回 message
            if result.get("status") in ("error", "timeout", "skipped"):
                return str(result.get("message", ""))[:max_chars]
            # 成功：返回关键字段摘要
            data = result.get("data", result)
            if isinstance(data, (dict, list)):
                return _json.dumps(data, ensure_ascii=False, default=str)[:max_chars]
            return str(data)[:max_chars]
        if isinstance(result, (list, dict)):
            return _json.dumps(result, ensure_ascii=False, default=str)[:max_chars]
        return str(result)[:max_chars]
    except Exception:  # noqa: BLE001
        return str(result)[:max_chars]


def format_shared_data_for_prompt(shared_data: dict[str, Any], max_chars: int = 8000) -> str:
    """
    将共享数据包格式化为 prompt 可读文本。
    控制总长度避免超出上下文窗口。
    """
    import json

    sections: list[str] = []
    total_len = 0

    for key, value in shared_data.items():
        if key == "extra":
            continue

        # 跳过错误/跳过状态
        if isinstance(value, dict) and value.get("status") in ("error", "skipped", "timeout"):
            sections.append(f"## {key}\n[数据不可用: {value.get('message', value.get('reason', ''))}]")
            continue

        # 序列化
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(value)

        # 截断过长数据
        if len(text) > 2000:
            text = text[:2000] + "\n... [数据已截断]"

        section = f"## {key}\n{text}"
        if total_len + len(section) > max_chars:
            sections.append(f"## {key}\n[超出长度限制，已省略]")
            continue

        sections.append(section)
        total_len += len(section)

    return "\n\n".join(sections)
