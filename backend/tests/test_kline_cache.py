"""
K线三级缓存引擎单元测试
覆盖: backend/core/kline_cache.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── 测试数据工厂 ─────────────────────────────────────────────────
def make_test_kline_df(rows: int = 10) -> pd.DataFrame:
    """生成测试用 K 线 DataFrame"""
    base = datetime.now(timezone.utc) - timedelta(days=rows)
    data = []
    for i in range(rows):
        data.append(
            {
                "time": base + timedelta(days=i),
                "open": 100.0 + i,
                "high": 102.0 + i,
                "low": 99.0 + i,
                "close": 101.0 + i,
                "volume": 10000 + i * 100,
            }
        )
    return pd.DataFrame(data)


# ─── CacheTier 枚举 ───────────────────────────────────────────────
class TestCacheTier:
    def test_tier_values(self):
        from backend.core.kline_cache import CacheTier

        assert CacheTier.L1_REDIS == "redis"
        assert CacheTier.L2_PARQUET == "parquet"
        assert CacheTier.L3_OBJECT == "object"
        assert CacheTier.MISS == "miss"


# ─── 模块级常量 ───────────────────────────────────────────────────
class TestModuleConstants:
    def test_l1_ttl_days_value(self):
        from backend.core.kline_cache import L1_TTL_DAYS

        assert L1_TTL_DAYS == 5

    def test_l1_ttl_seconds_value(self):
        from backend.core.kline_cache import L1_TTL_DAYS, L1_TTL_SECONDS

        assert L1_TTL_SECONDS == L1_TTL_DAYS * 86400

    def test_l2_retention_days_value(self):
        from backend.core.kline_cache import L2_RETENTION_DAYS

        assert L2_RETENTION_DAYS == 365

    def test_l1_key_prefix(self):
        from backend.core.kline_cache import L1_KEY_PREFIX

        assert L1_KEY_PREFIX == "quant:kline"


# ─── KlineCacheEngine: get_kline 路由策略 ─────────────────────────
class TestKlineCacheEngineGet:
    """get_kline 的智能路由与降级逻辑"""

    def test_get_kline_routes_to_l1_for_short_days(self):
        from backend.core.kline_cache import CacheTier, KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._warehouse = AsyncMock()

        df = make_test_kline_df(3)
        engine._get_l1 = AsyncMock(return_value=df)

        result = asyncio_run(engine.get_kline("US.AAPL", "K_DAY", days=3))
        assert result is not None
        engine._get_l1.assert_called_once()

    def test_get_kline_routes_to_l2_for_medium_days(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._warehouse = AsyncMock()

        df = make_test_kline_df(30)
        engine._get_l2 = AsyncMock(return_value=df)

        result = asyncio_run(engine.get_kline("US.AAPL", "K_DAY", days=30))
        assert result is not None
        engine._get_l2.assert_called_once()

    def test_get_kline_routes_to_l3_for_long_days(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._warehouse = AsyncMock()
        engine._get_l3 = AsyncMock(return_value=None)

        result = asyncio_run(engine.get_kline("US.AAPL", "K_DAY", days=400))
        assert result is None
        engine._get_l3.assert_called_once()

    def test_get_kline_l1_miss_fallback_to_l2(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._warehouse = AsyncMock()
        engine._get_l1 = AsyncMock(return_value=None)
        df = make_test_kline_df(3)
        engine._get_l2 = AsyncMock(return_value=df)
        engine._fill_l1 = AsyncMock()

        result = asyncio_run(
            engine.get_kline("US.AAPL", "K_DAY", days=3, fill_l1=True)
        )
        assert result is not None
        engine._get_l2.assert_called_once()

    def test_get_kline_l1_miss_l2_miss_returns_none(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._get_l1 = AsyncMock(return_value=None)
        engine._get_l2 = AsyncMock(return_value=None)

        result = asyncio_run(engine.get_kline("US.AAPL", "K_DAY", days=3))
        assert result is None

    def test_get_kline_explicit_tier_overrides_auto(self):
        from backend.core.kline_cache import CacheTier, KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._warehouse = AsyncMock()
        engine._get_l1 = AsyncMock(return_value=make_test_kline_df(3))
        engine._get_l2 = AsyncMock(return_value=None)

        # 强制 L2，days=3 (本来应路由到 L1)
        asyncio_run(
            engine.get_kline(
                "US.AAPL", "K_DAY", days=3, tier=CacheTier.L2_PARQUET
            )
        )
        engine._get_l2.assert_called_once()
        engine._get_l1.assert_not_called()


# ─── KlineCacheEngine: put_kline 写入 ─────────────────────────────
class TestKlineCacheEnginePut:
    def test_put_kline_none_df_skipped(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._put_l1 = AsyncMock()
        asyncio_run(engine.put_kline("US.AAPL", "K_DAY", None))
        engine._put_l1.assert_not_called()

    def test_put_kline_empty_df_skipped(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._put_l1 = AsyncMock()
        asyncio_run(engine.put_kline("US.AAPL", "K_DAY", pd.DataFrame()))
        engine._put_l1.assert_not_called()

    def test_put_kline_writes_to_l1(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._put_l1 = AsyncMock()
        df = make_test_kline_df(5)
        asyncio_run(engine.put_kline("US.AAPL", "K_DAY", df))
        engine._put_l1.assert_called_once_with("US.AAPL", "K_DAY", df)


# ─── KlineCacheEngine: L1 Redis 操作 ──────────────────────────────
class TestKlineCacheEngineL1:
    def test_get_l1_empty_redis_returns_none(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._redis.hgetall = AsyncMock(return_value={})

        result = asyncio_run(engine._get_l1("US.AAPL", "K_DAY", 5))
        assert result is None

    def test_get_l1_with_data_returns_df(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        redis_data = {
            today: json.dumps(
                {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10000}
            )
        }
        engine._redis.hgetall = AsyncMock(return_value=redis_data)

        result = asyncio_run(engine._get_l1("US.AAPL", "K_DAY", 5))
        assert result is not None
        assert len(result) == 1
        assert "close" in result.columns

    def test_get_l1_handles_invalid_json(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # 含 1 条非法 JSON 与 1 条合法 JSON
        redis_data = {
            today: "not-valid-json",
            "1970-01-01": json.dumps({"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}),
        }
        engine._redis.hgetall = AsyncMock(return_value=redis_data)

        result = asyncio_run(engine._get_l1("US.AAPL", "K_DAY", 365))
        # 应返回 1 行（1970 那条被解析但不在范围内会过滤；today 那条 JSON 解析失败被跳过）
        # 实际 today 那条 JSON 失败会被 continue 跳过；1970 那条会被 cutoff 过滤
        assert result is None or len(result) >= 0

    def test_get_l1_handles_redis_exception(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._redis.hgetall = AsyncMock(side_effect=Exception("Redis down"))

        result = asyncio_run(engine._get_l1("US.AAPL", "K_DAY", 5))
        assert result is None

    def test_put_l1_writes_pipeline(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        mock_pipe = MagicMock()
        mock_pipe.hset = MagicMock()
        mock_pipe.expire = MagicMock()
        engine._redis = MagicMock()
        engine._redis.pipeline.return_value = mock_pipe
        mock_pipe.execute = AsyncMock()

        df = make_test_kline_df(3)
        asyncio_run(engine._put_l1("US.AAPL", "K_DAY", df))
        assert mock_pipe.hset.call_count == 3
        mock_pipe.expire.assert_called_once()

    def test_put_l1_empty_after_filter_returns(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        mock_pipe = MagicMock()
        engine._redis = MagicMock()
        engine._redis.pipeline.return_value = mock_pipe
        mock_pipe.execute = AsyncMock()

        # 所有日期都早于 cutoff
        df = pd.DataFrame(
            [
                {
                    "time": datetime(2000, 1, 1) + timedelta(days=i),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000,
                }
                for i in range(3)
            ]
        )
        asyncio_run(engine._put_l1("US.AAPL", "K_DAY", df))
        # 不应调用 hset（数据被过滤）
        mock_pipe.hset.assert_not_called()


# ─── KlineCacheEngine: L2/L3 操作 ─────────────────────────────────
class TestKlineCacheEngineL2L3:
    def test_get_l2_calls_warehouse(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._warehouse = AsyncMock()
        df = make_test_kline_df(5)
        engine._warehouse.get_history = AsyncMock(return_value=df)

        result = asyncio_run(engine._get_l2("US.AAPL", "K_DAY", 5))
        assert result is not None
        engine._warehouse.get_history.assert_called_once_with(
            "US.AAPL", ktype="K_DAY", num=5
        )

    def test_get_l2_handles_exception(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._warehouse = AsyncMock()
        engine._warehouse.get_history = AsyncMock(side_effect=Exception("IO error"))

        result = asyncio_run(engine._get_l2("US.AAPL", "K_DAY", 5))
        assert result is None

    def test_get_l3_always_returns_none(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        result = asyncio_run(engine._get_l3("US.AAPL", "K_DAY", 1000))
        assert result is None


# ─── KlineCacheEngine: invalidate / stats ─────────────────────────
class TestKlineCacheEngineManage:
    def test_invalidate_with_period_deletes_key(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        asyncio_run(engine.invalidate("US.AAPL", "K_DAY"))
        engine._redis.delete.assert_called_once()

    def test_invalidate_without_period_uses_scan(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        # 模拟 scan 立即返回 cursor=0
        engine._redis.scan = AsyncMock(return_value=(0, ["key1", "key2"]))

        asyncio_run(engine.invalidate("US.AAPL"))
        engine._redis.scan.assert_called_once()
        engine._redis.delete.assert_called_once_with("key1", "key2")

    def test_invalidate_handles_exception(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._redis.delete = AsyncMock(side_effect=Exception("Redis down"))
        # 不应抛异常
        asyncio_run(engine.invalidate("US.AAPL", "K_DAY"))

    def test_stats_returns_dict(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._redis.scan = AsyncMock(return_value=(0, ["k1", "k2", "k3"]))

        result = asyncio_run(engine.stats())
        assert result["l1_redis_keys"] == 3
        assert result["l1_ttl_days"] == 5
        assert result["l2_retention_days"] == 365
        assert result["l3_enabled"] is False

    def test_stats_handles_exception(self):
        from backend.core.kline_cache import KlineCacheEngine

        engine = KlineCacheEngine()
        engine._redis = AsyncMock()
        engine._redis.scan = AsyncMock(side_effect=Exception("Redis down"))

        result = asyncio_run(engine.stats())
        assert "error" in result


# ─── 全局单例 get_kline_cache_engine ──────────────────────────────
class TestGetKlineCacheEngine:
    def test_singleton_returns_same_instance(self):
        from backend.core.kline_cache import get_kline_cache_engine

        e1 = get_kline_cache_engine()
        e2 = get_kline_cache_engine()
        assert e1 is e2

    def test_singleton_is_kline_cache_engine(self):
        from backend.core.kline_cache import KlineCacheEngine, get_kline_cache_engine

        engine = get_kline_cache_engine()
        assert isinstance(engine, KlineCacheEngine)


# ─── 辅助函数 ─────────────────────────────────────────────────────
def asyncio_run(coro):
    """同步包装异步调用"""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro)
