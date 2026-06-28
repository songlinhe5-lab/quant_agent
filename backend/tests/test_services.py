"""
存量服务层单元测试
TEST-09: 对现有 services/ 核心逻辑补齐单测
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from unittest.mock import MagicMock

import pytest


# ─── Audit Service ───────────────────────────────────────────────────
class TestAuditService:
    """审计日志服务测试"""

    def test_generate_trace_id(self):
        """测试 trace_id 生成"""
        import uuid

        from backend.services.audit_service import generate_trace_id

        trace_id = generate_trace_id()
        # 应该是合法的 UUID
        uuid.UUID(trace_id)
        assert len(trace_id) > 0

    def test_generate_trace_id_unique(self):
        """测试 trace_id 唯一性"""
        from backend.services.audit_service import generate_trace_id

        ids = [generate_trace_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_get_client_ip_with_forwarded(self):
        """测试从 X-Forwarded-For 获取 IP"""
        from backend.services.audit_service import get_client_ip

        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        request.client = None

        ip = get_client_ip(request)
        assert ip == "1.2.3.4"

    def test_get_client_ip_with_real_ip(self):
        """测试从 X-Real-IP 获取 IP"""
        from backend.services.audit_service import get_client_ip

        request = MagicMock()
        request.headers = {"X-Real-IP": "10.0.0.1"}
        request.client = None

        ip = get_client_ip(request)
        assert ip == "10.0.0.1"

    def test_get_client_ip_with_client(self):
        """测试从 client.host 获取 IP"""
        from backend.services.audit_service import get_client_ip

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        ip = get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_get_client_ip_none_request(self):
        """测试 None request"""
        from backend.services.audit_service import get_client_ip

        ip = get_client_ip(None)
        assert ip is None

    def test_log_audit(self, mock_db):
        """测试审计日志写入"""
        from backend.services.audit_service import log_audit

        log_audit(
            db=mock_db,
            action="login",
            detail={"username": "test"},
            user_id=1,
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

    def test_get_audit_logs(self, mock_db):
        """测试审计日志查询"""
        from backend.services.audit_service import get_audit_logs

        # mock_db.query 已在 conftest 中 mock
        get_audit_logs(mock_db, action="login", user_id=1, skip=0, limit=10)
        mock_db.query.assert_called()


# ─── OMS Mock Data ───────────────────────────────────────────────────
class TestOmsMockData:
    """OMS 模拟数据测试"""

    def test_initial_bots_structure(self):
        """测试初始机器人数据结构"""
        from backend.services.oms_mock_data import INITIAL_BOTS

        assert len(INITIAL_BOTS) > 0
        for bot in INITIAL_BOTS:
            assert "id" in bot
            assert "name" in bot
            assert "status" in bot
            assert bot["status"] in ("running", "paused", "stopped")

    def test_active_orders_structure(self):
        """测试活跃订单数据结构"""
        from backend.services.oms_mock_data import ACTIVE_ORDERS

        assert len(ACTIVE_ORDERS) > 0
        for order in ACTIVE_ORDERS:
            assert "id" in order
            assert "symbol" in order
            assert "side" in order
            assert order["side"] in ("BUY", "SELL")
            assert "qty" in order
            assert order["qty"] > 0

    def test_historical_trades_structure(self):
        """测试历史成交数据结构"""
        from backend.services.oms_mock_data import HISTORICAL_TRADES

        assert len(HISTORICAL_TRADES) > 0
        for trade in HISTORICAL_TRADES:
            assert "id" in trade
            assert "symbol" in trade
            assert "pnl" in trade

    def test_algo_executions_structure(self):
        """测试算法执行数据结构"""
        from backend.services.oms_mock_data import ALGO_EXECUTIONS

        assert len(ALGO_EXECUTIONS) > 0
        for algo in ALGO_EXECUTIONS:
            assert "id" in algo
            assert "algo_type" in algo
            assert algo["algo_type"] in ("TWAP", "VWAP", "ICEBERG")
            assert "progress" in algo
            assert 0 <= algo["progress"] <= 100


# ─── Encryption Utils ────────────────────────────────────────────────
class TestEncryption:
    """加密工具测试"""

    def test_encrypt_decrypt_roundtrip(self):
        """测试加密解密往返"""
        from backend.core.encryption import (
            decrypt_sensitive_data,
            encrypt_sensitive_data,
        )

        plaintext = "my-secret-api-key-12345"
        encrypted = encrypt_sensitive_data(plaintext)

        assert encrypted != plaintext
        assert len(encrypted) > 0

        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == plaintext

    def test_encrypt_different_ciphertext(self):
        """测试同一明文产生不同密文（AES-GCM 随机 nonce）"""
        from backend.core.encryption import encrypt_sensitive_data

        plaintext = "same-secret"
        enc1 = encrypt_sensitive_data(plaintext)
        enc2 = encrypt_sensitive_data(plaintext)
        # GCM 模式下每次加密 nonce 不同，密文应不同
        assert enc1 != enc2

    def test_encrypt_empty_string(self):
        """测试空字符串加密"""
        from backend.core.encryption import (
            decrypt_sensitive_data,
            encrypt_sensitive_data,
        )

        encrypted = encrypt_sensitive_data("")
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == ""


# ─── Circuit Breaker (补充) ──────────────────────────────────────────
class TestCircuitBreakerAdvanced:
    """熔断器高级测试"""

    def test_half_open_state_transition(self):
        """测试 OPEN → HALF_OPEN 状态转换"""
        import asyncio
        import time

        from backend.core.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(max_failures=1, recovery_timeout=0.1)

        async def fail_fn():
            raise RuntimeError("fail")

        loop = asyncio.get_event_loop()

        # 触发熔断
        with pytest.raises(RuntimeError):
            loop.run_until_complete(cb.call("half_open_test", fail_fn))

        assert cb.get_state("half_open_test") == CircuitState.OPEN

        # 等待恢复超时
        time.sleep(0.2)

        # 应该转为 HALF_OPEN
        assert cb.get_state("half_open_test") == CircuitState.HALF_OPEN

    def test_multiple_services_independent(self):
        """测试不同服务熔断状态独立"""
        import asyncio

        from backend.core.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)

        async def fail_fn():
            raise RuntimeError("fail")

        async def ok_fn():
            return "ok"

        loop = asyncio.get_event_loop()

        # 服务 A 失败
        for _ in range(2):
            with pytest.raises(RuntimeError):
                loop.run_until_complete(cb.call("svc_a", fail_fn))

        # 服务 B 正常
        result = loop.run_until_complete(cb.call("svc_b", ok_fn))
        assert result == "ok"

        # A 熔断，B 正常
        assert cb.get_state("svc_a") == CircuitState.OPEN
        assert cb.get_state("svc_b") == CircuitState.CLOSED
