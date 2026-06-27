import asyncio
import sys
import os
import json

# 将项目根目录加入 sys.path，以便能够正确识别并导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.akshare_service import akshare_service
from backend.core.redis_client import redis_client

async def verify_southbound():
    print("=" * 60)
    print("🔍 开始验证港股南向资金真实数据 (AKShare)")
    print("=" * 60)
    try:
        print("📡 正在向东方财富接口发起并发请求 (当日汇总 + 近期历史趋势)...")
        res = await akshare_service.get_southbound_flow()
        
        if res.get("status") == "success":
            print("✅ [获取成功] 真实数据返回如下:")
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif res.get("status") == "warning":
            print("⚠️ [触发兜底] 真实接口获取失败，返回了 Mock 模拟数据:")
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"❌ [获取报错]: {res}")
    except Exception as e:
        print(f"❌ [执行异常]: {e}")
    finally:
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(verify_southbound())