#!/usr/bin/env python3
"""
内存热点分析工具
使用 tracemalloc 追踪内存分配，找出占用最高的模块和对象
"""

import tracemalloc
import os
import sys
import time
from pathlib import Path

# 添加 backend 到 Python 路径
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


def start_profiling():
    """启动内存追踪"""
    tracemalloc.start(25)  # 保留 25 层调用栈
    print("✅ Memory profiling started")
    print(f"   PID: {os.getpid()}")
    print(f"   Tracemalloc snapshot interval: 25 frames\n")


def take_snapshot(label: str = ""):
    """拍摄内存快照"""
    snapshot = tracemalloc.take_snapshot()
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, "<frozen zipimport>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    return snapshot


def print_top_stats(snapshot, key_type="lineno", limit=20):
    """打印内存占用最高的对象"""
    print(f"\n{'='*80}")
    print(f"📊 Top {limit} Memory Consumers (by {key_type})")
    print(f"{'='*80}\n")

    top_stats = snapshot.statistics(key_type)

    total = sum(stat.size for stat in top_stats)
    print(f"Total allocated memory: {total / 1024 / 1024:.2f} MB")
    print(f"Number of allocated blocks: {len(top_stats)}\n")

    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        filename = Path(frame.filename).name
        print(f"{index:3d}. {filename}:{frame.lineno} - "
              f"{stat.size / 1024 / 1024:.2f} MB "
              f"({stat.count} blocks)")


def compare_snapshots(snapshot1, snapshot2, limit=20):
    """对比两个快照，找出内存增长热点"""
    print(f"\n{'='*80}")
    print(f"📈 Memory Growth Analysis (Top {limit})")
    print(f"{'='*80}\n")

    stats1 = snapshot1.statistics("filename")
    stats2 = snapshot2.statistics("filename")

    # 计算差异
    stats1_dict = {stat.traceback[0].filename: stat.size for stat in stats1}
    stats2_dict = {stat.traceback[0].filename: stat.size for stat in stats2}

    growth = []
    for filename, size2 in stats2_dict.items():
        size1 = stats1_dict.get(filename, 0)
        if size2 > size1:
            growth.append((filename, size2 - size1))

    growth.sort(key=lambda x: x[1], reverse=True)

    for index, (filename, delta) in enumerate(growth[:limit], 1):
        print(f"{index:3d}. {Path(filename).name} - "
              f"+{delta / 1024 / 1024:.2f} MB")


def analyze_imports():
    """分析各模块导入后的内存占用"""
    print("\n" + "="*80)
    print("📦 Module Import Memory Analysis")
    print("="*80 + "\n")

    snapshot_before = take_snapshot()

    # 逐个导入主要模块，测量内存增长
    modules_to_test = [
        ("FastAPI Core", lambda: __import__("backend.core.database")),
        ("Redis Client", lambda: __import__("backend.core.redis_client")),
        ("Futu Service", lambda: __import__("backend.services.futu.service")),
        ("YFinance Service", lambda: __import__("backend.services.yfinance_service")),
        ("FRED Service", lambda: __import__("backend.services.fred_service")),
        ("Hermes Agent", lambda: __import__("hermes_agent.agent")),
        ("Tool Registry", lambda: __import__("hermes_agent.tool_registry")),
        ("VectorBT", lambda: __import__("vectorbt")),
    ]

    for module_name, import_func in modules_to_test:
        try:
            snapshot_before_module = take_snapshot()
            import_func()
            snapshot_after_module = take_snapshot()

            stats_before = snapshot_before_module.statistics("filename")
            stats_after = snapshot_after_module.statistics("filename")

            total_before = sum(stat.size for stat in stats_before)
            total_after = sum(stat.size for stat in stats_after)
            delta = total_after - total_before

            print(f"✅ {module_name:20s} - Memory increase: "
                  f"{delta / 1024 / 1024:7.2f} MB")
        except Exception as e:
            print(f"❌ {module_name:20s} - Failed to import: {e}")


def main():
    """主函数"""
    print("\n" + "🧠"*40)
    print("Quant Agent - Memory Profiler")
    print("🧠"*40 + "\n")

    # 启动追踪
    start_profiling()

    # 拍摄初始快照
    print("📸 Taking initial snapshot...")
    snapshot1 = take_snapshot()

    # 分析各模块导入的内存占用
    analyze_imports()

    # 拍摄导入后的快照
    print("\n📸 Taking post-import snapshot...")
    snapshot2 = take_snapshot()

    # 对比快照
    compare_snapshots(snapshot1, snapshot2)

    # 打印最终内存占用最高的对象
    print_top_stats(snapshot2, limit=30)

    # 停止追踪
    tracemalloc.stop()

    print("\n✅ Memory profiling completed\n")


if __name__ == "__main__":
    main()
