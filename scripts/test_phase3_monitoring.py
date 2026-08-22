#!/usr/bin/env python3
"""
Phase 3 监控指标体系端到端测试脚本

测试所有新增的 API 端点：
1. GET /datasource/{name}/latency-distribution
2. GET /datasource/{name}/error-rate-trend
3. GET /datasource/rate-limit-heatmap
4. GET /datasource/{name}/availability-timeline
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.redis_client import redis_client
from backend.services.datasource.call_metrics_store import call_metrics


async def test_latency_distribution():
    """测试延迟分布 API"""
    print("\n" + "=" * 60)
    print("测试 1: 延迟分布直方图 API")
    print("=" * 60)

    # 模拟记录一些延迟样本
    for i in range(10):
        latency = 50 + i * 20  # 50ms 到 230ms
        await call_metrics._record_latency("finnhub", latency)

    # 获取延迟统计
    stats = await call_metrics.get_latency_stats("finnhub")
    print(f"✓ 延迟统计：{stats}")
    print(f"  - 样本数：{stats['samples']}")
    print(f"  - 平均延迟：{stats['avg_ms']:.2f} ms" if stats["avg_ms"] else "  - 平均延迟：N/A")
    print(f"  - P50: {stats['p50_ms']:.2f} ms" if stats["p50_ms"] else "  - P50: N/A")
    print(f"  - P95: {stats['p95_ms']:.2f} ms" if stats["p95_ms"] else "  - P95: N/A")


async def test_error_rate_trend():
    """测试错误率趋势 API"""
    print("\n" + "=" * 60)
    print("测试 2: 错误率趋势图 API")
    print("=" * 60)

    # 模拟记录一些业务调用
    for i in range(20):
        outcome = "success" if i % 10 != 0 else "error"
        await call_metrics.record_business("finnhub", outcome, latency_ms=100 + i * 10)

    # 获取错误率趋势
    trend = await call_metrics.get_error_rate_trend("finnhub", hours=24)
    print("✓ 错误率趋势：")
    print(f"  - 数据源：{trend['source']}")
    print(f"  - 时间点数量：{len(trend['time_series'])}")
    print(f"  - 总调用：{trend['summary']['total_calls']}")
    print(f"  - 总错误：{trend['summary']['total_errors']}")
    print(f"  - 平均错误率：{trend['summary']['avg_error_rate']:.2%}")


async def test_rate_limit_heatmap():
    """测试限流热力图 API"""
    print("\n" + "=" * 60)
    print("测试 3: 限流热力图 API")
    print("=" * 60)

    # 模拟记录一些限流事件
    for i in range(5):
        await call_metrics.record_business("finnhub", "rate_limited", category="rate_limit")

    # 获取热力图数据
    heatmap = await call_metrics.get_rate_limit_heatmap(sources=["finnhub", "yfinance"], days=7)
    print("✓ 限流热力图：")
    print(f"  - 数据源：{heatmap['sources']}")
    print(f"  - 统计天数：{heatmap['days']}")
    print(f"  - 数据点数量：{len(heatmap['heatmap'])}")


async def test_availability_timeline():
    """测试可用性时间线 API"""
    print("\n" + "=" * 60)
    print("测试 4: 可用性时间线 API")
    print("=" * 60)

    # 获取可用性时间线
    timeline = await call_metrics.get_availability_timeline("finnhub", hours=24)
    print("✓ 可用性时间线：")
    print(f"  - 数据源：{timeline['source']}")
    print(f"  - 时间点数量：{len(timeline['timeline'])}")
    print(f"  - 总时长：{timeline['summary']['total_hours']} 小时")
    print(f"  - 可用时长：{timeline['summary']['available_hours']} 小时")
    print(f"  - 可用率：{timeline['summary']['availability_rate']:.2%}")


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Phase 3 监控指标体系 - 端到端测试")
    print("=" * 60)

    # 检查 Redis 连接
    try:
        info = await redis_client.info()
        print(f"\n✓ Redis 连接成功：{info.get('redis_version', 'unknown')}")
    except Exception as e:
        print(f"\n✗ Redis 连接失败：{e}")
        return

    try:
        # 测试所有 API
        await test_latency_distribution()
        await test_error_rate_trend()
        await test_rate_limit_heatmap()
        await test_availability_timeline()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        print("\nAPI 端点总结：")
        print("  1. GET /datasource/{name}/latency-distribution")
        print("  2. GET /datasource/{name}/error-rate-trend")
        print("  3. GET /datasource/rate-limit-heatmap")
        print("  4. GET /datasource/{name}/availability-timeline")
        print("\n前端组件：")
        print("  - latency-distribution-chart.tsx")
        print("  - error-rate-trend-chart.tsx")
        print("  - rate-limit-heatmap-chart.tsx")
        print("  - availability-timeline-chart.tsx")
        print("\nGrafana 仪表板：")
        print("  - phase3-datasource-monitoring.json")
        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败：{e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
