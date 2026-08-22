"""
情绪追踪器单元测试
覆盖: backend/services/sentiment_tracker.py
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


from backend.services.macro.sentiment_tracker import SentimentTracker, sentiment_tracker


class TestSentimentTracker:
    """SentimentTracker 单元测试（直接、确定性地测试 _run_once，避免依赖 daemon 的 sleep 取消计时）"""

    @pytest.fixture
    def tracker(self):
        return SentimentTracker()

    async def test_track_daemon_lock_not_acquired_skips_iteration(self, tracker):
        """分布式锁未获取时，_run_once 应返回 False（由 daemon 决定跳过本轮）"""
        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=False)),
        ):
            result = await tracker._run_once()

        assert result is False

    async def test_track_daemon_extracts_vix_and_cpc_successfully(self, tracker):
        """VIX 与 P/C 缓存存在时应解析为浮点数并写入数据库"""
        vix_cache = json.dumps([{"Close": 18.5}, {"Close": 19.2}])
        cpc_cache = json.dumps([{"Close": 0.85}, {"Close": 0.92}])

        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            if key == "yf_macro_cache_^VIX":
                return vix_cache
            if key == "yf_macro_cache_^CPC":
                return cpc_cache
            return None

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            # 数据库为同步 IO，测试内同步执行避免起线程，逻辑等价
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
        ):
            result = await tracker._run_once()

        # 已获取锁且完成落库
        assert result is True
        # 验证 DB 写入
        mock_db.add.assert_called_once()
        record = mock_db.add.call_args[0][0]
        assert record.vix_value == 19.2
        assert record.pc_ratio == 0.92
        # credit_spread = 2.0 + (19.2 / 10.0) = 3.92
        assert record.credit_spread == 3.92
        mock_db.commit.assert_called_once()

    async def test_track_daemon_missing_vix_cache_keeps_none(self, tracker):
        """VIX/P-C 缓存均缺失时应跳过打点（零幻觉红线），不写入全 None 记录"""
        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            return None

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
        ):
            result = await tracker._run_once()

        # 零幻觉红线：源数据均缺失时跳过打点，不调用 db.add，避免污染历史序列
        assert result is True
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    async def test_track_daemon_handles_multiindex_close_key(self, tracker):
        """当 yfinance 返回的 records 最后一条无 Close 键（MultiIndex 形式）时，应回退解析"""
        # 模拟 yfinance 偶发的 MultiIndex 列名 "('Close', '^VIX')"
        vix_cache = json.dumps([{"('Close', '^VIX')": 22.8}])
        cpc_cache = json.dumps([{"Close": 1.1}])

        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            if key == "yf_macro_cache_^VIX":
                return vix_cache
            if key == "yf_macro_cache_^CPC":
                return cpc_cache
            return None

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
        ):
            result = await tracker._run_once()

        assert result is True
        record = mock_db.add.call_args[0][0]
        assert record.vix_value == 22.8
        assert record.pc_ratio == 1.1

    async def test_track_daemon_handles_db_exception_resilient(self, tracker):
        """数据库写入异常时不应崩溃，_run_once 应吞掉异常并返回 True（daemon 继续下一轮）"""

        async def fake_get(key):
            return None

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", side_effect=RuntimeError("db down")),
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
        ):
            result = await tracker._run_once()

        # DB 异常被吞掉，返回 True（已获取锁），daemon 继续调度下一轮
        assert result is True

    def test_global_singleton_exists(self):
        """全局单例 sentiment_tracker 应可正常导入"""
        assert hasattr(sentiment_tracker, "track_daemon")

    async def test_track_daemon_extracts_retail_heat_factor(self, tracker):
        """C.1: 经 fetch_sentiment 拉取 ApeWisdom 热度 → 派生市场级热度因子落库"""
        vix_cache = json.dumps([{"Close": 18.5}, {"Close": 19.2}])
        cpc_cache = json.dumps([{"Close": 0.85}, {"Close": 0.92}])
        heat_payload = {
            "data": [
                {"ticker": "SPY", "mentions": 188, "mentions_24h_ago": 323, "mentions_delta_pct": -0.418},
                {"ticker": "NVDA", "mentions": 147, "mentions_24h_ago": 82, "mentions_delta_pct": 0.7927},
            ]
        }

        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            if key == "yf_macro_cache_^VIX":
                return vix_cache
            if key == "yf_macro_cache_^CPC":
                return cpc_cache
            return None

        async def fake_fetch_sentiment(action, **params):
            return heat_payload

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
            # mock data_source_router.fetch_sentiment 返回 ApeWisdom 热度
            patch(
                "backend.services.datasource.router.data_source_router.fetch_sentiment",
                new=AsyncMock(side_effect=fake_fetch_sentiment),
            ),
        ):
            result = await tracker._run_once()

        assert result is True
        record = mock_db.add.call_args[0][0]
        # 热度因子: (-0.418 + 0.7927) / 2 = 0.18735 → round 0.1874
        assert record.retail_heat_change_pct == pytest.approx(0.1874, abs=1e-3)
        assert record.retail_heat_total == 188 + 147

    async def test_track_daemon_heat_source_failure_degrades(self, tracker):
        """C.1: ApeWisdom 取数失败时热度因子降级为 None（不污染历史序列）"""
        vix_cache = json.dumps([{"Close": 19.2}])
        cpc_cache = json.dumps([{"Close": 0.92}])

        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            if key == "yf_macro_cache_^VIX":
                return vix_cache
            if key == "yf_macro_cache_^CPC":
                return cpc_cache
            return None

        with (
            patch("backend.services.macro.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.macro.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.macro.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.macro.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())
            ),
            # fetch_sentiment 抛异常 → 热度降级 None
            patch(
                "backend.services.datasource.router.data_source_router.fetch_sentiment",
                new=AsyncMock(side_effect=RuntimeError("router down")),
            ),
        ):
            result = await tracker._run_once()

        assert result is True
        record = mock_db.add.call_args[0][0]
        assert record.retail_heat_change_pct is None  # 降级,不臆造
        assert record.retail_heat_total is None
