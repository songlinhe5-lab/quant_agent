"""BE-ARCH-07l③：后台心跳循环须周期性刷新 Redis，避免 TTL 到期后节点被判 dead。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import data_subservice.main as main_mod
from data_subservice._internal.service_registry import ServiceRegistry


@pytest.fixture
def fake_redis():
    return MagicMock()


@pytest.mark.asyncio
async def test_heartbeat_loop_refreshes_periodically(fake_redis):
    """心跳循环应在间隔后至少调用一次 registry.heartbeat。"""
    registry = ServiceRegistry(fake_redis)
    registry.heartbeat = AsyncMock(return_value=True)

    # 强制短间隔以加速测试
    old_interval = main_mod._HEARTBEAT_INTERVAL
    main_mod._HEARTBEAT_INTERVAL = 0.05
    try:
        task = asyncio.create_task(main_mod._heartbeat_loop("ds-test", registry))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        main_mod._HEARTBEAT_INTERVAL = old_interval

    assert registry.heartbeat.await_count >= 1
    registry.heartbeat.assert_any_await("ds-test")


@pytest.mark.asyncio
async def test_heartbeat_loop_exits_on_cancel(fake_redis):
    """取消心跳任务后循环应干净退出，不抛未捕获异常。"""
    registry = ServiceRegistry(fake_redis)
    registry.heartbeat = AsyncMock(return_value=True)

    old_interval = main_mod._HEARTBEAT_INTERVAL
    main_mod._HEARTBEAT_INTERVAL = 0.01
    try:
        task = asyncio.create_task(main_mod._heartbeat_loop("ds-test", registry))
        await asyncio.sleep(0.05)
        task.cancel()
        # 循环捕获 CancelledError 后 break，await 应正常返回（无未捕获异常）
        await task
        assert task.done()
    finally:
        main_mod._HEARTBEAT_INTERVAL = old_interval
