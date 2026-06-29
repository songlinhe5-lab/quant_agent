"""
情绪追踪器单元测试
覆盖: backend/services/sentiment_tracker.py
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


from backend.services.sentiment_tracker import SentimentTracker, sentiment_tracker


def _cancel_after_sleep(counts: dict, target: int):
    """构造一个 side_effect：在第 N 次 sleep 后抛 CancelledError 以跳出 while True"""

    async def _side_effect(delay, *args, **kwargs):
        counts["n"] += 1
        if counts["n"] >= target:
            raise asyncio.CancelledError()

    return _side_effect


class TestSentimentTracker:
    """SentimentTracker 单元测试"""

    @pytest.fixture
    def tracker(self):
        return SentimentTracker()

    async def test_track_daemon_lock_not_acquired_skips_iteration(self, tracker):
        """分布式锁未获取时应跳过本次迭代，进入下一轮"""
        sleep_counts = {"n": 0}
        with (
            patch("backend.services.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=False)),
            patch(
                "backend.services.sentiment_tracker.asyncio.sleep",
                new=AsyncMock(side_effect=_cancel_after_sleep(sleep_counts, 2)),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await tracker.track_daemon()

        # 第一次 sleep(30) 初始延迟 + 第二次 sleep(60) 锁未获取 → CancelledError
        assert sleep_counts["n"] == 2

    async def test_track_daemon_extracts_vix_and_cpc_successfully(self, tracker):
        """VIX 与 P/C 缓存存在时应解析为浮点数并写入数据库"""
        vix_cache = json.dumps([{"Close": 18.5}, {"Close": 19.2}])
        cpc_cache = json.dumps([{"Close": 0.85}, {"Close": 0.92}])

        sleep_counts = {"n": 0}
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
            patch("backend.services.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.sentiment_tracker.asyncio.sleep",
                new=AsyncMock(side_effect=_cancel_after_sleep(sleep_counts, 2)),
            ),
            patch("backend.services.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())),
        ):
            with pytest.raises(asyncio.CancelledError):
                await tracker.track_daemon()

        # 验证 DB 写入
        mock_db.add.assert_called_once()
        record = mock_db.add.call_args[0][0]
        assert record.vix_value == 19.2
        assert record.pc_ratio == 0.92
        # credit_spread = 2.0 + (19.2 / 10.0) = 3.92
        assert record.credit_spread == 3.92
        mock_db.commit.assert_called_once()

    async def test_track_daemon_missing_vix_cache_keeps_none(self, tracker):
        """VIX 缓存不存在时 vix_val 与 credit_spread 应为 None"""
        sleep_counts = {"n": 0}
        mock_db = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)

        async def fake_get(key):
            return None

        with (
            patch("backend.services.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.sentiment_tracker.asyncio.sleep",
                new=AsyncMock(side_effect=_cancel_after_sleep(sleep_counts, 2)),
            ),
            patch("backend.services.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())),
        ):
            with pytest.raises(asyncio.CancelledError):
                await tracker.track_daemon()

        record = mock_db.add.call_args[0][0]
        assert record.vix_value is None
        assert record.pc_ratio is None
        assert record.credit_spread is None

    async def test_track_daemon_handles_multiindex_close_key(self, tracker):
        """当 yfinance 返回的 records 最后一条无 Close 键（MultiIndex 形式）时，应回退解析"""
        # 模拟 yfinance 偶发的 MultiIndex 列名 "('Close', '^VIX')"
        vix_cache = json.dumps([{"('Close', '^VIX')": 22.8}])
        cpc_cache = json.dumps([{"Close": 1.1}])

        sleep_counts = {"n": 0}
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
            patch("backend.services.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.sentiment_tracker.SessionLocal", return_value=mock_session_ctx),
            patch(
                "backend.services.sentiment_tracker.asyncio.sleep",
                new=AsyncMock(side_effect=_cancel_after_sleep(sleep_counts, 2)),
            ),
            patch("backend.services.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())),
        ):
            with pytest.raises(asyncio.CancelledError):
                await tracker.track_daemon()

        record = mock_db.add.call_args[0][0]
        assert record.vix_value == 22.8
        assert record.pc_ratio == 1.1

    async def test_track_daemon_handles_db_exception_resilient(self, tracker):
        """数据库写入异常时不应崩溃，应继续进入下一轮循环"""
        sleep_counts = {"n": 0}

        async def fake_get(key):
            return None

        with (
            patch("backend.services.sentiment_tracker.redis_client.set", new=AsyncMock(return_value=True)),
            patch("backend.services.sentiment_tracker.redis_client.get", new=AsyncMock(side_effect=fake_get)),
            patch("backend.services.sentiment_tracker.SessionLocal", side_effect=RuntimeError("db down")),
            patch(
                "backend.services.sentiment_tracker.asyncio.sleep",
                new=AsyncMock(side_effect=_cancel_after_sleep(sleep_counts, 2)),
            ),
            patch("backend.services.sentiment_tracker.asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())),
        ):
            with pytest.raises(asyncio.CancelledError):
                await tracker.track_daemon()

        # DB 异常被吞掉，循环继续，第二次 sleep 触发 CancelledError
        assert sleep_counts["n"] == 2

    def test_global_singleton_exists(self):
        """全局单例 sentiment_tracker 应可正常导入"""
        assert hasattr(sentiment_tracker, "track_daemon")
