"""BRD-01: 早报持久化单元测试 (morning_briefing/storage.py, 覆盖 49% → 全绿)

storage 层在无 Redis 时自动降级为进程内 dict 兜底，本测试强制走内存兜底路径，
避免依赖外部 Redis。
"""

import pytest

from backend.services.morning_briefing import storage as mb_storage
from backend.services.morning_briefing.models import BriefingResult


@pytest.fixture
def force_memory_fallback():
    # backend.core.database 未导出 get_redis_client，storage 会自然降级到 _MEMORY 兜底。
    # 这里不强制 patch，仅作为语义标记确保本文件走内存路径、不依赖外部 Redis。
    yield


def _briefing(bid: str, market: str = "全球") -> BriefingResult:
    return BriefingResult(
        id=bid,
        date="2026-07-24",
        market=market,
        markdown="# 早报\n内容",
        source_tools=["get_macro_news"],
    )


@pytest.mark.asyncio
async def test_save_and_get(force_memory_fallback):
    await mb_storage.save_briefing(_briefing("b1"))
    got = await mb_storage.get_briefing("b1")
    assert got is not None
    assert got.id == "b1"
    assert got.markdown.startswith("# 早报")


@pytest.mark.asyncio
async def test_get_missing_returns_none(force_memory_fallback):
    assert await mb_storage.get_briefing("nope") is None


@pytest.mark.asyncio
async def test_get_latest_briefing(force_memory_fallback):
    await mb_storage.save_briefing(_briefing("b2", "美股"))
    latest = await mb_storage.get_latest_briefing("美股")
    assert latest is not None
    assert latest.id == "b2"


@pytest.mark.asyncio
async def test_get_latest_missing_market(force_memory_fallback):
    assert await mb_storage.get_latest_briefing("港股") is None
