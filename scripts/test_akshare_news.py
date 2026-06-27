import asyncio
import os
import sys
from dotenv import load_dotenv

# 确保可以正确导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

load_dotenv()

from backend.services.akshare_service import akshare_service
from backend.core.redis_client import redis_client

async def test_akshare_company_news():
    print("=" * 60)
    print("🔍 正在测试 AKShare (东方财富) 获取 A股/港股新闻")
    print("=" * 60)
    
    # 测试标的：包含港股与 A 股 (沪市、深市)
    test_symbols = ["00700.HK", "00772.HK", "SH.600519", "000001.SZ"]
    
    try:
        for symbol in test_symbols:
            print(f"📡 正在调用 AKShare 接口获取 [{symbol}] 的公司新闻...")
            try:
                res = await akshare_service.get_company_news(ticker=symbol)
                if res.get("status") == "success":
                    news = res.get("data", [])
                    print(f"  ✅ 成功! 从 {res.get('source', '未知数据源')} 获取到 {len(news)} 条新闻。")
                    if news:
                        headline = news[0].get('headline', '')
                        dt_str = news[0].get('date', '')
                        print(f"  📰 最新一条: {headline} ({dt_str})")
                else:
                    print(f"  ❌ 失败! 错误信息: {res.get('message')}")
            except Exception as e:
                print(f"  ❌ 请求异常: {e}")
            print("-" * 60)
    finally:
        # 测试完毕后主动关闭 Redis 连接，避免触发 Asyncio 警告
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(test_akshare_company_news())