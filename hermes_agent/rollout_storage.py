"""
AGENT-15 · 会话事件日志持久化（Rollout）

对标 openai/codex rollout.rs + compact*.rs 范式：
1. JSONL 追加写入 logs/sessions/{date}/{session_id}.jsonl
2. 首行 SessionMeta（session_id/model/创建时间），后续每行单条 Event
3. Budget 上限 → 自动归档到 archived/子目录
4. 冷启动时从 Rollout 重放恢复 SessionEventLog（双轨：Redis/PG + Rollout）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

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
    def from_comment_line(cls, line: str) -> cls:
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
