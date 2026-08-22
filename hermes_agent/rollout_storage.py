"""
AGENT-15 · 会话事件日志持久化（Rollout）

对标 openai/codex rollout.rs + compact*.rs 范式：
1. JSONL 追加写入 logs/sessions/{date}/{session_id}.jsonl
2. 首行 SessionMeta（session_id/model/创建时间），后续每行单条 Event
3. Budget 上限 → 自动归档到 archived/子目录
4. 冷启动时从 Rollout 重放恢复 SessionEventLog（双轨：Redis/PG + Rollout）
5. Cursor 分页查询（向前/向后翻页）+ 截断策略
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_agent.event_log import SessionEvent


@dataclass
class SessionMeta:
    """会话元数据（写入 Rollout 首行，JSON 对象 + `#`注释标记）"""

    session_id: str
    model: str
    created_at: str  # ISO8601
    event_count: int = 0

    def to_comment_line(self) -> str:
        return f"# {json.dumps({'session_id': self.session_id, 'model': self.model, 'created_at': self.created_at, 'event_count': self.event_count}, ensure_ascii=False)}"

    @classmethod
    def from_comment_line(cls, line: str) -> RolloutStorage:
        data = json.loads(line[2:].strip())  # 去掉 '# '
        return cls(
            session_id=data["session_id"],
            model=data["model"],
            created_at=data["created_at"],
            event_count=data.get("event_count", 0),
        )


class RolloutStorage:
    """
    Rollout 持久化层（JSONL 追加文件）。

    路径规范：
      logs/sessions/{date}/{session_id}.jsonl       - 当前会话
      logs/sessions/{date}/archived/{session_id}_yyyy-mm-dd_HHMMSS.jsonl  - 归档
    """

    def __init__(
        self,
        base_dir: str = "logs/sessions",
        budget_bytes: int = 10 * 1024 * 1024,  # 默认 10MB per session file
    ):
        self.base_dir = Path(base_dir)
        self.budget_bytes = budget_bytes
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 按日期划分子目录
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.current_dir = self.base_dir / today
        self.current_dir.mkdir(parents=True, exist_ok=True)

        # 归档目录
        self.archived_dir = self.current_dir / "archived"
        self.archived_dir.mkdir(exist_ok=True)

    def _get_session_path(self, session_id: str) -> Path:
        """获取当前会话的 Rollout 文件路径"""
        return self.current_dir / f"{session_id}.jsonl"

    def _get_archived_prefix(self) -> str:
        """获取归档文件的日期前缀"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d_")

    def save_session_meta(self, session_id: str, meta: SessionMeta):
        """写入会话元数据（首行注释）"""
        path = self._get_session_path(session_id)

        # 检查文件是否存在，若存在则不覆盖（幂等）
        if path.exists():
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write(meta.to_comment_line() + "\n")

    def append_event(self, session_id: str, event: SessionEvent):
        """追加单条事件（JSONL 格式）"""
        path = self._get_session_path(session_id)

        # 格式化 JSON（确保 UTF-8，支持中文）
        event_dict = event.to_dict()
        json_line = json.dumps(event_dict, ensure_ascii=False) + "\n"

        with open(path, "a", encoding="utf-8") as f:
            f.write(json_line)

    def load_events(self, session_id: str) -> List[SessionEvent]:
        """
        从 Rollout 加载所有事件（用于冷启动恢复）。

        Returns:
            事件列表（不含 SessionMeta 行）
        """
        path = self._get_session_path(session_id)
        if not path.exists():
            return []

        events: List[SessionEvent] = []
        seq = 0

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue  # 跳过空行和 Meta 行

                try:
                    data = json.loads(line)
                    evt = SessionEvent(
                        seq=seq,
                        ts=data["ts"],
                        type=data["type"],
                        payload=data.get("payload", {}),
                    )
                    events.append(evt)
                    seq += 1
                except (json.JSONDecodeError, KeyError) as e:
                    # 容错：损坏行跳过并记录日志
                    print(f"⚠️ [RolloutStorage] 跳过损坏事件行 (session={session_id}, seq={seq}): {e}")
                    continue

        return events

    def check_budget_and_archive(self, session_id: str) -> bool:
        """
        检查预算超限，若超限则归档当前文件（不移除，仅移动）。

        Returns:
            True 已归档，False 未超限
        """
        path = self._get_session_path(session_id)
        if not path.exists():
            return False

        file_size = path.stat().st_size
        if file_size < self.budget_bytes:
            return False

        # 归档：生成新文件名（带时间戳）
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archived_name = f"{session_id}_{timestamp}.jsonl"
        archived_path = self.archived_dir / archived_name

        # 移动文件
        path.rename(archived_path)

        # 更新 SessionMeta 的 event_count
        # （简化版：这里不更新，因为归档后不再读取该文件）

        print(f"✅ [RolloutStorage] 会话已归档 (budget exceeded): {path.name} → {archived_name}")
        return True

    def get_session_metadata(self, session_id: str) -> Optional[SessionMeta]:
        """读取会话元数据（从首行）"""
        path = self._get_session_path(session_id)
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line.startswith("#"):
                return None

            try:
                return SessionMeta.from_comment_line(first_line)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️ [RolloutStorage] 解析元数据失败 (session={session_id}): {e}")
                return None


