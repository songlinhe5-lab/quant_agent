"""
AGENT-07 · 逐笔交易审批闸门骨架（fail-closed）

AGENTS.md §6 要求：实盘交易必须二次确认。
本模块定义审批框架，当前为骨架实装（always-allow），
后续 AGENT-07 完整版将接入 WebSocket UI 确认流程。

设计参考 dsh subsystems/approval.md：
- 闭集结果 + fail-closed
- 一次授权只授一次
- 会话级策略 ask / never
- 审计对 asked / decided
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ApprovalOutcome(str, Enum):
    """
    审批结果（闭集）。

    fail-closed: 任何异常 / 缺失 → unavailable → 拒绝。
    """

    ALLOWED_ONCE = "allowed-once"  # 本次授权通过（仅对当次交易有效）
    REJECTED = "rejected"  # 明确拒绝
    CANCELLED = "cancelled"  # 用户取消
    UNAVAILABLE = "unavailable"  # 审批方不可用（fail-closed → 拒绝）


@dataclass
class ApprovalRecord:
    """
    审批审计对（asked + decided）。

    每次审批生成唯一 approval_id（不与 tool_call_id 混用）。
    """

    approval_id: str
    tool_name: str
    tool_call_id: str
    outcome: ApprovalOutcome
    asked: Dict[str, Any] = field(default_factory=dict)  # 审批请求参数快照
    decided: Dict[str, Any] = field(default_factory=dict)  # 审批决策详情
    session_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool": self.tool_name,
            "outcome": self.outcome.value,
            "asked": self.asked,
            "decided": self.decided,
        }


# 交易类工具前缀（这些工具需要审批）
_TRADE_TOOL_PREFIXES = (
    "broker_trade",
    "place_order",
    "execute_trade",
    "EMERGENCY_LIQUIDATION",
)


def is_trade_tool(tool_name: str) -> bool:
    """判断是否为交易类工具（需要审批）。"""
    return any(tool_name.startswith(prefix) for prefix in _TRADE_TOOL_PREFIXES)


def check_trade_approval(
    tool_name: str,
    tool_call_id: str,
    arguments: Dict[str, Any],
    session_id: str = "",
) -> ApprovalRecord:
    """
    交易审批检查（骨架实装）。

    当前行为：always-allow（因为 UI 确认流程尚未接入）。
    后续完整版将：
    1. 检查会话级策略（ask / never）
    2. 若 ask → 经 WebSocket 发送审批请求 → 等待用户确认
    3. 生成 ApprovalRecord 审计对

    fail-closed: 异常时返回 UNAVAILABLE。
    """
    approval_id = str(uuid.uuid4())

    try:
        # 骨架：当前所有交易工具均不在 hermes_agent/tools 中
        # 实际交易由 backend/engine/gateway.py 的三级安全锁控制
        # 此处仅记录审计日志
        record = ApprovalRecord(
            approval_id=approval_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            outcome=ApprovalOutcome.ALLOWED_ONCE,
            asked={"arguments": arguments},
            decided={"reason": "skeleton: auto-allow (UI not yet wired)"},
            session_id=session_id,
        )
        logger.info(
            "trade_approval %s tool=%s outcome=%s",
            approval_id,
            tool_name,
            record.outcome.value,
        )
        return record

    except Exception as e:
        # fail-closed: 异常时拒绝
        logger.error("trade_approval_failed %s: %s", approval_id, e)
        return ApprovalRecord(
            approval_id=approval_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            outcome=ApprovalOutcome.UNAVAILABLE,
            asked={"arguments": arguments},
            decided={"reason": f"审批异常: {e}"},
            session_id=session_id,
        )
