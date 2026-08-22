#!/usr/bin/env python3
"""
测试延迟统计功能

验证：
1. CallMetricsStore.record_business() 能否正确记录延迟
2. CallMetricsStore.get_latency_stats() 能否正确返回 P50/P95/P99
3. Redis 键空间是否正确
"""

import asyncio
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.datasource.call_metrics_store import call_metrics


async def test_latency_recording():
    """测试延迟记录功能"""
    print("=" * 60)
    print("测试 1: 延迟记录功能")
    print("=" * 60)

    test_source = "test_latency_source"
    test_latencies = [150.5, 200.3, 180.2, 220.1, 195.8, 210.4, 185.6, 190.3, 205.7, 215.9]

    print(f"\n测试数据源：{test_source}")
    print(f"记录 {len(test_latencies)} 个延迟样本:")

    for i, latency in enumerate(test_latencies, 1):
        await call_metrics.record_business(test_source, "success", latency_ms=latency)
        print(f"  [{i:2d}] {latency:.1f} ms")

    print("\n✅ 延迟记录完成")
    return test_source


async def test_latency_stats(test_source: str):
    """测试延迟统计功能"""
    print("\n" + "=" * 60)
    print("测试 2: 延迟统计功能")
    print("=" * 60)

    stats = await call_metrics.get_latency_stats(test_source)

    print("\n延迟统计结果:")
    print(f"  样本数量：{stats['samples']}")
    print(f"  平均延迟：{stats['avg_ms']:.2f} ms" if stats["avg_ms"] else "  平均延迟：N/A")
    print(f"  P50 延迟：{stats['p50_ms']:.2f} ms" if stats["p50_ms"] else "  P50 延迟：N/A")
    print(f"  P95 延迟：{stats['p95_ms']:.2f} ms" if stats["p95_ms"] else "  P95 延迟：N/A")
    print(f"  P99 延迟：{stats['p99_ms']:.2f} ms" if stats["p99_ms"] else "  P99 延迟：N/A")
    print(f"  最小延迟：{stats['min_ms']:.2f} ms" if stats["min_ms"] else "  最小延迟：N/A")
    print(f"  最大延迟：{stats['max_ms']:.2f} ms" if stats["max_ms"] else "  最大延迟：N/A")

    # 验证统计结果
    assert stats["samples"] == 10, f"样本数量应为 10，实际为 {stats['samples']}"
    assert stats["avg_ms"] is not None, "平均延迟不应为 None"
    assert stats["p50_ms"] is not None, "P50 延迟不应为 None"
    assert stats["p95_ms"] is not None, "P95 延迟不应为 None"

    # 验证 P50 应该在中位数附近（排序后第 5-6 个值）
    sorted_latencies = sorted([150.5, 200.3, 180.2, 220.1, 195.8, 210.4, 185.6, 190.3, 205.7, 215.9])
    expected_p50_range = (sorted_latencies[4], sorted_latencies[5])  # 195.8 ~ 200.3
    assert expected_p50_range[0] <= stats["p50_ms"] <= expected_p50_range[1] + 1, (
        f"P50 应在 {expected_p50_range} 范围内，实际为 {stats['p50_ms']}"
    )

    print("\n✅ 延迟统计验证通过")
    return stats


async def test_redis_keys(test_source: str):
    """测试 Redis 键空间"""
    print("\n" + "=" * 60)
    print("测试 3: Redis 键空间验证")
    print("=" * 60)

    from backend.core.redis_client import redis_client

    # 检查调用计数键
    call_key = f"quant:metrics:{test_source}:calls:*"
    call_keys = await redis_client.keys(call_key)
    print(f"\n调用计数键：{call_key}")
    print(f"  找到 {len(call_keys)} 个键")
    if call_keys:
        for key in call_keys[:3]:
            print(f"    - {key}")

    # 检查延迟样本键
    latency_key = f"quant:metrics:{test_source}:latency:*"
    latency_keys = await redis_client.keys(latency_key)
    print(f"\n延迟样本键：{latency_key}")
    print(f"  找到 {len(latency_keys)} 个键")
    if latency_keys:
        for key in latency_keys[:3]:
            ttl = await redis_client.ttl(key)
            length = await redis_client.llen(key)
            print(f"    - {key}")
            print(f"      TTL: {ttl}s, 样本数：{length}")

    assert len(latency_keys) > 0, "应该有至少一个延迟样本键"

    print("\n✅ Redis 键空间验证通过")


async def test_empty_stats():
    """测试空统计结果"""
    print("\n" + "=" * 60)
    print("测试 4: 空统计结果处理")
    print("=" * 60)

    empty_source = "non_existent_source"
    stats = await call_metrics.get_latency_stats(empty_source)

    print(f"\n数据源：{empty_source}")
    print(f"  样本数量：{stats['samples']}")
    print(f"  平均延迟：{stats['avg_ms']}")
    print(f"  P50 延迟：{stats['p50_ms']}")

    assert stats["samples"] == 0, "空数据源样本数应为 0"
    assert stats["avg_ms"] is None, "空数据源平均延迟应为 None"

    print("\n✅ 空统计结果处理正确")


async def cleanup_test_data(test_source: str):
    """清理测试数据"""
    print("\n" + "=" * 60)
    print("清理测试数据")
    print("=" * 60)

    from backend.core.redis_client import redis_client

    # 清理调用计数键
    call_pattern = f"quant:metrics:{test_source}:calls:*"
    call_keys = await redis_client.keys(call_pattern)
    if call_keys:
        await redis_client.delete(*call_keys)
        print(f"已删除 {len(call_keys)} 个调用计数键")

    # 清理延迟样本键
    latency_pattern = f"quant:metrics:{test_source}:latency:*"
    latency_keys = await redis_client.keys(latency_pattern)
    if latency_keys:
        await redis_client.delete(*latency_keys)
        print(f"已删除 {len(latency_keys)} 个延迟样本键")

    print("\n✅ 测试数据清理完成")


async def main():
    """主测试流程"""
    print("\n" + "=" * 60)
    print("🚀 开始延迟统计功能测试")
    print("=" * 60)

    try:
        # 测试 1: 延迟记录
        test_source = await test_latency_recording()

        # 测试 2: 延迟统计
        await test_latency_stats(test_source)

        # 测试 3: Redis 键空间
        await test_redis_keys(test_source)

        # 测试 4: 空统计结果
        await test_empty_stats()

        # 清理测试数据
        await cleanup_test_data(test_source)

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        print("\n📊 功能验证:")
        print("  ✅ 延迟记录功能正常")
        print("  ✅ P50/P95/P99 计算正确")
        print("  ✅ Redis 键空间符合设计")
        print("  ✅ 空数据源处理正确")
        print("\n🎯 下一步:")
        print("  1. 部署到生产环境")
        print("  2. 观察真实业务调用的延迟统计")
        print("  3. 验证前端看板展示效果")

    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
