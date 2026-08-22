"""
==========================================================
重复/停滞守卫 (AGENT-12)
==========================================================

检测 Agent ReAct 循环中的死循环和停滞模式，在耗满 max_iterations 之前
提前识别并中止，避免无意义的 token 消耗和用户等待。

检测维度：
1. 同参数重复调用：连续 N 次调用同一工具且参数完全相同
2. 同结论重复输出：连续 N 次输出相同的结论文本
3. 工具调用无进展：连续 N 次工具调用返回相同/相似结果
4. 循环模式检测：A→B→A→B 的交替循环模式

策略：
- 滑动窗口：维护最近 K 次调用的历史记录
- 相似度阈值：文本相似度 > 0.9 视为重复
- 早停机制：3 轮内识别停滞并中止（而非耗满 8 轮）
- 原因说明：中止时提供详细的停滞原因分析

与 AGENT-04 的协同：
- 在 _react_loop 中集成，每次工具调用后检查
- 检测到停滞时，提前退出循环并返回原因
- 不改变 SSE 事件契约（error 事件携带停滞原因）

键空间（Redis）：
- 会话停滞统计: quant:metrics:agent:stuck:{session_id}:{date}
- 全局停滞统计: quant:metrics:agent:stuck:global:{date}

对齐 token_usage_store 的设计：Redis 不可用时静默降级。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
REPETITION_GUARD_ENABLED = os.getenv("REPETITION_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# 检测参数
MAX_CONSECUTIVE_IDENTICAL_CALLS = 3  # 同参数重复调用阈值
MAX_CONSECUTIVE_IDENTICAL_OUTPUTS = 2  # 同结论重复输出阈值
MAX_CONSECUTIVE_NO_PROGRESS = 4  # 无进展调用阈值
SIMILARITY_THRESHOLD = 0.9  # 文本相似度阈值
SLIDING_WINDOW_SIZE = 10  # 滑动窗口大小

# Prometheus 指标（延迟初始化）
_STUCK_DETECTION_COUNTER: Any = None
_STUCK_REASON_GAUGE: Any = None

# Redis TTL
_STUCK_TTL = 7 * 86400  # 7 天


def _init_metrics():
    """延迟初始化 Prometheus 指标"""
    global _STUCK_DETECTION_COUNTER, _STUCK_REASON_GAUGE
    if _STUCK_DETECTION_COUNTER is not None:
        return
    try:
        from prometheus_client import Counter, Gauge

        _STUCK_DETECTION_COUNTER = Counter(
            "agent_stuck_detection_total",
            "Agent 停滞检测触发次数",
            ["session_id", "reason"],
        )
        _STUCK_REASON_GAUGE = Gauge(
            "agent_stuck_iterations_saved",
            "Agent 停滞检测节省的迭代轮数",
            ["session_id"],
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RepetitionGuard] Prometheus 指标初始化失败: {e}")


@dataclass
class StuckDetectionResult:
    """
    停滞检测结果

    - is_stuck: 是否检测到停滞
    - reason: 停滞原因（如 "identical_tool_calls", "no_progress", "loop_pattern"）
    - details: 详细信息（如重复的工具名称、参数、输出等）
    - iterations_saved: 节省的迭代轮数（max_iterations - current_iteration）
    """

    is_stuck: bool
    reason: Optional[str]
    details: Optional[Dict[str, Any]]
    iterations_saved: int


@dataclass
class ToolCallRecord:
    """工具调用记录"""

    tool_name: str
    arguments_hash: str  # 参数哈希（用于快速比较）
    result_hash: str  # 结果哈希
    timestamp: float
    output_summary: str  # 输出摘要（用于相似度比较）


class RepetitionGuard:
    """
    重复/停滞守卫

    - record_tool_call(): 记录工具调用
    - check_stuck(): 检测是否停滞
    - reset(): 重置检测状态
    - get_stuck_stats(): 查询停滞统计
    """

    def __init__(self, enabled: bool = REPETITION_GUARD_ENABLED) -> None:
        self._enabled = enabled
        # 滑动窗口：最近 K 次调用
        self._call_history: List[ToolCallRecord] = []
        # 内存降级统计
        self._stuck_count: Dict[str, int] = {}  # session_id -> count

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        output_summary: str = "",
    ) -> None:
        """
        记录工具调用

        Args:
            tool_name: 工具名称
            arguments: 工具参数（dict）
            result: 工具返回结果
            output_summary: 输出摘要（可选，用于相似度比较）
        """
        if not self._enabled:
            return

        # 计算参数哈希
        import json

        args_str = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        args_hash = hashlib.sha256(args_str.encode()).hexdigest()[:16]

        # 计算结果哈希
        result_str = str(result)
        result_hash = hashlib.sha256(result_str.encode()).hexdigest()[:16]

        # 创建调用记录
        record = ToolCallRecord(
            tool_name=tool_name,
            arguments_hash=args_hash,
            result_hash=result_hash,
            timestamp=datetime.now().timestamp(),
            output_summary=output_summary or result_str[:200],  # 默认取前 200 字符
        )

        # 添加到滑动窗口
        self._call_history.append(record)
        if len(self._call_history) > SLIDING_WINDOW_SIZE:
            self._call_history.pop(0)

    def check_stuck(self, current_iteration: int, max_iterations: int) -> StuckDetectionResult:
        """
        检测是否停滞

        Args:
            current_iteration: 当前迭代轮数
            max_iterations: 最大迭代轮数

        Returns:
            StuckDetectionResult 对象
        """
        if not self._enabled or len(self._call_history) < 2:
            return StuckDetectionResult(
                is_stuck=False,
                reason=None,
                details=None,
                iterations_saved=max_iterations - current_iteration,
            )

        # 计算节省的迭代轮数
        iterations_saved = max_iterations - current_iteration

        # 检测维度 1: 同参数重复调用
        identical_calls_result = self._check_identical_tool_calls()
        if identical_calls_result.is_stuck:
            identical_calls_result.iterations_saved = iterations_saved
            return identical_calls_result

        # 检测维度 2: 同结论重复输出
        identical_outputs_result = self._check_identical_outputs()
        if identical_outputs_result.is_stuck:
            identical_outputs_result.iterations_saved = iterations_saved
            return identical_outputs_result

        # 检测维度 3: 工具调用无进展
        no_progress_result = self._check_no_progress()
        if no_progress_result.is_stuck:
            no_progress_result.iterations_saved = iterations_saved
            return no_progress_result

        # 检测维度 4: 循环模式检测
        loop_pattern_result = self._check_loop_pattern()
        if loop_pattern_result.is_stuck:
            loop_pattern_result.iterations_saved = iterations_saved
            return loop_pattern_result

        # 未检测到停滞
        return StuckDetectionResult(
            is_stuck=False,
            reason=None,
            details=None,
            iterations_saved=iterations_saved,
        )

    def _check_identical_tool_calls(self) -> StuckDetectionResult:
        """检测同参数重复调用"""
        if len(self._call_history) < MAX_CONSECUTIVE_IDENTICAL_CALLS:
            return StuckDetectionResult(False, None, None, 0)

        # 检查最近 N 次调用是否完全相同
        recent_calls = self._call_history[-MAX_CONSECUTIVE_IDENTICAL_CALLS:]
        first_call = recent_calls[0]

        all_identical = all(
            call.tool_name == first_call.tool_name and call.arguments_hash == first_call.arguments_hash
            for call in recent_calls
        )

        if all_identical:
            return StuckDetectionResult(
                is_stuck=True,
                reason="identical_tool_calls",
                details={
                    "tool_name": first_call.tool_name,
                    "arguments_hash": first_call.arguments_hash,
                    "consecutive_count": MAX_CONSECUTIVE_IDENTICAL_CALLS,
                },
                iterations_saved=0,  # 由调用方计算
            )

        return StuckDetectionResult(False, None, None, 0)

    def _check_identical_outputs(self) -> StuckDetectionResult:
        """检测同结论重复输出"""
        if len(self._call_history) < MAX_CONSECUTIVE_IDENTICAL_OUTPUTS:
            return StuckDetectionResult(False, None, None, 0)

        # 检查最近 N 次输出是否相似
        recent_outputs = [call.output_summary for call in self._call_history[-MAX_CONSECUTIVE_IDENTICAL_OUTPUTS:]]
        first_output = recent_outputs[0]

        # 简单相似度检查（完全相同或相似度 > 阈值）
        similar_count = 0
        for output in recent_outputs[1:]:
            if output == first_output:
                similar_count += 1
            else:
                # 计算文本相似度（Jaccard 相似度）
                similarity = self._calculate_text_similarity(first_output, output)
                if similarity > SIMILARITY_THRESHOLD:
                    similar_count += 1

        if similar_count >= MAX_CONSECUTIVE_IDENTICAL_OUTPUTS - 1:
            return StuckDetectionResult(
                is_stuck=True,
                reason="identical_outputs",
                details={
                    "output_summary": first_output[:100],
                    "consecutive_count": MAX_CONSECUTIVE_IDENTICAL_OUTPUTS,
                },
                iterations_saved=0,
            )

        return StuckDetectionResult(False, None, None, 0)

    def _check_no_progress(self) -> StuckDetectionResult:
        """检测工具调用无进展（连续 N 次返回相同结果）"""
        if len(self._call_history) < MAX_CONSECUTIVE_NO_PROGRESS:
            return StuckDetectionResult(False, None, None, 0)

        # 检查最近 N 次调用结果是否相同
        recent_calls = self._call_history[-MAX_CONSECUTIVE_NO_PROGRESS:]
        first_result = recent_calls[0].result_hash

        all_same = all(call.result_hash == first_result for call in recent_calls)

        if all_same:
            return StuckDetectionResult(
                is_stuck=True,
                reason="no_progress",
                details={
                    "tool_names": [call.tool_name for call in recent_calls],
                    "result_hash": first_result,
                    "consecutive_count": MAX_CONSECUTIVE_NO_PROGRESS,
                },
                iterations_saved=0,
            )

        return StuckDetectionResult(False, None, None, 0)

    def _check_loop_pattern(self) -> StuckDetectionResult:
        """检测循环模式（A→B→A→B）"""
        if len(self._call_history) < 4:
            return StuckDetectionResult(False, None, None, 0)

        # 检查最近 4 次调用是否形成 A→B→A→B 模式
        recent_calls = self._call_history[-4:]

        # A→B→A→B 模式：call[0] == call[2] and call[1] == call[3]
        if (
            recent_calls[0].tool_name == recent_calls[2].tool_name
            and recent_calls[0].arguments_hash == recent_calls[2].arguments_hash
            and recent_calls[1].tool_name == recent_calls[3].tool_name
            and recent_calls[1].arguments_hash == recent_calls[3].arguments_hash
        ):
            return StuckDetectionResult(
                is_stuck=True,
                reason="loop_pattern",
                details={
                    "pattern": [recent_calls[0].tool_name, recent_calls[1].tool_name],
                    "loop_count": 2,
                },
                iterations_saved=0,
            )

        return StuckDetectionResult(False, None, None, 0)

    @staticmethod
    def _calculate_text_similarity(text1: str, text2: str) -> float:
        """计算两段文本的 Jaccard 相似度"""
        if not text1 or not text2:
            return 0.0

        # 分词（简单按空格分割）
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        # Jaccard 相似度
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    async def record_stuck_detection(
        self,
        session_id: str,
        reason: str,
        iterations_saved: int,
    ) -> None:
        """
        记录停滞检测事件

        异常安全：任何 Redis / 指标异常均被吞掉。
        """
        if not self._enabled:
            return

        # 内存降级统计
        self._stuck_count[session_id] = self._stuck_count.get(session_id, 0) + 1

        # Prometheus 指标
        _init_metrics()
        if _STUCK_DETECTION_COUNTER is not None:
            _STUCK_DETECTION_COUNTER.labels(session_id=session_id, reason=reason).inc(1)
        if _STUCK_REASON_GAUGE is not None:
            _STUCK_REASON_GAUGE.labels(session_id=session_id).set(iterations_saved)

        # Redis 持久化（best-effort）
        try:
            now = datetime.now()
            pipe = redis_client.pipeline()

            # 会话维度停滞统计
            session_key = f"quant:metrics:agent:stuck:{session_id}:{now.date().isoformat()}"
            pipe.hincrby(session_key, reason, 1)
            pipe.hincrby(session_key, "total", 1)
            pipe.hincrby(session_key, "iterations_saved", iterations_saved)
            pipe.expire(session_key, _STUCK_TTL)

            # 全局维度停滞统计
            global_key = f"quant:metrics:agent:stuck:global:{now.date().isoformat()}"
            pipe.hincrby(global_key, reason, 1)
            pipe.hincrby(global_key, "total", 1)
            pipe.hincrby(global_key, "iterations_saved", iterations_saved)
            pipe.expire(global_key, _STUCK_TTL)

            await pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[RepetitionGuard] Redis 写入失败（已走内存降级）: {e}")

    async def get_stuck_stats(
        self,
        session_id: Optional[str] = None,
        d: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        查询停滞统计

        Args:
            session_id: 指定会话 ID（可选，不传则查询全局）
            d: 指定日期（可选，默认今日）

        Returns:
            {"total": int, "reasons": dict, "iterations_saved": int, "metric_source": str}
        """
        d = d or date.today()

        if session_id:
            # 会话维度
            key = f"quant:metrics:agent:stuck:{session_id}:{d.isoformat()}"
        else:
            # 全局维度
            key = f"quant:metrics:agent:stuck:global:{d.isoformat()}"

        try:
            raw = await redis_client.hgetall(key)
            if raw:
                return {
                    "session_id": session_id,
                    "date": d.isoformat(),
                    "total": int(raw.get("total", 0)),
                    "reasons": {
                        "identical_tool_calls": int(raw.get("identical_tool_calls", 0)),
                        "identical_outputs": int(raw.get("identical_outputs", 0)),
                        "no_progress": int(raw.get("no_progress", 0)),
                        "loop_pattern": int(raw.get("loop_pattern", 0)),
                    },
                    "iterations_saved": int(raw.get("iterations_saved", 0)),
                    "metric_source": "redis",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[RepetitionGuard] Redis 读取失败: {e}")

        # 内存降级
        return {
            "session_id": session_id,
            "date": d.isoformat(),
            "total": sum(self._stuck_count.values()) if not session_id else self._stuck_count.get(session_id, 0),
            "reasons": {},
            "iterations_saved": 0,
            "metric_source": "memory_fallback" if self._enabled else "disabled",
        }

    def reset(self) -> None:
        """重置检测状态（用于测试或新会话开始）"""
        self._call_history.clear()
        self._stuck_count.clear()


# 全局单例
repetition_guard = RepetitionGuard()
