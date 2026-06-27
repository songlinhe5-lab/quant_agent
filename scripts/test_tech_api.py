import asyncio
import httpx
import json

async def test_tech_indicators():
    url = "http://127.0.0.1:8000/market/tech-indicators"
    params = {
        "ticker": "HK.00700",  # 测试腾讯控股
        "lookback_days": 3     # 获取过去 3 天的数据
    }
    
    print(f"🚀 正在测试技术指标 API: {url}")
    print(f"📦 请求参数: {params}\n")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            
            print(f"📡 HTTP 状态码: {response.status_code}")
            if response.status_code == 200:
                print("✅ 测试成功！返回数据如下:")
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            else:
                print(f"❌ 请求失败，错误信息:\n{response.text}")
    except Exception as e:
        print(f"💥 请求发生异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_tech_indicators())