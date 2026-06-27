import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# 将项目根目录加入 sys.path，避免 ModuleNotFoundError
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from backend.services.fred_service import fred_service
from backend.core.redis_client import redis_client

async def main():
    print("=" * 60)
    print("🏛️  正在测试圣路易斯联储 (FRED) 宏观数据源")
    print("=" * 60)

    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        print("🚨 警告: 未配置 FRED_API_KEY，请确保在 .env 文件中已添加。")
    else:
        print(f"🔑 已检测到 FRED_API_KEY: {api_key[:4]}******{api_key[-4:]}")

    # 测试核心的宏观经济指标
    test_series = ["DGS10", "PAYEMS", "UNRATE"]

    try:
        for series_id in test_series:
            print(f"\n📡 正在请求序列 [{series_id}] 的最新 5 条数据...")
            res = await fred_service.get_series_observations(series_id=series_id, limit=5)
            
            if res.get("status") == "success":
                data = res.get("data", [])
                print(f"  ✅ 获取成功! 提取到 {len(data)} 条数据记录。")
                print(f"  📄 数据样例: {json.dumps(data[:3], indent=2)}")
            else:
                print(f"  ❌ 获取失败: {res.get('message')}")
    finally:
        await redis_client.aclose()
        await fred_service.close()

if __name__ == "__main__":
    asyncio.run(main())