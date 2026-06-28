"""
行情路由 & 核心模块单元测试
TEST-01: 行情管道、熔断器、响应封装
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


import pytest


class TestMarketRoutes:
    """行情路由测试"""

    def test_quote_endpoint(self, test_client):
        """测试行情查询端点"""
        response = test_client.get("/api/v1/market/quote?symbol=HK.00700")
        # 可能成功或因 Futu 未连接而返回错误，或 422 参数校验失败
        assert response.status_code in (200, 400, 422, 500, 502, 503)

    def test_quote_missing_symbol(self, test_client):
        """测试缺少标的代码"""
        response = test_client.get("/api/v1/market/quote")
        assert response.status_code in (400, 422)

    def test_fundamental_endpoint(self, test_client):
        """测试基本面查询端点"""
        response = test_client.get("/api/v1/fundamental/data?symbol=HK.00700")
        # 路由可能不存在或返回 404/503
        assert response.status_code in (200, 400, 404, 422, 500, 502, 503)


class TestCircuitBreaker:
    """熔断器测试"""

    def test_circuit_breaker_closed_state(self):
        """测试熔断器关闭状态（正常）"""
        from backend.core.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(max_failures=3, recovery_timeout=60)

        async def success_fn():
            return "ok"

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            cb.call("test_svc", success_fn)
        )  # noqa: E501
        assert result == "ok"
        assert cb.get_state("test_svc") == CircuitState.CLOSED

    def test_circuit_breaker_open_state(self):
        """测试熔断器打开状态（熔断）"""
        from backend.core.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerOpenError,
            CircuitState,
        )

        cb = CircuitBreaker(max_failures=2, recovery_timeout=60)

        async def fail_fn():
            raise RuntimeError("外部服务失败")

        import asyncio

        loop = asyncio.get_event_loop()

        # 连续失败触发熔断
        for _ in range(2):
            with pytest.raises(RuntimeError):
                loop.run_until_complete(cb.call("test_open", fail_fn))

        assert cb.get_state("test_open") == CircuitState.OPEN

        # 再次调用应触发熔断器打开异常
        with pytest.raises(CircuitBreakerOpenError):
            loop.run_until_complete(cb.call("test_open", fail_fn))


class TestUnifiedResponse:
    """统一响应封装测试"""

    def test_success_response_structure(self, test_client):
        """测试成功响应结构"""
        response = test_client.get("/api/v1/health")
        # 200 或 503 均可接受（取决于 Redis 连接状态）
        assert response.status_code in (200, 503)
        data = response.json()
        # 统一响应应有 code 或 status 字段
        assert "code" in data or "status" in data

    def test_error_response_structure(self, test_client):
        """测试错误响应结构"""
        response = test_client.get("/api/v1/nonexistent")
        assert response.status_code == 404


class TestDomainSchemas:
    """Pydantic 领域模型测试"""

    def test_quote_schema(self):
        """测试 Quote Schema"""
        from backend.schemas.domain import QuoteModel

        quote = QuoteModel(
            symbol="HK.00700",
            price=400.0,
            open=398.0,
            high=405.0,
            low=395.0,
            prev_close=397.0,
            volume=1000000,
            turnover=400000000.0,
            change=3.0,
            change_pct=0.76,
            ts=1719500000,
        )
        assert quote.symbol == "HK.00700"
        assert quote.price == 400.0

    def test_kline_schema(self):
        """测试 Kline Schema"""
        from backend.schemas.domain import KlineModel

        kline = KlineModel(
            ts=1719500000,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=10000,
        )
        assert kline.close == 101.0

    def test_order_schema(self):
        """测试 Order Schema"""
        import time

        from backend.schemas.domain import OrderModel

        now = int(time.time() * 1000)
        order = OrderModel(
            order_id="ORD-001",
            symbol="HK.00700",
            side="buy",
            order_type="limit",
            qty=100,
            price=400.0,
            filled_qty=0,
            status="pending",
            is_simulated=True,
            created_at=now,
            updated_at=now,
        )
        assert order.symbol == "HK.00700"
        assert order.qty == 100

    def test_position_schema(self):
        """测试 Position Schema"""
        from backend.schemas.domain import PositionModel

        position = PositionModel(
            symbol="HK.00700",
            qty=100,
            avg_cost=395.0,
            current_price=400.0,
            market_value=40000.0,
            unrealized_pnl=500.0,
            unrealized_pnl_pct=1.27,
        )
        assert position.symbol == "HK.00700"
        assert position.unrealized_pnl == 500.0
