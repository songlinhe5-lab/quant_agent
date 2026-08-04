#!/usr/bin/env python3
"""
数据源缓存命中率诊断工具

用途：
1. 检查 L1 本地缓存状态
2. 检查 YFinance 内存缓存
3. 检查 Redis 调用计数
4. 验证 test-link 是否真的绕过所有缓存
"""

import asyncio
import sys
import time
from datetime import datetime

# 添加项目根目录到 path
sys.path.insert(0, "/Users/stephenhe/Development/workspace/quant_agent")


async def check_l1_cache():
    """检查 LocalL1Cache 状态"""
    print("\n" + "=" * 60)
    print("🔍 L1 本地缓存检查")
    print("=" * 60)

    try:
        from backend.core.redis_client import l1_cached_redis

        # 尝试获取 AAPL 相关缓存
        test_keys = [
            "quant:cache:yfinance:AAPL",
            "quant:cache:quote:AAPL",
            "AAPL",
        ]

        print(f"\nL1 Cache 实例：{l1_cached_redis}")
        print(f"L1 Cache 类型：{type(l1_cached_redis)}")

        # 检查内部字典大小
        if hasattr(l1_cached_redis, "_cache"):
            cache_dict = l1_cached_redis._cache
            print(f"\nL1 缓存条目数：{len(cache_dict)}")
            print(f"L1 缓存最大容量：{l1_cached_redis.max_size}")
            print(f"L1 默认 TTL: {l1_cached_redis.default_ttl}s")

            # 显示前 10 个 key
            if cache_dict:
                print("\n前 10 个缓存 key:")
                for i, (key, (value, exp)) in enumerate(list(cache_dict.items())[:10]):
                    ttl_remaining = exp - time.time()
                    print(f"  {i + 1}. {key[:50]}... (TTL 剩余：{ttl_remaining:.1f}s)")

        # 尝试读取 AAPL 缓存
        for key in test_keys:
            val = await l1_cached_redis.get(key)
            if val:
                print(f"\n✅ 命中 L1 缓存：{key}")
                print(f"   值：{str(val)[:100]}...")
            else:
                print(f"\n❌ 未命中 L1 缓存：{key}")

    except Exception as e:
        print(f"❌ L1 缓存检查失败：{e}")


async def check_yfinance_memory_cache():
    """检查 YFinance 服务的内存缓存"""
    print("\n" + "=" * 60)
    print("🔍 YFinance 内存缓存检查")
    print("=" * 60)

    try:
        from backend.services.yfinance import yf_service

        print(f"\nYFinance Service 实例：{yf_service}")
        print(f"主缓存条目数：{len(yf_service._cache)}")
        print(f"主缓存最大容量：500 (硬编码)")
        print(f"主缓存 TTL: 600s (10 分钟)")
        print(f"错误黑名单条目数：{len(yf_service._error_cache)}")

        # 显示缓存中的 key
        if yf_service._cache:
            print("\n缓存中的 key (前 10 个):")
            for i, key in enumerate(list(yf_service._cache.keys())[:10]):
                ts, data = yf_service._cache[key]
                age = time.time() - ts
                print(f"  {i + 1}. {key[:60]}... (年龄：{age:.1f}s)")

        # 检查是否有 AAPL
        aapl_keys = [k for k in yf_service._cache.keys() if "AAPL" in k.upper()]
        if aapl_keys:
            print(f"\n✅ 发现 AAPL 缓存条目：{len(aapl_keys)} 个")
            for key in aapl_keys[:3]:
                ts, data = yf_service._cache[key]
                print(f"   - {key[:60]}... (年龄：{time.time() - ts:.1f}s)")
        else:
            print(f"\n❌ 未发现 AAPL 缓存条目")

    except Exception as e:
        print(f"❌ YFinance 缓存检查失败：{e}")


async def check_redis_call_metrics():
    """检查 Redis 中的调用计数"""
    print("\n" + "=" * 60)
    print("🔍 Redis 调用计数检查")
    print("=" * 60)

    try:
        from backend.core.redis_client import redis_client
        from backend.services.datasource.call_metrics_store import _bucket_key, _local_date_key

        date_key = _local_date_key()
        source = "yfinance"
        bucket_key = _bucket_key(source, date_key)

        print(f"\n日期：{date_key}")
        print(f"Redis Key: {bucket_key}")

        # 读取所有字段
        metrics = await redis_client.hgetall(bucket_key)

        if metrics:
            print("\n✅ Redis 中有调用记录:")
            for field, value in sorted(metrics.items()):
                print(f"   {field}: {value}")
        else:
            print("\n❌ Redis 中无调用记录 (今日尚未发起业务调用)")

        # 刷新 TTL
        ttl = await redis_client.ttl(bucket_key)
        print(f"\nKey TTL: {ttl}s ({ttl / 86400:.1f}天)")

    except Exception as e:
        print(f"❌ Redis 调用计数检查失败：{e}")