def create_rollout_storage() -> RolloutStorage:
    """Factory 函数：创建 RolloutStorage 实例（可配置参数）"""
    budget = os.environ.get("ROLLOUT_BUDGET_BYTES", "10485760")  # 默认 10MB
    return RolloutStorage(budget_bytes=int(budget))


# ========================================================================
# AGENT-15: Cursor 分页查询 + 截断策略
# ========================================================================


@dataclass
class RolloutPage:
    """分页查询结果"""

    events: List[SessionEvent]
    total_count: int  # 该会话总事件数
    next_cursor: Optional[int]  # 下一页起始 seq（None=无更多）
    prev_cursor: Optional[int]  # 上一页起始 seq（None=无更多）
    session_meta: Optional[SessionMeta] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "total_count": self.total_count,
            "next_cursor": self.next_cursor,
            "prev_cursor": self.prev_cursor,
            "session_meta": (
                {
                    "session_id": self.session_meta.session_id,
                    "model": self.session_meta.model,
                    "created_at": self.session_meta.created_at,
                    "event_count": self.session_meta.event_count,
                }
                if self.session_meta
                else None
            ),
        }


@dataclass
class SessionSummary:
    """会话摘要（list_sessions 返回项）"""

    session_id: str
    date: str  # 目录日期
    model: str
    created_at: str
    event_count: int
    file_size_bytes: int
    file_path: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "date": self.date,
            "model": self.model,
            "created_at": self.created_at,
            "event_count": self.event_count,
            "file_size_bytes": self.file_size_bytes,
            "file_path": self.file_path,
        }


# 扩展 RolloutStorage 方法（通过 monkey-patch 避免循环导入）
def _rollout_read_events_paginated(
    self,
    session_id: str,
    cursor: Optional[int] = None,
    limit: int = 50,
    direction: str = "forward",
) -> RolloutPage:
    """
    Cursor 分页查询事件。

    Args:
        session_id: 会话 ID
        cursor: 起始 seq（None=从头/尾开始）
        limit: 每页事件数（默认 50）
        direction: "forward"（向后）或 "backward"（向前）

    Returns:
        RolloutPage: 分页结果
    """
    all_events = self.load_events(session_id)
    total = len(all_events)

    if total == 0:
        return RolloutPage(
            events=[],
            total_count=0,
            next_cursor=None,
            prev_cursor=None,
            session_meta=self.get_session_metadata(session_id),
        )

    if direction == "forward":
        start = cursor if cursor is not None else 0
        end = min(start + limit, total)
        page_events = all_events[start:end]
        next_cursor = end if end < total else None
        prev_cursor = max(0, start - limit) if start > 0 else None
    else:  # backward
        end = cursor if cursor is not None else total
        start = max(end - limit, 0)
        page_events = all_events[start:end]
        next_cursor = end if end < total else None
        prev_cursor = max(0, start - limit) if start > 0 else None

    return RolloutPage(
        events=page_events,
        total_count=total,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        session_meta=self.get_session_metadata(session_id),
    )


def _rollout_list_sessions(self, limit: int = 20) -> List[SessionSummary]:
    """
    列出最近的会话（按日期倒序）。

    Args:
        limit: 最大返回数

    Returns:
        SessionSummary 列表
    """
    sessions: List[SessionSummary] = []

    # 遍历日期子目录
    if not self.base_dir.exists():
        return []

    date_dirs = sorted(
        [d for d in self.base_dir.iterdir() if d.is_dir() and d.name != "archived"],
        reverse=True,  # 最新日期在前
    )

    for date_dir in date_dirs:
        date_str = date_dir.name
        for jsonl_file in date_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            meta = self.get_session_metadata(session_id)
            file_size = jsonl_file.stat().st_size

            sessions.append(
                SessionSummary(
                    session_id=session_id,
                    date=date_str,
                    model=meta.model if meta else "unknown",
                    created_at=meta.created_at if meta else "",
                    event_count=meta.event_count if meta else 0,
                    file_size_bytes=file_size,
                    file_path=str(jsonl_file),
                )
            )

            if len(sessions) >= limit:
                return sessions

    return sessions


def _rollout_get_event_stats(self, session_id: str) -> Dict[str, Any]:
    """
    获取会话事件统计信息。

    Returns:
        统计字典（事件数/类型分布/文件大小/时间范围）
    """
    path = self._get_session_path(session_id)
    if not path.exists():
        return {"exists": False}

    events = self.load_events(session_id)
    file_size = path.stat().st_size

    # 事件类型分布
    type_counts: Dict[str, int] = {}
    for evt in events:
        type_counts[evt.type] = type_counts.get(evt.type, 0) + 1

    # 时间范围
    ts_range = (events[0].ts, events[-1].ts) if events else (0, 0)

    return {
        "exists": True,
        "event_count": len(events),
        "file_size_bytes": file_size,
        "type_distribution": type_counts,
        "time_range": {"first": ts_range[0], "last": ts_range[1]},
        "meta": self.get_session_metadata(session_id),
    }


# 挂载到 RolloutStorage 类
RolloutStorage.read_events_paginated = _rollout_read_events_paginated
RolloutStorage.list_sessions = _rollout_list_sessions
RolloutStorage.get_event_stats = _rollout_get_event_stats
