#!/usr/bin/env python3
"""快速检查缓存状态和调用计数"""

import asyncio
import time

from backend.core.redis_client import l1_cached_redis, redis_client
from backend.services.datasource.call_metrics_store import _bucket_key, _local_date_key
from backend.services.yfinance import yf_service


async def check():
    print("=" * 60)
    print("🔍 缓存状态与调用计数诊断")
    print("=" * 60)

    # 1. L1 Cache
    print("\n📦 L1 本地缓存")
    if hasattr(l1_cached_redis, "_cache"):
        cache_dict = l1_cached_redis._cache
        print(f"   条目数：{len(cache_dict)}")
        print(f"   最大容量：{l1_cached_redis.max_size}")

        # 检查 AAPL 相关
        aapl_keys = [k for k in cache_dict.keys() if "AAPL" in k.upper()]
        if aapl_keys:
            print(f"   ✅ AAPL 缓存条目：{len(aapl_keys)}")
            for k in aapl_keys[:3]:
                val, exp = cache_dict[k]
                ttl = exp - time.time()
                print(f"      - {k[:50]}... (TTL 剩余：{ttl:.1f}s)")
        else:
            print(f"   ❌ 无 AAPL 缓存")

    # 2. YFinance Cache
    print("\n📦 YFinance 内存缓存")
    print(f"   条目数：{len(yf_service._cache)}")
    aapl_keys = [k for k in yf_service._cache.keys() if "AAPL" in k.upper()]
    if aapl_keys:
        print(f"   ✅ AAPL 缓存条目：{len(aapl_keys)}")
        for k in aapl_keys[:3]:
            ts, data = yf_service._cache[k]
            age = time.time() - ts
            print(f"      - {k[:50]}... (年龄：{age:.1f}s)")
    else:
        print(f"   ❌ 无 AAPL 缓存")

    # 3. Redis Call Metrics
    print("\n📊 Redis 调用计数 (今日)")
    date_key = _local_date_key()
    bucket = _bucket_key("yfinance", date_key)
    print(f"   日期：{date_key}")
    print(f"   Key: {bucket}")

    metrics = await redis_client.hgetall(bucket)
    if metrics:
        print("   ✅ 有调用记录:")
        for field, value in sorted(metrics.items()):
            print(f"      {field}: {value}")
    else:
        print("   ❌ 无调用记录 (今日尚未发起业务调用)")

    # 4. 分析
    print("\n" + "=" * 60)
    print("🎯 结论")
    print("=" * 60)

    has_l1_aapl = hasattr(l1_cached_redis, "_cache") and any("AAPL" in k.upper() for k in l1_cached_redis._cache.keys())
    has_yf_aapl = len(aapl_keys) > 0 if "aapl_keys" in locals() else False
    has_redis_calls = bool(metrics)

    if has_l1_aapl or has_yf_aapl:
        print("\n⚠️  发现 AAPL 缓存！")
        print("   test-link 可能命中了本地缓存，导致延迟极低")
        print("   但这不影响'今日调用'统计，因为 test-link 不计入业务 calls")

    if not has_redis_calls:
        print("\nℹ️  今日尚无业务调用")
        print("   '今日调用'显示为 0 是正常的")
        print("   test-link 探针调用单独统计在 probe_calls 字段")

    print("\n💡 如何验证:")
    print("   1. 在前端查询个股行情 (如 AAPL)")
    print("   2. 观察 '今日调用' 是否增加")
    print("   3. 如果增加，说明业务调用正常统计")


if __name__ == "__main__":
    asyncio.run(check())
