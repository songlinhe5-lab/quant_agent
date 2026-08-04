#!/usr/bin/env python3
"""检查 Finnhub 延迟统计为什么是 0ms"""

import asyncio

from backend.core.redis_client import redis_client
from backend.services.datasource.call_metrics_store import _bucket_key, _local_date_key


async def check_finnhub_metrics():
    """检查 Finnhub 的详细指标"""

    date_key = _local_date_key()
    bucket = _bucket_key("finnhub", date_key)

    print("\n" + "=" * 70)
    print(f"🔍 Finnhub 调用指标详情")
    print(f"⏰ 日期：{date_key}")
    print(f"📍 Redis Key: {bucket}")
    print("=" * 70)

    # 读取所有字段
    metrics = await redis_client.hgetall(bucket)

    if not metrics:
        print("\n❌ 无调用记录")
        return

    print("\n📊 所有字段:")
    for field, value in sorted(metrics.items()):
        print(f"  {field:30s}: {value}")

    # 分析延迟相关字段
    print("\n" + "-" * 70)
    print("🔍 延迟相关字段:")
    print("-" * 70)

    latency_fields = [k for k in metrics.keys() if "latency" in k.lower() or "p95" in k.lower()]

    if latency_fields:
        print("\n✅ 发现延迟字段:")
        for field in latency_fields:
            print(f"  {field}: {metrics[field]}")
    else:
        print("\n❌ 无延迟字段！")
        print("   CallMetricsStore 不记录延迟分布")
        print("   延迟统计可能在 RateLimitAnalyzer 中")

    # 检查 RateLimitAnalyzer
    print("\n" + "-" * 70)
    print("🔍 RateLimitAnalyzer 状态:")
    print("-" * 70)

    try:
        from backend.services.datasource.registry import rate_limit_registry

        analyzer = rate_limit_registry.get_analyzer("finnhub")

        if analyzer:
            print(f"\n✅ Analyzer 存在")
            print(f"   总请求数：{analyzer.total_requests}")
            print(f"   错误请求：{analyzer.error_requests}")
            print(f"   延迟样本数：{len(analyzer.latency_samples)}")

            if analyzer.latency_samples:
                samples = analyzer.latency_samples
                print(f"\n   延迟统计:")
                print(f"     最小值：{min(samples):.2f}ms")
                print(f"     最大值：{max(samples):.2f}ms")
                print(f"     平均值：{sum(samples) / len(samples):.2f}ms")

                # 计算 P95
                sorted_samples = sorted(samples)
                p95_idx = int(len(sorted_samples) * 0.95)
                p95 = sorted_samples[p95_idx] if p95_idx < len(sorted_samples) else 0
                print(f"     P95:    {p95:.2f}ms")
            else:
                print(f"\n   ❌ 无延迟样本！")
                print(f"      可能原因:")
                print(f"      1. 探针调用未记录延迟")
                print(f"      2. 业务调用未记录延迟")
                print(f"      3. 延迟记录逻辑有问题")
        else:
            print("\n❌ Analyzer 不存在")

    except Exception as e:
        print(f"\n❌ 检查 Analyzer 失败：{e}")


if __name__ == "__main__":
    asyncio.run(check_finnhub_metrics())
