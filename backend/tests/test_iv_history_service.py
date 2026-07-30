"""IV 历史序列服务单测 (OPTION-04, 零幻觉契约)。

覆盖:
- record_iv_snapshot: 拒绝非法/负/None IV (不落库); 合法 IV 写入 DB + 追加 Redis
- get_iv_history: Redis 命中优先返回; Redis 异常时回源 DB 并升序返回
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.iv_history_service import get_iv_history, record_iv_snapshot


@pytest.mark.asyncio
async def test_record_iv_snapshot_rejects_invalid_iv():
    """负/零/None IV 不得落库 (零幻觉: 防止污染历史序列)"""
    with patch("backend.app.iv_history_service.SessionLocal") as mock_session:
        await record_iv_snapshot("AAPL", -0.1)
        await record_iv_snapshot("AAPL", 0)
        await record_iv_snapshot("AAPL", None)
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_record_iv_snapshot_valid_writes_db_and_cache():
    """合法 IV 应写入 DB 并追加 Redis 缓存"""
    fake_db = MagicMock()
    fake_db.__enter__.return_value = fake_db
    fake_db.__exit__.return_value = False
    with (
        patch("backend.app.iv_history_service.SessionLocal", return_value=fake_db),
        patch("backend.app.iv_history_service.redis_client") as mock_redis,
    ):
        mock_redis.rpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        await record_iv_snapshot("AAPL", 0.30)
        fake_db.add.assert_called_once()
        fake_db.commit.assert_called_once()
        mock_redis.rpush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_iv_history_redis_priority():
    """Redis 命中优先返回, 不回源 DB"""
    with (
        patch("backend.app.iv_history_service.redis_client") as mock_redis,
        patch("backend.app.iv_history_service.SessionLocal") as mock_session,
    ):
        mock_redis.lrange = AsyncMock(return_value=["0.20", "0.25", "0.30"])
        result = await get_iv_history("AAPL")
        assert result == [0.20, 0.25, 0.30]
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_get_iv_history_redis_failure_falls_back_to_db():
    """Redis 异常时回源 DB 且升序返回"""
    fake_db = MagicMock()
    fake_db.__enter__.return_value = fake_db
    fake_db.__exit__.return_value = False
    fake_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        (0.18,),
        (0.22,),
        (0.25,),
    ]
    with (
        patch("backend.app.iv_history_service.redis_client") as mock_redis,
        patch("backend.app.iv_history_service.SessionLocal", return_value=fake_db),
    ):
        mock_redis.lrange = AsyncMock(side_effect=RuntimeError("redis down"))
        result = await get_iv_history("AAPL")
        assert result == [0.18, 0.22, 0.25]
