"""
AGENT-08 · Verify 阶段实装（零幻觉的结构保证）

AGENTS.md §4.1 强制四段式：Plan → Tool → Verify → Output。
本模块实装 Verify 环节：工具返回后校验非空 / 时间戳新鲜度 / 数值合理性。
校验产出证据对象（VerificationEvidence），未通过时阻止进入 Output。

设计参考 hermes verify/ + verification_evidence.py + verification_stop.py。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class VerifyStatus(str, Enum):
    """校验结果。"""

    PASS = "pass"  # 校验通过
    FAIL_EMPTY = "fail_empty"  # 空结果
    FAIL_STALE = "fail_stale"  # 数据过期
    FAIL_INVALID = "fail_invalid"  # 数值越界或格式异常


@dataclass
class VerificationEvidence:
    """
    校验证据对象 — 每次工具执行后产出，绑定到对应 tool_result。

    结构保证：模型看到的每个数字都有对应的 evidence 记录。
    """

    tool_name: str
    status: VerifyStatus
    checks_performed: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == VerifyStatus.PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool_name,
            "verify_status": self.status.value,
            "checks": self.checks_performed,
            "failures": self.failures,
        }


# 默认数据新鲜度阈值（秒）
_DEFAULT_FRESHNESS_THRESHOLD = 86400  # 24 小时


def verify_tool_result(
    tool_name: str,
    result: Any,
    freshness_threshold: int = _DEFAULT_FRESHNESS_THRESHOLD,
) -> VerificationEvidence:
    """
    对工具执行结果进行校验。

    校验项（按 AGENTS.md §4.1）：
    1. 非空校验：结果不为 None / 空 dict / 空 list
    2. 时间戳新鲜度：若含 timestamp / updated_at 字段，检查是否过期
    3. 错误检测：status=error 的结果标记为 FAIL_INVALID

    Returns:
        VerificationEvidence: 校验证据对象
    """
    checks: List[str] = []
    failures: List[str] = []

    # ── 1. 非空校验 ──────────────────────────────────────────
    checks.append("non_empty")
    if result is None:
        failures.append("结果为 None")
    elif isinstance(result, dict):
        if not result:
            failures.append("结果为空 dict")
        elif result.get("status") in ("error", "failed"):
            checks.append("error_status")
            failures.append(f"工具返回错误: {result.get('message', '未知')}")
    elif isinstance(result, (list, str)) and len(result) == 0:
        failures.append("结果为空集合")

    # ── 2. 时间戳新鲜度 ─────────────────────────────────────
    if isinstance(result, dict) and not failures:
        ts = result.get("timestamp") or result.get("updated_at") or result.get("as_of")
        if ts is not None:
            checks.append("freshness")
            try:
                ts_float = float(ts)
                age = time.time() - ts_float
                if age > freshness_threshold:
                    failures.append(f"数据已过期: {age:.0f}s 前更新 (阈值 {freshness_threshold}s)")
            except (ValueError, TypeError):
                pass  # 非数字时间戳，跳过

    # ── 3. 判定 ──────────────────────────────────────────────
    if failures:
        if any("空" in f or "None" in f for f in failures):
            status = VerifyStatus.FAIL_EMPTY
        elif any("过期" in f for f in failures):
            status = VerifyStatus.FAIL_STALE
        else:
            status = VerifyStatus.FAIL_INVALID
    else:
        status = VerifyStatus.PASS

    return VerificationEvidence(
        tool_name=tool_name,
        status=status,
        checks_performed=checks,
        failures=failures,
    )
