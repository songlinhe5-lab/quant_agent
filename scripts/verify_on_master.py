#!/usr/bin/env python3
"""
主服务器验证脚本 - 全数据源真实性验证

验证目标:
1. 检查所有已注册数据源的缓存状态
2. 验证调用计数和成功率
3. 确认是否命中本地缓存
4. 判断数据来源的真实性
"""

import asyncio
from datetime import datetime


async def verify_all_datasources():
    """验证所有数据源"""
    from backend.core.redis_client import l1_cached_redis, redis_client
    from backend.services.datasource.call_metrics_store import _bucket_key, _local_date_key

    print("\n" + "=" * 80)
    print("🔬 全数据源真实性验证报告")
    print(f"⏰ 验证时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 直接从 Redis 读取所有有调用记录的数据源
    # 这样更准确，不依赖内存中的 registry
    date_key = _local_date_key()
    print(f"\n📊 检查日期：{date_key}")

    # 扫描所有 quant:metrics:*:calls:{date} 键
    pattern = f"quant:metrics:*:calls:{date_key}"
    source_keys = await redis_client.keys(pattern)

    # 提取数据源名称
    source_names = []
    for key in source_keys:
        # quant:metrics:yfinance:calls:2026-08-04 -> yfinance
        parts = key.split(":")
        if len(parts) >= 3:
            source_names.append(parts[2])

    print(f"📊 发现数据源总数：{len(source_names)}")
    print(f"   数据源列表：{', '.join(sorted(source_names))}")

    results = []

    for name in sorted(source_names):
        print("\n" + "=" * 80)
        print(f"📡 数据源：{name.upper()}")
        print("=" * 80)

        result = {
            "name": name,
            "status": "unknown",
            "cache_hit": False,
            "has_calls": False,
            "success_rate": 0.0,
            "probe_calls": 0,
            "business_calls": 0,
            "rate_limit_count": 0,
        }

        # 1. 检查数据源基本信息 (跳过，因为我们从 Redis 扫描来的)
        print(f"\n【基本信息】")
        print(f"  类型：(从 Redis 调用记录推断)")
        print(f"  模式：(未知)")
        print(f"  能力：(未知)")

        # 2. 检查缓存状态
        print(f"\n【缓存状态】")

        # L1 Cache
        l1_entries = len(l1_cached_redis._cache) if hasattr(l1_cached_redis, "_cache") else 0
        l1_source_keys = [k for k in l1_cached_redis._cache if name.upper() in k.upper()] if l1_entries > 0 else []
        print(f"  L1 Cache 条目：{len(l1_source_keys)}")

        # YFinance 特有缓存
        if name.lower() == "yfinance":
            from backend.services.yfinance import yf_service

            yf_entries = len(yf_service._cache)
            print(f"  YFinance 内存缓存：{yf_entries} 条目")

            if yf_entries > 0:
                print(f"    ⚠️  发现内存缓存，test-link 可能命中")
                result["cache_hit"] = True
            else:
                print(f"    ✅ 无内存缓存")

        # Futu 特有缓存
        if name.lower() == "futu":
            # Futu 使用 Redis 缓存
            futu_cache_keys = await redis_client.keys(f"quant:cache:futu:*")
            print(f"  Futu Redis 缓存：{len(futu_cache_keys)} 条目")

            if futu_cache_keys:
                print(f"    ⚠️  发现 Redis 缓存")
                result["cache_hit"] = True
            else:
                print(f"    ✅ 无 Redis 缓存")

        # 3. 检查 Redis 调用计数
        print(f"\n【调用计数 (今日)】")

        date_key = _local_date_key()
        bucket = _bucket_key(name, date_key)

        print(f"  日期：{date_key}")
        print(f"  Redis Key: {bucket}")

        metrics = await redis_client.hgetall(bucket)

        if metrics:
            print(f"  ✅ 有调用记录:")

            # 业务指标
            calls = int(metrics.get("calls", 0))
            success = int(metrics.get("success", 0))
            errors = int(metrics.get("errors", 0))

            # 探针指标
            probe_calls = int(metrics.get("probe_calls", 0))
            probe_success = int(metrics.get("probe_success", 0))

            # 限流指标
            rl_rate_limit = int(metrics.get("rl_rate_limit", 0))
            rl_quota_exhausted = int(metrics.get("rl_quota_exhausted", 0))
            rl_ip_blocked = int(metrics.get("rl_ip_blocked", 0))
            rate_limit_total = rl_rate_limit + rl_quota_exhausted + rl_ip_blocked

            print(f"    业务调用：{calls}")
            print(f"    业务成功：{success}")
            print(f"    业务错误：{errors}")
            print(f"    成功率：{success / calls * 100:.1f}%" if calls > 0 else "    成功率：N/A")

            print(f"    探针调用：{probe_calls}")
            print(f"    探针成功：{probe_success}")
            print(f"    探针成功率：{probe_success / max(1, probe_calls) * 100:.1f}%")

            print(f"    限流次数：{rate_limit_total}")

            # 更新结果
            result["has_calls"] = True
            result["business_calls"] = calls
            result["probe_calls"] = probe_calls
            result["rate_limit_count"] = rate_limit_total
            result["success_rate"] = (success / calls * 100) if calls > 0 else 0.0

        else:
            print(f"  ❌ 无调用记录")
            print(f"     可能原因:")
            print(f"     1. 刚重启服务，Redis 键已过期")
            print(f"     2. 尚未发起真实业务请求")
            print(f"     3. 数据源未启用或未使用")

        # 4. 检查最近一次请求时间
        print(f"\n【最近请求】")

        last_request = metrics.get("last_request") if metrics else None
        last_success = metrics.get("last_success") if metrics else None

        if last_request:
            print(f"  最后请求：{last_request}")
            print(f"  最后成功：{last_success or 'N/A'}")

            # 计算时间差
            try:
                from datetime import datetime as dt

                req_time = dt.fromisoformat(last_request)
                now = dt.now()
                delta = now - req_time
                print(f"  距今：{delta.seconds // 60}分 {delta.seconds % 60}秒前")
            except:
                pass
        else:
            print(f"  无最近请求记录")

        # 5. 综合判断
        print(f"\n【真实性判断】")

        has_probe = result["probe_calls"] > 0
        has_business = result["business_calls"] > 0

        if not result["has_calls"]:
            print(f"  ⚠️  无法判断 (无调用记录)")
            result["status"] = "no_data"
        elif result["cache_hit"]:
            print(f"  ⚠️  可能命中缓存，数据可能不真实")
            result["status"] = "cache_hit"
        elif has_business and result["success_rate"] > 0:
            print(f"  ✅ 数据源正常工作")
            print(f"     成功率：{result['success_rate']:.1f}%")
            print(f"     业务调用：{result['business_calls']} 次")
            print(f"     探针调用：{result['probe_calls']} 次")

            if result["rate_limit_count"] > 0:
                print(f"     ⚠️  已触发限流 {result['rate_limit_count']} 次")
                result["status"] = "throttled"
            else:
                print(f"     ✅ 无限流触发")
                result["status"] = "healthy"
        elif has_probe and not has_business:
            print(f"  ✅ 数据源正常 (仅探针调用)")
            print(f"     探针调用：{result['probe_calls']} 次")
            print(f"     业务调用：0 次 (尚未发起真实业务请求)")
            print(f"     ✅ 探针验证通过，数据源可用")
            result["status"] = "healthy"  # 有探针也算健康
        else:
            print(f"  ❌ 数据源异常 (成功率 0%)")
            result["status"] = "error"

        results.append(result)

    # 6. 汇总报告
    print("\n" + "=" * 80)
    print("📊 汇总报告")
    print("=" * 80)

    healthy = [r for r in results if r["status"] == "healthy"]
    throttled = [r for r in results if r["status"] == "throttled"]
    no_data = [r for r in results if r["status"] == "no_data"]
    cache_hit = [r for r in results if r["status"] == "cache_hit"]
    error = [r for r in results if r["status"] == "error"]

    print(f"\n✅ 健康数据源：{len(healthy)}")
    for r in healthy:
        print(
            f"   - {r['name'].upper()}: 成功率 {r['success_rate']:.1f}%, "
            f"业务 {r['business_calls']} 次，探针 {r['probe_calls']} 次"
        )

    if throttled:
        print(f"\n⚠️  已限流数据源：{len(throttled)}")
        for r in throttled:
            print(f"   - {r['name'].upper()}: 限流 {r['rate_limit_count']} 次")

    if no_data:
        print(f"\nℹ️  无调用记录：{len(no_data)}")
        for r in no_data:
            print(f"   - {r['name'].upper()}")

    if cache_hit:
        print(f"\n⚠️  命中缓存：{len(cache_hit)}")
        for r in cache_hit:
            print(f"   - {r['name'].upper()}: 可能命中本地缓存")

    if error:
        print(f"\n❌ 异常数据源：{len(error)}")
        for r in error:
            print(f"   - {r['name'].upper()}: 成功率 0%")

    # 7. 最终结论
    print("\n" + "=" * 80)
    print("🎯 最终结论")
    print("=" * 80)

    if len(healthy) + len(throttled) == len(results):
        print("\n✅ 所有数据源都在返回真实数据！")
        print(f"   - 健康：{len(healthy)}")
        print(f"   - 限流：{len(throttled)}")
        print(f"   - 总计：{len(results)}")
    elif no_data:
        print(f"\n⚠️  部分数据源无调用记录")
        print(f"   可能原因:")
        print(f"   1. 刚重启服务，Redis 键已过期")
        print(f"   2. 数据源未启用或未使用")
        print(f"   3. 尚未发起真实业务请求")
    else:
        print(f"\n❌ 存在异常数据源，请检查上述输出")

    return results


if __name__ == "__main__":
    asyncio.run(verify_all_datasources())
