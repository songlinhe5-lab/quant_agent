"""MRKT-01: 市场复盘 Redis 存储层单元测试 (storage.py, 覆盖 28% → 全绿)"""

from unittest.mock import patch

import pytest

from backend.services.market_review import storage as mr_storage
from backend.services.market_review.models import (
    IndexSnapshot,
    MarketDailyReview,
    MarketType,
)


class FakeRedis:
    """内存版 Redis，仅实现 storage 用到的命令。"""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        existed = key in self.data
        self.data.pop(key, None)
        return 1 if existed else 0

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {})
        self.zsets[key].update(mapping)
        return 1

    async def zrevrange(self, key, start, end):
        z = self.zsets.get(key, {})
        items = sorted(z.items(), key=lambda kv: kv[1], reverse=True)
        return [m for m, _ in items[start : end + 1]]

    async def zremrangebyrank(self, key, start, end):
        return 0

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)
        return 1


@pytest.fixture
def fake_redis():
    r = FakeRedis()
    with patch.object(mr_storage, "redis_client", r):
        yield r


def _review(date: str, market: MarketType = MarketType.A_SHARE) -> MarketDailyReview:
    return MarketDailyReview(
        date=date,
        market=market,
        indices=[IndexSnapshot(name="上证指数", code="000001.SH", close=3200.0, change_pct=1.0)],
    )


@pytest.mark.asyncio
async def test_save_and_get_roundtrip(fake_redis):
    rev = _review("2026-07-24")
    key = await mr_storage.save_market_review(rev)
    assert key == "quant:market_review:A股:2026-07-24"
    got = await mr_storage.get_market_review("2026-07-24", MarketType.A_SHARE)
    assert got is not None
    assert got.date == "2026-07-24"
    assert got.indices[0].name == "上证指数"


@pytest.mark.asyncio
async def test_get_missing_returns_none(fake_redis):
    assert await mr_storage.get_market_review("1999-01-01", MarketType.HK) is None


@pytest.mark.asyncio
async def test_get_recent_reviews_desc_order(fake_redis):
    await mr_storage.save_market_review(_review("2026-07-22"))
    await mr_storage.save_market_review(_review("2026-07-24"))
    await mr_storage.save_market_review(_review("2026-07-23"))
    recent = await mr_storage.get_recent_reviews(MarketType.A_SHARE, days=3)
    dates = [r.date for r in recent]
    assert dates == ["2026-07-24", "2026-07-23", "2026-07-22"]  # 降序


@pytest.mark.asyncio
async def test_get_latest_review(fake_redis):
    await mr_storage.save_market_review(_review("2026-07-22"))
    await mr_storage.save_market_review(_review("2026-07-24"))
    latest = await mr_storage.get_latest_review(MarketType.A_SHARE)
    assert latest is not None
    assert latest.date == "2026-07-24"


@pytest.mark.asyncio
async def test_list_available_dates(fake_redis):
    await mr_storage.save_market_review(_review("2026-07-22"))
    await mr_storage.save_market_review(_review("2026-07-24"))
    dates = await mr_storage.list_available_dates(MarketType.A_SHARE)
    assert "2026-07-24" in dates


@pytest.mark.asyncio
async def test_delete_market_review(fake_redis):
    await mr_storage.save_market_review(_review("2026-07-24"))
    deleted = await mr_storage.delete_market_review("2026-07-24", MarketType.A_SHARE)
    assert deleted is True
    assert await mr_storage.get_market_review("2026-07-24", MarketType.A_SHARE) is None
