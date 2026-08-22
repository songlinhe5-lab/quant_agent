"""
AGENT-15: 会话事件日志持久化（Rollout）- 单元测试

验收标准：
1. 进程重启后事件日志可完整重放
2. Budget 超限走归档而非截断
3. 恢复幂等（多次恢复结果一致）
4. Cursor 分页查询正确
5. SessionMeta 首行写入/读取
6. 三轨冷启动恢复（Redis → PG → Rollout）
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_agent.event_log import (
    EVENT_TYPES,
    SessionEvent,
    SessionEventLog,
    check_invariant,
    derive_messages,
)
from hermes_agent.rollout_storage import (
    RolloutPage,
    RolloutStorage,
    SessionMeta,
    create_rollout_storage,
)


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    d = tempfile.mkdtemp(prefix="rollout_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def storage(temp_dir):
    """创建测试用 RolloutStorage"""
    return RolloutStorage(base_dir=temp_dir, budget_bytes=1024)  # 1KB budget for testing


class TestSessionMeta:
    """SessionMeta 测试"""

    def test_meta_creation(self):
        """测试元数据创建"""
        meta = SessionMeta(
            session_id="test-session",
            model="deepseek-v4-flash",
            created_at="2026-08-22T00:00:00Z",
            event_count=10,
        )
        assert meta.session_id == "test-session"
        assert meta.model == "deepseek-v4-flash"
        assert meta.event_count == 10

    def test_meta_to_comment_line(self):
        """测试元数据序列化为注释行"""
        meta = SessionMeta(
            session_id="test",
            model="model",
            created_at="2026-08-22",
        )
        line = meta.to_comment_line()
        assert line.startswith("# ")
        data = json.loads(line[2:])
        assert data["session_id"] == "test"

    def test_meta_from_comment_line(self):
        """测试从注释行反序列化"""
        line = '# {"session_id": "test", "model": "m", "created_at": "2026", "event_count": 5}'
        meta = SessionMeta.from_comment_line(line)
        assert meta.session_id == "test"
        assert meta.event_count == 5

    def test_meta_roundtrip(self):
        """测试序列化/反序列化往返"""
        original = SessionMeta(
            session_id="roundtrip",
            model="deepseek-v4-pro",
            created_at="2026-08-22T12:00:00Z",
            event_count=42,
        )
        line = original.to_comment_line()
        restored = SessionMeta.from_comment_line(line)
        assert restored.session_id == original.session_id
        assert restored.model == original.model
        assert restored.event_count == original.event_count


class TestRolloutStorage:
    """RolloutStorage 核心测试"""

    def test_storage_creation(self, storage, temp_dir):
        """测试存储创建"""
        assert storage.base_dir == Path(temp_dir)
        assert storage.budget_bytes == 1024

    def test_save_and_read_meta(self, storage):
        """测试 SessionMeta 写入和读取"""
        meta = SessionMeta(
            session_id="test-meta",
            model="test-model",
            created_at="2026-08-22",
        )
        storage.save_session_meta("test-meta", meta)

        # 读取
        loaded = storage.get_session_metadata("test-meta")
        assert loaded is not None
        assert loaded.session_id == "test-meta"
        assert loaded.model == "test-model"

    def test_save_meta_idempotent(self, storage):
        """测试 SessionMeta 写入幂等（不覆盖已有文件）"""
        meta1 = SessionMeta(session_id="idem", model="m1", created_at="t1")
        meta2 = SessionMeta(session_id="idem", model="m2", created_at="t2")

        storage.save_session_meta("idem", meta1)
        storage.save_session_meta("idem", meta2)  # 不应覆盖

        loaded = storage.get_session_metadata("idem")
        assert loaded.model == "m1"  # 保持第一次的值

    def test_append_and_load_events(self, storage):
        """测试事件追加和加载"""
        evt1 = SessionEvent(seq=1, ts=time.time(), type="user/message", payload={"content": "hello"})
        evt2 = SessionEvent(seq=2, ts=time.time(), type="assistant/message", payload={"content": "hi"})

        storage.append_event("test-events", evt1)
        storage.append_event("test-events", evt2)

        loaded = storage.load_events("test-events")
        assert len(loaded) == 2
        assert loaded[0].type == "user/message"
        assert loaded[1].type == "assistant/message"
        assert loaded[0].payload["content"] == "hello"

    def test_load_events_empty(self, storage):
        """测试加载不存在会话的事件"""
        loaded = storage.load_events("nonexistent")
        assert loaded == []

    def test_load_events_corrupt_line(self, storage):
        """测试损坏行容错"""
        path = storage._get_session_path("corrupt-test")

        # 手动写入一个损坏行
        with open(path, "w") as f:
            f.write('{"seq": 1, "ts": 1.0, "type": "user/message", "payload": {}}\n')
            f.write("this is not json\n")  # 损坏行
            f.write('{"seq": 3, "ts": 3.0, "type": "assistant/message", "payload": {}}\n')

        loaded = storage.load_events("corrupt-test")
        assert len(loaded) == 2  # 跳过损坏行


class TestBudgetAndArchive:
    """Budget 和归档测试"""

    def test_budget_check_under_limit(self, storage):
        """测试未超预算"""
        evt = SessionEvent(seq=1, ts=time.time(), type="user/message", payload={"content": "small"})
        storage.append_event("budget-test", evt)

        archived = storage.check_budget_and_archive("budget-test")
        assert archived is False  # 未超限

    def test_budget_check_over_limit(self, storage):
        """测试超预算触发归档"""
        # 写入大量事件超过 1KB budget
        for i in range(50):
            evt = SessionEvent(
                seq=i,
                ts=time.time(),
                type="user/message",
                payload={"content": f"event data {i} " * 10},  # 每条约 200 bytes
            )
            storage.append_event("archive-test", evt)

        archived = storage.check_budget_and_archive("archive-test")
        assert archived is True  # 应已归档

        # 归档后原文件应不存在
        original_path = storage._get_session_path("archive-test")
        assert not original_path.exists()

        # 归档目录应有文件
        archived_files = list(storage.archived_dir.glob("archive-test_*.jsonl"))
        assert len(archived_files) == 1


class TestCursorPagination:
    """Cursor 分页查询测试"""

    @pytest.fixture
    def populated_storage(self, storage):
        """创建包含多个事件的存储"""
        for i in range(20):
            evt = SessionEvent(
                seq=i,
                ts=time.time() + i,
                type="user/message" if i % 2 == 0 else "assistant/message",
                payload={"content": f"message {i}"},
            )
            storage.append_event("page-test", evt)
        return storage

    def test_forward_pagination_first_page(self, populated_storage):
        """测试向前翻页 - 第一页"""
        page = populated_storage.read_events_paginated("page-test", cursor=None, limit=5, direction="forward")
        assert len(page.events) == 5
        assert page.total_count == 20
        assert page.next_cursor == 5
        assert page.prev_cursor is None  # 第一页无 prev

    def test_forward_pagination_middle_page(self, populated_storage):
        """测试向前翻页 - 中间页"""
        page = populated_storage.read_events_paginated("page-test", cursor=10, limit=5, direction="forward")
        assert len(page.events) == 5
        assert page.next_cursor == 15
        assert page.prev_cursor == 5

    def test_forward_pagination_last_page(self, populated_storage):
        """测试向前翻页 - 最后一页"""
        page = populated_storage.read_events_paginated("page-test", cursor=18, limit=5, direction="forward")
        assert len(page.events) == 2  # 只剩 2 条
        assert page.next_cursor is None  # 无更多
        assert page.prev_cursor == 13

    def test_backward_pagination(self, populated_storage):
        """测试向后翻页"""
        page = populated_storage.read_events_paginated("page-test", cursor=None, limit=5, direction="backward")
        assert len(page.events) == 5
        assert page.total_count == 20

    def test_empty_session_pagination(self, storage):
        """测试空会话分页"""
        page = storage.read_events_paginated("empty", cursor=None, limit=10)
        assert len(page.events) == 0
        assert page.total_count == 0
        assert page.next_cursor is None


class TestListSessions:
    """会话列表测试"""

    def test_list_sessions_empty(self, storage):
        """测试空存储列表"""
        sessions = storage.list_sessions()
        assert sessions == []

    def test_list_sessions_with_data(self, storage):
        """测试有数据的列表"""
        # 创建几个会话
        for sid in ["session-a", "session-b"]:
            meta = SessionMeta(session_id=sid, model="test", created_at="2026-08-22")
            storage.save_session_meta(sid, meta)
            evt = SessionEvent(seq=0, ts=time.time(), type="user/message", payload={"content": "hi"})
            storage.append_event(sid, evt)

        sessions = storage.list_sessions()
        assert len(sessions) >= 2
        session_ids = {s.session_id for s in sessions}
        assert "session-a" in session_ids
        assert "session-b" in session_ids


class TestEventStats:
    """事件统计测试"""

    def test_stats_nonexistent(self, storage):
        """测试不存在会话的统计"""
        stats = storage.get_event_stats("nonexistent")
        assert stats["exists"] is False

    def test_stats_with_data(self, storage):
        """测试有数据的统计"""
        for i in range(5):
            evt = SessionEvent(
                seq=i,
                ts=time.time() + i,
                type="user/message" if i % 2 == 0 else "tool/call",
                payload={"content": f"msg {i}"},
            )
            storage.append_event("stats-test", evt)

        stats = storage.get_event_stats("stats-test")
        assert stats["exists"] is True
        assert stats["event_count"] == 5
        assert "user/message" in stats["type_distribution"]
        assert "tool/call" in stats["type_distribution"]
        assert stats["file_size_bytes"] > 0


class TestSessionEventLogWithRollout:
    """SessionEventLog + Rollout 集成测试"""

    def test_event_log_writes_to_rollout(self, temp_dir):
        """测试事件日志写入 Rollout"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="integration-test", rollout_storage=storage)

        log.record_user_message("hello")
        log.record_assistant_message("hi there")
        log.record_tool_call("call_1", "get_quote", '{"ticker": "AAPL"}')

        # 验证 Rollout 文件已写入
        loaded = storage.load_events("integration-test")
        assert len(loaded) == 3
        assert loaded[0].type == "user/message"
        assert loaded[1].type == "assistant/message"
        assert loaded[2].type == "tool/call"

    def test_load_from_rollout(self, temp_dir):
        """测试从 Rollout 恢复事件日志"""
        storage = RolloutStorage(base_dir=temp_dir)

        # 先写入一些事件
        log = SessionEventLog(session_id="restore-test", rollout_storage=storage)
        log.record_user_message("msg1")
        log.record_assistant_message("reply1")
        log.record_tool_call("c1", "tool_a", "{}")

        # 从 Rollout 恢复
        restored = SessionEventLog.load_from_rollout("restore-test", base_dir=temp_dir)
        assert len(restored) == 3
        assert restored.events[0].type == "user/message"

    def test_derive_messages_from_rollout(self, temp_dir):
        """测试从 Rollout 恢复后投影消息"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="derive-test", rollout_storage=storage)

        log.record_user_message("what is AAPL price?")
        log.record_tool_call("c1", "get_quote", '{"ticker": "AAPL"}')
        log.record_tool_result("c1", "get_quote", '{"price": 150}')
        log.record_assistant_message("AAPL is $150")

        # 恢复并投影
        restored = SessionEventLog.load_from_rollout("derive-test", base_dir=temp_dir)
        messages = derive_messages(restored)

        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"  # tool_call → assistant with tool_calls
        assert messages[2]["role"] == "tool"
        assert messages[3]["role"] == "assistant"

    def test_recovery_idempotent(self, temp_dir):
        """测试恢复幂等（多次恢复结果一致）"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="idempotent-test", rollout_storage=storage)
        log.record_user_message("test")
        log.record_assistant_message("reply")

        # 多次恢复
        r1 = SessionEventLog.load_from_rollout("idempotent-test", base_dir=temp_dir)
        r2 = SessionEventLog.load_from_rollout("idempotent-test", base_dir=temp_dir)
        r3 = SessionEventLog.load_from_rollout("idempotent-test", base_dir=temp_dir)

        assert len(r1) == len(r2) == len(r3)
        assert r1.events[0].type == r2.events[0].type == r3.events[0].type


