"""BE-ARCH-07h-2: Futu broker/kline 推送桥接到 quant:* 频道的主服务消费者测试

覆盖:
- SubscriptionService 的 broker/kline 进程内缓存 TTL 行为 (get/put)
- _run_poly_ingest 协程正确订阅 quant:{prefix}:{symbol} 并回灌 _PolyCache
- 订阅频道名与子服务桥接的目标频道 (quant:broker:{ticker} / quant:kline:{ticker}) 一致
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.services.datasource.subscription import (
    SubscriptionService,
    _PolyCache,
    _run_poly_ingest,
)


def test_poly_cache_ttl_and_upper():
    cache = _PolyCache(ttl_sec=0.05)
    cache.put("hk.00700", {"ticker": "HK.00700", "x": 1})
    # 大写查询一致
    assert cache.get("HK.00700") == {"ticker": "HK.00700", "x": 1}
    # TTL 过期返回 None
    import time

    time.sleep(0.08)
    assert cache.get("HK.00700") is None


def test_subscription_service_broker_kline_interface():
    svc = SubscriptionService()
    svc.put_broker("HK.00700", {"ticker": "HK.00700", "bid_brokers": ["A"]})
    svc.put_kline("US.AAPL", {"ticker": "US.AAPL", "close": 200.0})
    assert svc.get_broker("hk.00700")["bid_brokers"] == ["A"]
    assert svc.get_kline("US.AAPL")["close"] == 200.0
    assert svc.get_broker("US.TSLA") is None  # 未订阅标的


async def test_run_poly_ingest_subscribes_correct_channel_and_backfills():
    """验证 ingest 协程订阅目标频道名，并将消息回灌到 _PolyCache。"""
    cache = _PolyCache()

    # 构造 fake pubsub: subscribe 记录频道名, listen 产出一条 broker 消息后结束
    class _FakePubsub:
        def __init__(self):
            self.channels = []

        async def subscribe(self, ch):
            self.channels.append(ch)

        async def listen(self):
            yield {"type": "message", "data": '{"ticker": "HK.00700", "bid_brokers": ["X"]}'}
            # 第二条为无效 (无 ticker)，应被忽略
            yield {"type": "message", "data": "not-json"}
            # 终止 listen
            await asyncio.sleep(0)
            return

        async def unsubscribe(self):
            pass

    class _FakeRedis:
        def pubsub(self):
            return _FakePubsub()

    fake_redis = _FakeRedis()
    # mock _redis 工厂 (async def → AsyncMock 返回 fake_redis)
    import backend.services.datasource.subscription as sub_mod

    orig_redis = sub_mod._redis
    sub_mod._redis = AsyncMock(return_value=fake_redis)

    try:
        task = asyncio.create_task(_run_poly_ingest(["HK.00700"], cache, "broker"))
        # 等待协程至少消费一条消息
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass
    finally:
        sub_mod._redis = orig_redis

    # 回灌生效
    assert cache.get("HK.00700") == {"ticker": "HK.00700", "bid_brokers": ["X"]}


async def test_run_poly_ingest_channel_name_recorded():
    """显式断言订阅的频道名与子服务桥接目标完全一致 (quant:broker:/quant:kline:)。"""
    cache = _PolyCache()
    recorded = []

    class _FakePubsub:
        async def subscribe(self, ch):
            recorded.append(ch)

        async def listen(self):
            # 异步生成器：先让出控制权使 task 可干净响应 cancel，再结束（不产出消息）
            await asyncio.sleep(0.05)
            return
            yield  # 使函数成为异步生成器 (async for 要求 __aiter__)

        async def unsubscribe(self):
            pass

    class _FakeRedis:
        def pubsub(self):
            return _FakePubsub()

    import backend.services.datasource.subscription as sub_mod

    orig = sub_mod._redis
    sub_mod._redis = AsyncMock(return_value=_FakeRedis())
    task = asyncio.create_task(_run_poly_ingest(["US.AAPL", "HK.00700"], cache, "kline"))
    # 等待 listen 自然结束 (先 await 0.05s 让出，再 return 使 async for 退出)
    await asyncio.sleep(0.15)
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        # 确认协程无未捕获异常
        task.result()
    sub_mod._redis = orig

    assert recorded == ["quant:kline:US.AAPL", "quant:kline:HK.00700"]


@pytest.mark.asyncio
async def test_subscription_service_start_broker_kline_ingest_returns_task_or_none():
    svc = SubscriptionService()
    # 空标的 -> None
    assert svc.start_broker_ingest([]) is None
    assert svc.start_kline_ingest([]) is None
    # 有标的 -> 返回 Task
    t1 = svc.start_broker_ingest(["HK.00700"])
    t2 = svc.start_kline_ingest(["US.AAPL"])
    assert isinstance(t1, asyncio.Task)
    assert isinstance(t2, asyncio.Task)
    assert svc._broker_task is t1 and svc._kline_task is t2
    # 重复调用取消旧任务
    t3 = svc.start_broker_ingest(["HK.00700"])
    assert t1.cancelled() or t1.done() or t1.cancelling()
    svc.stop_poly_ingest()
    assert svc._broker_task is None and svc._kline_task is None
