"""
Pytest 公共 Fixtures
TEST-08: 测试框架与脚手架搭建
"""

# ─── 🔇 过滤 Python 3.13 MagicMock 误报警告 ──────────────────
# Python 3.13 中，MagicMock 访问某些属性时会内部产生 unawaited coroutine
# 警告，这些来自 unittest.mock 内部实现，不是业务代码的 bug。
# 必须在 import unittest.mock 之前设置才有效。
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)

import asyncio  # noqa: E402
import logging  # noqa: E402
import logging.handlers  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

# ─── 🔧 关键修复：在导入任何模块之前 Mock redis.asyncio.Redis ─────────
# 防止 backend.core.redis_client 模块在 import 时创建真实 Redis 连接（导致测试超时）
# 必须在 `import redis.asyncio` 之前执行，确保模块加载时类已被替换
_redis_asyncio_patcher = patch("redis.asyncio.Redis", new_callable=AsyncMock)
_redis_asyncio_patcher.start()

# ─── futu logger 权限兜底 ──────────────────────────────────
# macOS TCC/sandbox 可能禁止写 ~/.com.futunn.FutuOpenD/Log,导致 `from futu import ...` 失败。
# 在任何模块 import futu 之前,patch TimedRotatingFileHandler 使其在 PermissionError 时降级为 StreamHandler。
_orig_trfh_init = logging.handlers.TimedRotatingFileHandler.__init__


def _safe_trfh_init(self, *args, **kwargs):
    try:
        _orig_trfh_init(self, *args, **kwargs)
    except PermissionError:
        logging.StreamHandler.__init__(self)


logging.handlers.TimedRotatingFileHandler.__init__ = _safe_trfh_init


# 💡 为使用 asyncio.get_event_loop() + loop.run_until_complete() 的旧测试提供事件循环
# 注意：pytest-asyncio Mode.AUTO 已自动管理 event loop，但 test_tools.py 等旧测试
# 显式调用 get_event_loop()，需要这个 fixture 才能正常工作。
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
# 💡 关键修复：测试环境强制 SQLite，避免 CI 的 PostgreSQL DATABASE_URL 导致
# pgvector.sqlalchemy.Vector 类型在 SQLite 内存库上编译失败（no such table: users）
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "test_password")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("QUANT_ENV", "testing")
# 🚀 测试环境加速：降低 bcrypt 成本因子（默认 12 → 4，加速约 16x）
# 注意：必须使用直接赋值而非 setdefault，防止 .env 或系统环境已设置该变量
os.environ["BCRYPT_ROUNDS"] = "4"
# 💡 消除 encryption.py 的 "ENCRYPTION_MASTER_KEY 未配置" RuntimeWarning
os.environ["ENCRYPTION_MASTER_KEY"] = "00" * 32  # 64 字符十六进制 = 32 字节 AES-256 密钥
# 💡 取消 chat router 模拟延迟（测试环境加速）
os.environ["CHAT_MOCK_DELAY"] = "0"


# ─── 🔧 全局 Redis Mock Fixture（autouse）───────────────────────────
# 自动 patch 各模块中的 redis_client/l1_cached_redis/redis_batch_writer 引用，
# 确保所有测试不依赖真实 Redis。
# 如需添加新的模块，往 _REDIS_PATCH_MODULES 列表追加即可。
_REDIS_PATCH_MODULES = [
    "backend.core.redis_client",
    "backend.main",
    "backend.services.sentiment_tracker",
]