class TestCheckInvariant:
    """不变量检查测试"""

    def test_invariant_holds(self, temp_dir):
        """测试不变量成立"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="invariant-test", rollout_storage=storage)

        log.record_user_message("hello")
        log.record_assistant_message("hi")

        messages = derive_messages(log)
        assert check_invariant(log, messages) is True

    def test_invariant_with_extra_messages(self, temp_dir):
        """测试窗口是投影后缀时不变量仍成立（压缩场景）"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="inv-compress", rollout_storage=storage)

        log.record_user_message("msg1")
        log.record_user_message("msg2")
        log.record_assistant_message("reply")

        # 窗口只包含最后两条（压缩后场景）
        window = [
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply"},
        ]
        assert check_invariant(log, window) is True


class TestCreateRolloutStorage:
    """Factory 函数测试"""

    def test_create_default(self):
        """测试默认创建"""
        storage = create_rollout_storage()
        assert storage.budget_bytes == 10485760  # 10MB

    @patch.dict(os.environ, {"ROLLOUT_BUDGET_BYTES": "5242880"})
    def test_create_with_env(self):
        """测试环境变量配置"""
        storage = create_rollout_storage()
        assert storage.budget_bytes == 5242880  # 5MB


class TestRolloutPage:
    """RolloutPage 序列化测试"""

    def test_page_to_dict(self):
        """测试分页结果序列化"""
        events = [
            SessionEvent(seq=0, ts=1.0, type="user/message", payload={"content": "hi"}),
        ]
        meta = SessionMeta(session_id="test", model="m", created_at="t")
        page = RolloutPage(
            events=events,
            total_count=10,
            next_cursor=5,
            prev_cursor=None,
            session_meta=meta,
        )
        d = page.to_dict()
        assert d["total_count"] == 10
        assert d["next_cursor"] == 5
        assert d["prev_cursor"] is None
        assert d["session_meta"]["session_id"] == "test"
        assert len(d["events"]) == 1


class TestEventTypes:
    """事件类型闭集测试"""

    def test_event_types_frozen(self):
        """测试事件类型闭集"""
        assert "user/message" in EVENT_TYPES
        assert "assistant/message" in EVENT_TYPES
        assert "tool/call" in EVENT_TYPES
        assert "tool/result" in EVENT_TYPES
        assert "turn/start" in EVENT_TYPES
        assert "turn/end" in EVENT_TYPES
        assert "memory/compress" in EVENT_TYPES
        assert "approval/asked" in EVENT_TYPES

    def test_invalid_type_still_recorded(self, temp_dir):
        """测试未知类型事件仍被记录（宽容写入）"""
        storage = RolloutStorage(base_dir=temp_dir)
        log = SessionEventLog(session_id="invalid-type", rollout_storage=storage)

        evt = log.append("unknown/type", {"data": "test"})
        assert evt.payload.get("_invalid_type") is True
        assert len(log) == 1
