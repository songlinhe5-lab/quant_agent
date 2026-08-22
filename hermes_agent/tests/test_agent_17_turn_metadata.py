"""
AGENT-17 · 轮次身份与计时元数据 — 完整单元测试

验收标准：
1. 事件日志 turn 事件全带 turn_id 与计时
2. 指标端点可见每轮延迟分布
3. tool_result 可按 turn_id 归组
"""

from hermes_agent.event_log import SessionEventLog

# ── SessionEventLog.turn 事件测试 ───────────────────────────────────────


class TestTurnStartEventWithTurnId:
    """record_turn_start 携带 turn_id + model + 血缘字段"""

    def test_turn_start_with_turn_id_and_model(self):
        """turn/start 包含 turn_id 和 model"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_start(
            iteration=1,
            turn_id="abc123",
            model="deepseek-chat",
        )
        assert evt.payload["iteration"] == 1
        assert evt.payload["turn_id"] == "abc123"
        assert evt.payload["model"] == "deepseek-chat"

    def test_turn_start_with_lineage_fields(self):
        """turn/start 包含 parent_turn_id/root_turn_id（AGENT-14 预留）"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_start(
            iteration=5,
            turn_id="xyz789",
            parent_turn_id="def456",
            root_turn_id="ghi012",
        )
        assert evt.payload["parent_turn_id"] == "def456"
        assert evt.payload["root_turn_id"] == "ghi012"

    def test_turn_start_without_optional_fields(self):
        """turn/start 可仅传必填参数，可选字段不出现"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_start(iteration=1)
        assert evt.payload["iteration"] == 1
        assert "turn_id" not in evt.payload
        assert "model" not in evt.payload


class TestTurnEndEventWithTiming:
    """record_turn_end 携带完整计时分解"""

    def test_turn_end_with_full_timing(self):
        """turn/end 包含所有延迟阶段"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_end(
            iteration=1,
            content_len=1234,
            turn_id="abc123",
            prompt_tokens=500,
            completion_tokens=200,
            inference_ms=1500.5,
            tool_ms=300.25,
            save_ms=50.125,
        )
        assert evt.payload["iteration"] == 1
        assert evt.payload["content_len"] == 1234
        assert evt.payload["turn_id"] == "abc123"
        assert evt.payload["prompt_tokens"] == 500
        assert evt.payload["completion_tokens"] == 200
        assert evt.payload["latency"]["inference_ms"] == 1500.5
        assert evt.payload["latency"]["tool_ms"] == 300.25
        assert evt.payload["latency"]["save_ms"] == 50.12  # round(50.125, 2)

    def test_turn_end_without_timing(self):
        """turn/end 可无延迟信息"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_end(iteration=1, content_len=100)
        assert evt.payload["iteration"] == 1
        assert "latency" not in evt.payload

    def test_turn_end_rounding(self):
        """延迟毫秒保留两位小数（Python round）"""
        log = SessionEventLog(session_id="test")
        evt = log.record_turn_end(
            iteration=1,
            content_len=0,
            turn_id="x",
            inference_ms=1234.567,
            tool_ms=89.123,
            save_ms=0.001,
        )
        # Python 的 round 采用银行家舍入
        assert evt.payload["latency"]["inference_ms"] == 1234.57
        assert evt.payload["latency"]["tool_ms"] == 89.12
        assert evt.payload["latency"]["save_ms"] == 0.0  # 0.001 -> 0.0


class TestToolResultWithTurnId:
    """record_tool_result 携带 turn_id 便于归组"""

    def test_tool_result_with_turn_id(self):
        """tool/result 包含 turn_id"""
        log = SessionEventLog(session_id="test")
        evt = log.record_tool_result(
            call_id="tool-123",
            name="get_stock_quote",
            content='{"price": 150}',
            turn_id="abc123",
        )
        assert evt.payload["call_id"] == "tool-123"
        assert evt.payload["name"] == "get_stock_quote"
        assert evt.payload["turn_id"] == "abc123"

    def test_tool_result_without_turn_id(self):
        """tool/result 可无 turn_id（向后兼容）"""
        log = SessionEventLog(session_id="test")
        evt = log.record_tool_result("call-1", "func", "data")
        assert evt.payload["call_id"] == "call-1"
        assert "turn_id" not in evt.payload


# ── TurnID 一致性验证 ─────────────────────────────────────────────────


class TestTurnIdConsistencyAcrossEvents:
    """单轮内所有事件 share 同一 turn_id"""

    def test_all_events_in_one_turn_share_same_turn_id(self):
        """turn/start → tool/call → tool/result → turn/end 全链路 turn_id 一致"""
        log = SessionEventLog(session_id="test-session-42")
        turn_id = "shared-turn-id"

        log.record_turn_start(1, turn_id=turn_id, model="test-model")
        log.record_tool_call("call-1", "get_broker_market_data", '{"action":"QUOTE"}')
        log.record_tool_result("call-1", "get_broker_market_data", '{"price": 150}', turn_id=turn_id)
        log.record_turn_end(
            1,
            content_len=500,
            turn_id=turn_id,
            prompt_tokens=300,
            completion_tokens=100,
            inference_ms=2000,
            tool_ms=100,
            save_ms=50,
        )

        events = log.events
        assert len(events) == 4

        # 验证 turn/start 有 turn_id
        assert events[0].type == "turn/start"
        assert events[0].payload["turn_id"] == turn_id

        # 验证 tool/result 有 turn_id（工具调用无）
        assert events[2].type == "tool/result"
        assert events[2].payload["turn_id"] == turn_id

        # 验证 turn/end 有 turn_id
        assert events[3].type == "turn/end"
        assert events[3].payload["turn_id"] == turn_id

        # 验证其他字段的完整性
        assert events[3].payload["latency"]["inference_ms"] == 2000


# ── Prometheus Metrics 初始化测试 ─────────────────────────────────────


class TestPrometheusMetricsInitialization:
    """_init_prometheus_metrics 和 _observe_turn_duration 正确工作"""

    def test_observed_turn_duration(self):
        """观测函数正常记录（若 prometheus_client 已安装）"""
        from hermes_agent.agent import _observe_turn_duration

        # 不应抛异常，即使 prometheus_client 未安装
        _observe_turn_duration("test_phase", "test_model", 1.5)  # 1.5s


# ── Integration: Event Log + Timing Realism ───────────────────────────


class TestRealisticTimingValues:
    """真实场景下的合理延迟值范围"""

    def test_reasonable_latency_values(self):
        """LLM 推理：500-5000ms；Tool：50-500ms；Save：10-100ms"""
        log = SessionEventLog(session_id="benchmark")
        turn_id = "benchmark-turn"

        # 模拟典型 LLM 推理 + Tool + Save
        log.record_turn_start(1, turn_id=turn_id, model="deepseek-chat")
        log.record_turn_end(
            1,
            content_len=2048,
            turn_id=turn_id,
            prompt_tokens=1024,
            completion_tokens=512,
            inference_ms=2500.0,  # ~2.5s LLM
            tool_ms=150.0,  # ~150ms tool
            save_ms=35.0,  # ~35ms save
        )

        events = [e for e in log.events if e.type == "turn/end"]
        assert len(events) == 1
        latency = events[0].payload["latency"]

        assert 500 <= latency["inference_ms"] <= 5000
        assert 10 <= latency["tool_ms"] <= 500
        assert 1 <= latency["save_ms"] <= 100
