#!/usr/bin/env python3
"""检查所有数据源模块是否存在"""

services = ["finnhub", "fmp", "fred", "dbnomics", "rbi", "tavily", "bocha", "jina"]

print("\n检查数据源模块:")
print("=" * 60)

for svc in services:
    try:
        # 尝试导入模块
        mod_name = f"backend.services.{svc}"
        mod = __import__(mod_name, fromlist=[f"{svc}_service"])

        # 检查是否有服务实例
        instance_name = f"{svc}_service"
        has_instance = hasattr(mod, instance_name)

        if has_instance:
            print(f"✅ {svc:12s}: 存在 ({instance_name})")
        else:
            # 列出模块内容
            attrs = [a for a in dir(mod) if not a.startswith("_")]
            print(f"⚠️  {svc:12s}: 模块存在，但无 {instance_name}")
            print(f"      可用属性：{attrs[:5]}")

    except ImportError as e:
        print(f"❌ {svc:12s}: 导入失败 - {str(e)[:50]}")

print("\n" + "=" * 60)
