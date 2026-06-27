import asyncio
import os
import sys
import httpx
import json
from datetime import datetime

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv()

from backend.services.akshare_service import akshare_service
from backend.services.fred_service import fred_service
from backend.core.redis_client import redis_client

async def verify_calendar():
    print("=" * 60)
    print("🔍 宏观经济日历双引擎底层直连诊断")
    print("=" * 60)

    # 1. 探针测试 Jin10
    print("\n📡 [1] 测试 金十数据 (Jin10) 直连...")
    res_jin = await akshare_service.get_economic_calendar(days_ahead=3, skip_cache=True)
    if res_jin.get("status") == "success" and res_jin.get("data"):
        print(f"  ✅ Jin10 获取成功! 共拿到 {len(res_jin['data'])} 条记录。")
        print(f"  📄 数据样例: {res_jin['data'][0]['time']} - {res_jin['data'][0]['event']} (预期: {res_jin['data'][0].get('estimate', '--')})")
    else:
        print(f"  ❌ Jin10 失败: {res_jin.get('message', res_jin)}")
        print("  🛠️ 正在进行裸 HTTP 探针测试...")
        url = f"https://rili-api.jin10.com/get_list?date={datetime.now().strftime('%Y-%m-%d')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://rili.jin10.com/"
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=10)
                print(f"    -> HTTP 状态码: {resp.status_code}")
                print(f"    -> 响应头部: {dict(resp.headers)}")
                print(f"    -> 响应文本: {resp.text[:300]}")
        except Exception as e:
            print(f"    -> 彻底崩溃: {e}")

    # 2. 探针测试 FRED
    print("\n📡 [2] 测试 FRED 接口...")
    res_fred = await fred_service.get_economic_calendar(days_ahead=3, skip_cache=True)
    if res_fred.get("status") == "success" and res_fred.get("data"):
        print(f"  ✅ FRED 获取成功! 共拿到 {len(res_fred['data'])} 条记录。")
    else:
        print(f"  ❌ FRED 失败: {res_fred.get('message', res_fred)}")
        key = os.getenv("FRED_API_KEY")
        if not key:
            print("    -> 诊断: 未配置 FRED_API_KEY")
        else:
            print(f"    -> 诊断: 已配置 API Key (尾号 {key[-4:]})，请检查网络是否能直连美国联储 API。")

    print("\n" + "=" * 60)
    await redis_client.aclose()
    await fred_service.close()

if __name__ == "__main__":
    asyncio.run(verify_calendar())