@pytest.fixture(autouse=True)
def _mock_redis_globals():
    """
    全局自动 fixture：动态 patch 所有已知模块中导入的 redis 全局变量。
    通过 importlib 动态导入模块，仅对模块确实存在的属性打补丁，
    避免因模块没有某个属性而抛出 AttributeError。
    """
    import importlib
    from contextlib import ExitStack

    _fake_store = {}

    # 构造一个通用的 AsyncMock Redis 客户端
    mock_rc = AsyncMock()
    mock_rc.get = AsyncMock(side_effect=lambda k: _fake_store.get(k))
    mock_rc.set = AsyncMock(side_effect=lambda k, v, **kw: (_fake_store.update({k: v}), True)[1])
    mock_rc.delete = AsyncMock(side_effect=lambda *keys: sum(_fake_store.pop(k, None) or 0 for k in keys))
    mock_rc.exists = AsyncMock(side_effect=lambda k: 1 if k in _fake_store else 0)
    mock_rc.expire = AsyncMock(return_value=True)
    mock_rc.incr = AsyncMock(
        side_effect=lambda k: _fake_store.update({k: int(_fake_store.get(k, 0)) + 1}) or _fake_store[k]
    )
    mock_rc.publish = AsyncMock(return_value=0)
    mock_rc.scan = AsyncMock(return_value=("0", []))
    mock_rc.aclose = AsyncMock()

    # ping() 必须正常返回，否则 health_check 会报 unhealthy
    mock_rc.ping = AsyncMock(return_value=True)

    # pipeline 支持 async with
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = AsyncMock(
        side_effect=lambda k: _fake_store.update({k: int(_fake_store.get(k, 0)) + 1}) or _fake_store[k]
    )
    mock_pipe.expire = AsyncMock(return_value=True)
    mock_pipe.execute = AsyncMock(return_value=[1, True])  # 对应 incr + expire 的返回值
    mock_rc.pipeline = MagicMock(return_value=mock_pipe)

    # pubsub mock（供 MCP SSE 使用）
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value=None)
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()
    mock_rc.pubsub = MagicMock(return_value=mock_pubsub)

    # l1_cached_redis mock（LocalL1Cache 的接口）
    mock_l1 = AsyncMock()
    mock_l1.get = AsyncMock(side_effect=lambda k: _fake_store.get(k))
    mock_l1.set = AsyncMock(side_effect=lambda k, v, **kw: (_fake_store.update({k: v}), None)[1])
    mock_l1.invalidate = MagicMock()

    # redis_batch_writer mock
    mock_writer = MagicMock()
    mock_writer.put_set_nowait = MagicMock()
    mock_writer.start = MagicMock()
    mock_writer.stop = AsyncMock()

    with ExitStack() as stack:
        for module_name in _REDIS_PATCH_MODULES:
            try:
                mod = importlib.import_module(module_name)
                # 仅 patch 模块确实存在的属性
                if hasattr(mod, "redis_client"):
                    stack.enter_context(patch(f"{module_name}.redis_client", mock_rc))
                if hasattr(mod, "l1_cached_redis"):
                    stack.enter_context(patch(f"{module_name}.l1_cached_redis", mock_l1))
                if hasattr(mod, "redis_batch_writer"):
                    stack.enter_context(patch(f"{module_name}.redis_batch_writer", mock_writer))
            except ImportError:
                # 模块尚未被导入（测试不涉及该模块），安全跳过
                pass

        yield


# ─── 🔧 全局 Futu/VyFinance Mock（autouse）────────────────────────
# 防止测试时尝试连接 Futu OpenD 或雅虎财经
# 💡 注意：test_yfinance_service.py 和 test_yfinance_service_batch.py 会自行 mock，
# 因此这两个文件需要在测试类中添加 `@pytest.mark.no_mock_external` 来跳过此 fixture
@pytest.fixture(autouse=True)
def _mock_external_services(request):
    """自动 mock 外部数据服务，避免测试时触发真实网络请求"""
    # 💡 环境变量开关：设置 DISABLE_EXTERNAL_MOCK=1 可禁用所有外部服务 mock
    if os.environ.get("DISABLE_EXTERNAL_MOCK") == "1":
        yield
        return

    # 检查测试是否标记了 no_mock_external
    marker = request.node.get_closest_marker("no_mock_external")
    if marker is not None:
        # 如果标记了 no_mock_external，则不执行 mock
        yield
    else:
        # 💡 注意：此处仅 mock 服务实例，不 mock yfinance 模块本身
        # 否则会导致 yfinance_service.py 的 coverage 统计异常
        with patch("backend.services.futu_service.futu_service") as mock_futu:
            mock_futu.status = "DISCONNECTED"
            mock_futu.get_market_snapshot = AsyncMock(return_value=([], None))
            yield


# ─── Fixtures: 数据库 ────────────────────────────────────────
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


# ─── Fixtures: Redis ──────────────────────────────────────────
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


# ─── Fixtures: HTTP 客户端 ──────────────────────────────────────
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


# ─── Fixtures: FastAPI TestClient ───────────────────────────
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


# ─── Fixtures: 认证 ─────────────────────────────────────────────
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


# ─── Fixtures: 行情数据 ────────────────────────────────────────
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
        "turn_over": 400000000.0,
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


# ─── Fixtures: 订单/持仓 ────────────────────────────────────
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


# ─── Fixtures: 外部服务 Mock ────────────────────────────────
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


# ─── 测试数据工厂 ────────────────────────────────────────────
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
            "turn_over": 400000000.0,
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
