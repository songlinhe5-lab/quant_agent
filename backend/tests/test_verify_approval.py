"""
AGENT-08 · Verify 阶段测试
AGENT-07 · 审批闸门骨架测试
"""

import os
import sys
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_BASE_URL", "https://api.test.com")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── AGENT-08: Verify 阶段 ──────────────────────────────────────────


class TestVerifyToolResult:
    """AGENT-08: 工具结果校验测试"""

    def test_verify_none_fails_empty(self):
        """None 结果 → FAIL_EMPTY"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        evidence = verify_tool_result("test_tool", None)
        assert evidence.status == VerifyStatus.FAIL_EMPTY
        assert not evidence.passed

    def test_verify_empty_dict_fails(self):
        """空 dict → FAIL_EMPTY"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        evidence = verify_tool_result("test_tool", {})
        assert evidence.status == VerifyStatus.FAIL_EMPTY

    def test_verify_error_dict_fails(self):
        """error status dict → FAIL_INVALID"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        result = {"status": "error", "message": "连接超时"}
        evidence = verify_tool_result("test_tool", result)
        assert evidence.status == VerifyStatus.FAIL_INVALID

    def test_verify_success_dict_passes(self):
        """正常数据 → PASS"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        result = {"price": 150.0, "volume": 1000}
        evidence = verify_tool_result("test_tool", result)
        assert evidence.status == VerifyStatus.PASS
        assert evidence.passed

    def test_verify_stale_timestamp(self):
        """过期时间戳 → FAIL_STALE"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        stale_ts = time.time() - 100000  # 远超 24h 阈值
        result = {"price": 150.0, "timestamp": stale_ts}
        evidence = verify_tool_result("test_tool", result, freshness_threshold=86400)
        assert evidence.status == VerifyStatus.FAIL_STALE

    def test_verify_fresh_timestamp_passes(self):
        """新鲜时间戳 → PASS"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        fresh_ts = time.time() - 60  # 1 分钟前
        result = {"price": 150.0, "timestamp": fresh_ts}
        evidence = verify_tool_result("test_tool", result)
        assert evidence.status == VerifyStatus.PASS

    def test_verify_empty_list_fails(self):
        """空 list → FAIL_EMPTY"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        evidence = verify_tool_result("test_tool", [])
        assert evidence.status == VerifyStatus.FAIL_EMPTY

    def test_verify_nonempty_list_passes(self):
        """非空 list → PASS"""
        from hermes_agent.verify import VerifyStatus, verify_tool_result

        evidence = verify_tool_result("test_tool", [1, 2, 3])
        assert evidence.status == VerifyStatus.PASS

    def test_evidence_has_checks_performed(self):
        """证据记录已执行的检查项"""
        from hermes_agent.verify import verify_tool_result

        result = {"price": 150.0}
        evidence = verify_tool_result("test_tool", result)
        assert "non_empty" in evidence.checks_performed

    def test_evidence_to_dict(self):
        """证据可序列化为 dict"""
        from hermes_agent.verify import verify_tool_result

        evidence = verify_tool_result("test_tool", {"data": "ok"})
        d = evidence.to_dict()
        assert d["tool"] == "test_tool"
        assert d["verify_status"] == "pass"
        assert "non_empty" in d["checks"]


# ─── AGENT-07: 审批闸门骨架 ─────────────────────────────────────────


class TestApprovalSkeleton:
    """AGENT-07: 审批闸门骨架测试"""

    def test_approval_outcome_enum(self):
        """审批结果闭集枚举"""
        from hermes_agent.approval import ApprovalOutcome

        assert ApprovalOutcome.ALLOWED_ONCE.value == "allowed-once"
        assert ApprovalOutcome.REJECTED.value == "rejected"
        assert ApprovalOutcome.CANCELLED.value == "cancelled"
        assert ApprovalOutcome.UNAVAILABLE.value == "unavailable"

    def test_is_trade_tool_detection(self):
        """交易工具识别"""
        from hermes_agent.approval import is_trade_tool

        assert is_trade_tool("broker_trade_buy")
        assert is_trade_tool("EMERGENCY_LIQUIDATION")
        assert not is_trade_tool("get_broker_market_data")
        assert not is_trade_tool("calculate_technical_indicators")

    def test_skeleton_always_allows(self):
        """骨架当前 always-allow"""
        from hermes_agent.approval import ApprovalOutcome, check_trade_approval

        record = check_trade_approval(
            tool_name="broker_trade_buy",
            tool_call_id="call_123",
            arguments={"symbol": "AAPL", "side": "BUY", "qty": 100},
        )
        assert record.outcome == ApprovalOutcome.ALLOWED_ONCE
        assert record.tool_name == "broker_trade_buy"
        assert record.approval_id  # 非空

    def test_approval_record_has_audit_pair(self):
        """审批记录含审计对（asked + decided）"""
        from hermes_agent.approval import check_trade_approval

        record = check_trade_approval(
            tool_name="broker_trade_sell",
            tool_call_id="call_456",
            arguments={"symbol": "TSLA"},
        )
        assert record.asked  # 有审批请求
        assert record.decided  # 有审批决策
        assert record.approval_id  # 唯一 ID

    def test_approval_record_to_dict(self):
        """审批记录可序列化"""
        from hermes_agent.approval import check_trade_approval

        record = check_trade_approval(
            tool_name="broker_trade_buy",
            tool_call_id="call_789",
            arguments={},
        )
        d = record.to_dict()
        assert d["tool"] == "broker_trade_buy"
        assert d["outcome"] == "allowed-once"
        assert "approval_id" in d
