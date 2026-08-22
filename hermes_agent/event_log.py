"""
AGENT-01 · 会话事件日志（append-only）+「模型可见即已记录」不变量

AGENTS.md §3 要求每个数字可溯源到具体 Tool 返回。现状（S6）：
_save_session 整体覆盖 Redis + PG 破坏性 upsert，_compress_memory / _heal_memory
原地改写 self.messages → 事后无法重建"模型当时看到了什么"。

本模块借鉴 dsh core/session + subsystems/{session-projection,invariants}.md：
1. SessionEventLog  — append-only 事件日志（只追加，永不改写）
2. derive_messages  — 投影函数：从事件日志派生模型可见消息列表
3. check_invariant  — 运行时不变量：到达模型请求的消息必须可从日志重建

核心原则（dsh 原话）：
"Anything that reaches a model request must be reconstructable from the log."
压缩只影响投影，不删事件。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# AGENT-15: 延迟加载 RolloutStorage（避免循环导入）
def _import_rollout():
    from hermes_agent.rollout_storage import RolloutStorage, SessionEvent, create_rollout_storage

    return RolloutStorage, create_rollout_storage, SessionEvent


# ── 事件类型闭集 ────────────────────────────────────────────────────
# user/message    — 用户输入（含系统注入的校验/强制指令）
# assistant/message — 助手完整回复（turn 结束时定稿）
# tool/call       — 工具调用发起（name + arguments + call_id）
# tool/result     — 工具返回（call_id + result 摘要）
# turn/start      — ReAct 轮次开始
# turn/end        — ReAct 轮次结束（含最终内容长度）
# memory/compress — 压缩发生（只记事件，事件日志本身不被压缩）
# memory/heal     — 记忆自愈发生
# approval/asked  — 审批请求（AGENT-07 预留）
# approval/decided — 审批决策（AGENT-07 预留）
EVENT_TYPES = frozenset(
    {
        "user/message",
        "assistant/message",
        "tool/call",
        "tool/result",
        "turn/start",
        "turn/end",
        "memory/compress",
        "memory/heal",
        "approval/asked",
        "approval/decided",
    }
)


@dataclass
class SessionEvent:
    """单条会话事件（不可变语义：append 后不得修改）。"""

    seq: int
    ts: float
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"seq": self.seq, "ts": self.ts, "type": self.type, "payload": self.payload}


class SessionEventLog:
    """
    append-only 会话事件日志。

    - append() 只追加；不提供修改/删除单条事件的接口
    - reset() 仅在 /clear（用户显式清空会话）时允许，且自身作为事件留痕
    - derive_messages() 从事件派生模型可见消息（投影）

    AGENT-15: 新增 RolloutStorage 持久化层（JSONL 追加文件）
    """

    def __init__(self, session_id: str = "", rollout_storage: Optional["RolloutStorage"] = None):
        self.session_id = session_id
        self._events: List[SessionEvent] = []
        self._seq = 0

        # AGENT-15: Rollout 持久化层（可选注入，便于测试）
        _RolloutStorage, _, _ = _import_rollout()
        if rollout_storage is None and session_id:
            self.rollout = _RolloutStorage()  # 默认创建实例
        else:
            self.rollout = rollout_storage

    # ── 追加 ────────────────────────────────────────────────────────
    def append(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> SessionEvent:
        """追加一条事件。未知类型仍会记录（宽容写入），但标记 invalid_type。

        AGENT-15: 同时写入内存和 RolloutStorage
        """
        if event_type not in EVENT_TYPES:
            payload = dict(payload or {})
            payload["_invalid_type"] = True
        self._seq += 1
        evt = SessionEvent(seq=self._seq, ts=time.time(), type=event_type, payload=payload or {})
        self._events.append(evt)

        # AGENT-15: 持久化到 Rollout（幂等：session_id 非空时才写）
        if self.rollout and self.session_id:
            try:
                self.rollout.append_event(self.session_id, evt)
                # Budget 检查：每次追加后检查（避免单文件过大）
                self.rollout.check_budget_and_archive(self.session_id)
            except Exception as e:
                print(f"⚠️ [SessionEventLog] Rollout 持久化失败：{e}")

        return evt

    def record_user_message(self, content: str) -> SessionEvent:
        return self.append("user/message", {"content": content})

    def record_assistant_message(self, content: str) -> SessionEvent:
        return self.append("assistant/message", {"content": content})

    def record_tool_call(self, call_id: str, name: str, arguments: str) -> SessionEvent:
        return self.append("tool/call", {"call_id": call_id, "name": name, "arguments": arguments})

    def record_tool_result(self, call_id: str, name: str, content: str, turn_id: str = "") -> SessionEvent:
        """记录工具返回（AGENT-17: 携带 turn_id 便于按轮次归组）"""
        payload = {"call_id": call_id, "name": name, "content": content}
        if turn_id:
            payload["turn_id"] = turn_id
        return self.append("tool/result", payload)

    def record_turn_start(
        self,
        iteration: int,
        turn_id: str = "",
        model: str = "",
        parent_turn_id: str = "",
        root_turn_id: str = "",
    ) -> SessionEvent:
        """记录 ReAct 轮次开始（AGENT-17: 携带 turn_id + 血缘字段）"""
        payload: Dict[str, Any] = {"iteration": iteration}
        if turn_id:
            payload["turn_id"] = turn_id
        if model:
            payload["model"] = model
        # AGENT-14 血缘预留
        if parent_turn_id:
            payload["parent_turn_id"] = parent_turn_id
        if root_turn_id:
            payload["root_turn_id"] = root_turn_id
        return self.append("turn/start", payload)

    def record_turn_end(
        self,
        iteration: int,
        content_len: int = 0,
        turn_id: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        inference_ms: float = 0.0,
        tool_ms: float = 0.0,
        save_ms: float = 0.0,
    ) -> SessionEvent:
        """记录 ReAct 轮次结束（AGENT-17: 携带完整计时分解）"""
        payload: Dict[str, Any] = {"iteration": iteration, "content_len": content_len}
        if turn_id:
            payload["turn_id"] = turn_id
        if prompt_tokens:
            payload["prompt_tokens"] = prompt_tokens
        if completion_tokens:
            payload["completion_tokens"] = completion_tokens
        # 延迟分解（毫秒）
        if inference_ms or tool_ms or save_ms:
            payload["latency"] = {
                "inference_ms": round(inference_ms, 2),
                "tool_ms": round(tool_ms, 2),
                "save_ms": round(save_ms, 2),
            }
        return self.append("turn/end", payload)

    def record_memory_op(self, op: str, detail: str = "") -> SessionEvent:
        """记录 memory/compress 或 memory/heal（压缩不改事件日志本身）。"""
        etype = f"memory/{op}" if f"memory/{op}" in EVENT_TYPES else "memory/compress"
        return self.append(etype, {"detail": detail})

    # ── 读取 ────────────────────────────────────────────────────────
    @property
    def events(self) -> List[SessionEvent]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def reset(self) -> None:
        """用户显式 /clear 时重置（保留审计语义：调用方应先记录清空事件）。"""
        self._events = []
        self._seq = 0

    # ── AGENT-15: Rollout 持久化相关 ───────────────────────────────────────

    @classmethod
    def load_from_rollout(cls, session_id: str, base_dir: Optional[str] = None) -> "SessionEventLog":
        """
        从 Rollout 加载事件日志（冷启动恢复）。

        Args:
            session_id: 会话 ID
            base_dir: Rollout 存储根目录（None=默认 logs/sessions）
        Returns:
            重放后的 SessionEventLog 实例
        """
        _RolloutStorage, _, SessionEvent = _import_rollout()
        storage = _RolloutStorage(base_dir=base_dir) if base_dir else _RolloutStorage()
        events = storage.load_events(session_id)

        # 创建新的 SessionEventLog 实例（不触发 Rollout 写入）
        log = cls(session_id=session_id, rollout_storage=None)
        log._events = events
        log._seq = len(events)

        print(f"✅ [SessionEventLog] 从 Rollout 恢复 {len(events)} 条事件 (session={session_id})")
        return log


# ── 投影函数 ────────────────────────────────────────────────────────


def derive_messages(event_log: SessionEventLog) -> List[Dict[str, Any]]:
    """
    从 append-only 事件日志投影出模型可见消息序列。

    投影规则（按事件序）：
    - user/message      → {"role": "user", "content": ...}
    - assistant/message → {"role": "assistant", "content": ...}
    - tool/call         → 累积为 assistant 消息的 tool_calls（同一 turn 内连续 call 合并）
    - tool/result       → {"role": "tool", "tool_call_id": ..., "name": ..., "content": ...}

    压缩 / 自愈只影响运行时的 self.messages 窗口，不影响事件日志；
    需要重建"当时模型看到了什么"时重放本投影即可。
    """
    messages: List[Dict[str, Any]] = []
    pending_calls: List[Dict[str, Any]] = []

    def flush_pending_calls():
        nonlocal pending_calls
        if pending_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": c["call_id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"]},
                        }
                        for c in pending_calls
                    ],
                }
            )
            pending_calls = []

    for evt in event_log.events:
        p = evt.payload
        if evt.type == "user/message":
            flush_pending_calls()
            messages.append({"role": "user", "content": p.get("content", "")})
        elif evt.type == "assistant/message":
            flush_pending_calls()
            messages.append({"role": "assistant", "content": p.get("content", "")})
        elif evt.type == "tool/call":
            pending_calls.append(
                {"call_id": p.get("call_id", ""), "name": p.get("name", ""), "arguments": p.get("arguments", "")}
            )
        elif evt.type == "tool/result":
            flush_pending_calls()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": p.get("call_id", ""),
                    "name": p.get("name", ""),
                    "content": p.get("content", ""),
                }
            )
        # turn/* 与 memory/* 事件不参与消息投影（仅审计）

    flush_pending_calls()
    return messages


# ── 运行时不变量 ────────────────────────────────────────────────────


def check_invariant(event_log: SessionEventLog, messages: List[Dict[str, Any]]) -> bool:
    """
    「模型可见即已记录」不变量（dsh invariants.md）：
    当前上下文窗口中的每条 user / assistant / tool 消息，
    必须能在事件日志投影中找到对应记录（按角色+内容匹配）。

    压缩会裁掉旧消息 → 窗口是投影的后缀子集，故用包含关系校验。
    Returns True = 不变量成立；False = 存在模型可见但日志未记录的消息。
    """
    projected = derive_messages(event_log)

    def _key(m: Dict[str, Any]) -> tuple:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            ids = tuple(tc.get("id") for tc in m.get("tool_calls", []))
            return ("assistant_tool_calls", ids)
        return (role, str(m.get("content") or "")[:500])

    projected_keys = {_key(m) for m in projected}
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue  # system prompt 由代码注入，不经事件日志
        if _key(m) not in projected_keys:
            return False
    return True