async def simulate_test_link():
    """模拟 test-link 调用，观察缓存行为"""
    print("\n" + "=" * 60)
    print("🔍 模拟 test-link 调用")
    print("=" * 60)

    try:
        from backend.services.datasource import datasource_registry
        from backend.services.datasource.call_metrics_store import call_metrics

        source = datasource_registry.get("yfinance")
        if not source:
            print("❌ yfinance 数据源未注册")
            return

        print(f"\n数据源实例：{source}")
        print(f"capabilities: {getattr(source, 'capabilities', [])}")

        # 记录调用前的 Redis 计数
        before_metrics = await call_metrics.get_today("yfinance")
        print(f"\n调用前 Redis 计数:")
        if before_metrics:
            print(f"   calls: {before_metrics.get('calls', 0)}")
            print(f"   probe_calls: {before_metrics.get('probe_calls', 0)}")
        else:
            print("   (无记录)")

        # 发起 test-link 探测
        print("\n发起 test-link 探测...")
        start = time.perf_counter()

        # 模拟 test-link 的逻辑
        caps = getattr(source, "capabilities", [])
        caps_upper = {c.upper(): c for c in caps}

        if "QUOTE" in caps_upper:
            probe_action = caps_upper["QUOTE"]
            probe_params = {"ticker": "AAPL", "skip_cache": True, "ttl": 60}

            print(f"   Action: {probe_action}")
            print(f"   Params: {probe_params}")

            probe_start = time.perf_counter()
            result = await source.fetch(probe_action, probe_params)
            latency_ms = round((time.perf_counter() - probe_start) * 1000, 2)

            print(f"\n✅ 探测完成")
            print(f"   延迟：{latency_ms}ms")
            print(f"   结果状态：{result.get('status', 'unknown')}")

        # 记录调用后的 Redis 计数
        after_metrics = await call_metrics.get_today("yfinance")
        print(f"\n调用后 Redis 计数:")
        if after_metrics:
            print(f"   calls: {after_metrics.get('calls', 0)}")
            print(f"   probe_calls: {after_metrics.get('probe_calls', 0)}")
            print(f"   probe_success: {after_metrics.get('probe_success', 0)}")
        else:
            print("   (仍无记录)")

        # 分析变化
        if before_metrics and after_metrics:
            calls_diff = after_metrics.get("calls", 0) - before_metrics.get("calls", 0)
            probe_diff = after_metrics.get("probe_calls", 0) - before_metrics.get("probe_calls", 0)

            print(f"\n📊 变化分析:")
            print(f"   业务 calls 增量：{calls_diff} (应该=0，test-link 不计入)")
            print(f"   探针 calls 增量：{probe_diff} (应该=1)")

            if calls_diff == 0 and probe_diff == 1:
                print("\n✅ 符合预期！test-link 正确隔离了业务指标")
            else:
                print("\n❌ 异常！指标隔离失败")

    except Exception as e:
        print(f"❌ 模拟 test-link 失败：{e}")
        import traceback

        traceback.print_exc()


async def main():
    """主诊断流程"""
    print("\n" + "=" * 60)
    print("🔬 数据源缓存命中率诊断报告")
    print(f"⏰ 诊断时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    await check_l1_cache()
    await check_yfinance_memory_cache()
    await check_redis_call_metrics()
    await simulate_test_link()

    print("\n" + "=" * 60)
    print("🎯 诊断完成")
    print("=" * 60)
    print("\n💡 建议:")
    print("1. 如果 L1/YF 缓存中有 AAPL，说明 test-link 可能命中缓存")
    print("2. 如果 Redis probe_calls 增加但 calls 不变，说明指标隔离正常")
    print("3. 如果想看到 calls 增加，需要发起真实业务请求 (如查询个股行情)")


if __name__ == "__main__":
    asyncio.run(main())
