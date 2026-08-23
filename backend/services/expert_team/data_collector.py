"""
共享数据包采集器
根据场景模板的 data_requirements，通过 ToolRegistry 并行采集数据
所有专家复用同一份数据包，避免重复调用外部 API
"""

import asyncio
import traceback
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass

# 数据类型 → 采集工具映射
_DATA_COLLECTORS: dict[str, dict[str, Any]] = {
    "quote": {
        "tool": "get_broker_market_data",
        "param_key": "ticker",
        "description": "实时行情报价",
    },
    "fundamental": {
        "tool": "get_fundamental_data",
        "param_key": "ticker",
        "description": "基本面财务数据",
    },
    "technicals": {
        "tool": "calculate_technical_indicators",
        "param_key": "ticker",
        "description": "技术指标",
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
        "description": "市场复盘(宏观判因)",
    },
    "fed_watch": {
        "tool": "get_fed_watch",
        "param_key": None,  # 市场级，无需 ticker
        "description": "FedWatch FOMC 目标利率隐含概率(Tier1 前瞻)",
    },
    "code_context": {
        "tool": None,  # 由请求直接提供，不需要工具采集
        "param_key": None,
        "description": "代码上下文",
    },
}

# 单个工具采集超时 (秒)
_COLLECT_TIMEOUT = 30.0


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

    for req in data_requirements:
        collector = _DATA_COLLECTORS.get(req)
        if not collector:
            shared_data[req] = {"status": "skipped", "reason": f"未知数据类型: {req}"}
            if on_progress:
                await on_progress({"key": req, "status": "skipped", "message": f"未知数据类型: {req}"})
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
                await on_progress({"key": req, "status": "skipped", "message": "工具不可用"})
            continue

        # 构建参数
        kwargs: dict[str, Any] = {}
        if collector["param_key"] == "ticker" and ticker:
            kwargs["ticker"] = ticker

        # 创建异步采集任务
        task = asyncio.create_task(_safe_collect(tool_registry, tool_name, req, kwargs))
        tasks.append((req, task))

    # 并行等待所有采集任务：每完成一个即回调，实现逐步透传（FIRST_COMPLETED 逐步取）
    if tasks:
        pending: set[asyncio.Task] = set(t for _, t in tasks)
        task_to_key = {t: r for r, t in tasks}
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for coro in done:
                req = task_to_key.get(coro)
                try:
                    result = coro.result()
                except Exception as e:  # noqa: BLE001
                    result = {"status": "error", "message": f"采集异常: {str(e)}"}
                if req is None:
                    continue
                shared_data[req] = result
                if on_progress:
                    if isinstance(result, dict) and result.get("status") in ("error", "timeout", "skipped"):
                        await on_progress(
                            {"key": req, "status": result.get("status"), "message": result.get("message", "")}
                        )
                    else:
                        await on_progress({"key": req, "status": "success", "message": f"{req} 采集完成"})

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
