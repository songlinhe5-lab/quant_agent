"""
Pytest 公共 Fixtures
TEST-08: 测试框架与脚手架搭建
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# 💡 修复事件循环问题：为异步测试提供事件循环
@pytest.fixture(scope="function")
def event_loop():
    """为每个测试函数创建独立的事件循环"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# ─── 环境变量 Mock（必须在导入 app 之前设置）─────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "test_password")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("QUANT_ENV", "testing")


# ─── Fixtures: 数据库 ──────────────────────────────────────────────
@pytest.fixture
def mock_db():
    """Mock 数据库会话"""
    db = MagicMock()
    db.query.return_value = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.close = MagicMock()
    return db


@pytest.fixture
def mock_async_db():
    """Mock 异步数据库会话"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ─── Fixtures: Redis ────────────────────────────────────────────────
@pytest.fixture
def mock_redis():
    """Mock Redis 客户端"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    redis.hgetall = AsyncMock(return_value={})
    redis.publish = AsyncMock()
    redis.xadd = AsyncMock(return_value=b"1234-0")
    redis.xread = AsyncMock(return_value=[])
    return redis


# ─── Fixtures: HTTP 客户端 ──────────────────────────────────────────
@pytest.fixture
def mock_httpx():
    """Mock httpx 异步客户端"""
    client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}
    response.text = ""
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    client.put = AsyncMock(return_value=response)
    client.delete = AsyncMock(return_value=response)
    return client


# ─── Fixtures: FastAPI TestClient ───────────────────────────────────
@pytest.fixture
def test_client():
    """FastAPI 测试客户端（同步）"""
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    return client


@pytest.fixture
async def async_test_client():
    """FastAPI 测试客户端（异步）"""
    import httpx

    from backend.main import app

    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client


# ─── Fixtures: 认证 ─────────────────────────────────────────────────
@pytest.fixture
def mock_user():
    """Mock 用户数据"""
    return {
        "id": 1,
        "username": "test_user",
        "email": "test@example.com",
        "role": "user",
    }


@pytest.fixture
def admin_user():
    """Mock 管理员用户"""
    return {
        "id": 999,
        "username": "admin",
        "email": "admin@example.com",
        "role": "admin",
    }


@pytest.fixture
def auth_headers():
    """Mock 认证头"""
    return {"Authorization": "Bearer test-access-token"}


# ─── Fixtures: 行情数据 ─────────────────────────────────────────────
@pytest.fixture
def sample_quote():
    """示例行情数据"""
    return {
        "symbol": "HK.00700",
        "last_price": 400.0,
        "open": 398.0,
        "high": 405.0,
        "low": 395.0,
        "prev_close": 397.0,
        "volume": 1000000,
        "turnover": 400000000.0,
        "change": 3.0,
        "change_percent": 0.76,
        "timestamp": 1719500000,
    }


@pytest.fixture
def sample_klines():
    """示例 K 线数据"""
    return [
        {
            "timestamp": 1719500000 + i * 86400,
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 10000 + i * 100,
        }
        for i in range(30)
    ]


# ─── Fixtures: 订单/持仓 ────────────────────────────────────────────
@pytest.fixture
def sample_order():
    """示例订单数据"""
    return {
        "id": "ORD-001",
        "symbol": "HK.00700",
        "side": "BUY",
        "type": "LIMIT",
        "quantity": 100,
        "price": 400.0,
        "filled_quantity": 0,
        "status": "PENDING",
        "is_paper": True,
    }


@pytest.fixture
def sample_position():
    """示例持仓数据"""
    return {
        "id": "POS-001",
        "symbol": "HK.00700",
        "side": "LONG",
        "quantity": 100,
        "avg_cost": 395.0,
        "current_price": 400.0,
        "market_value": 40000.0,
        "unrealized_pnl": 500.0,
        "unrealized_pnl_percent": 1.27,
        "status": "OPEN",
    }


# ─── Fixtures: 外部服务 Mock ────────────────────────────────────────
@pytest.fixture
def mock_futu():
    """Mock Futu OpenD 连接"""
    futu = MagicMock()
    futu.connect = MagicMock(return_value=0)
    futu.is_connected = MagicMock(return_value=True)
    futu.get_market_snapshot = MagicMock(return_value=[])
    futu.get_cur_kline = MagicMock(return_value=([], 0))
    return futu


@pytest.fixture
def mock_yfinance():
    """Mock yfinance"""
    with patch("yfinance.Ticker") as mock_ticker:
        ticker = MagicMock()
        ticker.info = {"currentPrice": 150.0, "marketCap": 2000000000}
        ticker.history = MagicMock()
        mock_ticker.return_value = ticker
        yield mock_ticker


# ─── 测试数据工厂 ────────────────────────────────────────────────────
class TestDataFactory:
    """测试数据工厂，快速生成各类测试数据"""

    @staticmethod
    def make_quote(**kwargs) -> dict:
        base = {
            "symbol": "HK.00700",
            "last_price": 400.0,
            "open": 398.0,
            "high": 405.0,
            "low": 395.0,
            "prev_close": 397.0,
            "volume": 1000000,
            "turnover": 400000000.0,
            "change": 3.0,
            "change_percent": 0.76,
            "timestamp": 1719500000,
        }
        base.update(kwargs)
        return base

    @staticmethod
    def make_kline(**kwargs) -> dict:
        base = {
            "timestamp": 1719500000,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 10000,
        }
        base.update(kwargs)
        return base

    @staticmethod
    def make_order(**kwargs) -> dict:
        base = {
            "id": "ORD-001",
            "symbol": "HK.00700",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": 100,
            "price": 400.0,
            "filled_quantity": 0,
            "status": "PENDING",
            "is_paper": True,
        }
        base.update(kwargs)
        return base

    @staticmethod
    def make_position(**kwargs) -> dict:
        base = {
            "id": "POS-001",
            "symbol": "HK.00700",
            "side": "LONG",
            "quantity": 100,
            "avg_cost": 395.0,
            "current_price": 400.0,
            "market_value": 40000.0,
            "unrealized_pnl": 500.0,
            "unrealized_pnl_percent": 1.27,
            "status": "OPEN",
        }
        base.update(kwargs)
        return base

    @staticmethod
    def make_user(**kwargs) -> dict:
        base = {
            "id": 1,
            "username": "test_user",
            "email": "test@example.com",
            "role": "user",
        }
        base.update(kwargs)
        return base


@pytest.fixture
def factory():
    """测试数据工厂"""
    return TestDataFactory()
