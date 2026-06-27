import os
import httpx
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

async def test_company_news():
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("🚨 未找到 FINNHUB_API_KEY，请检查 .env 文件配置。")
        return

    # 测试标的：包含港股与美股
    test_symbols = ["0772.HK", "0700.HK", "AAPL", "MSFT"]
    
    # 设定日期范围为过去 7 天
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    print(f"📅 查询日期范围: {start_date} -> {end_date}\n")
    print("=" * 60)
    
    async with httpx.AsyncClient(verify=False) as client:
        for symbol in test_symbols:
            url = "https://finnhub.io/api/v1/company-news"
            params = {
                "symbol": symbol,
                "from": start_date,
                "to": end_date,
                "token": api_key
            }
            
            print(f"📡 正在调用 REST API 获取 [{symbol}] 的公司新闻...")
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    news = response.json()
                    print(f"  ✅ 成功! HTTP 200，共获取到 {len(news)} 条新闻。")
                    if news:
                        headline = news[0].get('headline', '')
                        dt_str = datetime.fromtimestamp(news[0].get('datetime', 0)).strftime('%Y-%m-%d %H:%M')
                        print(f"  📰 最新一条: {headline} ({dt_str})")
                elif response.status_code == 403:
                    print(f"  ❌ 失败! HTTP 403 权限拒绝 (提示: 免费版仅支持美股，不支持此市场标的)")
                else:
                    print(f"  ⚠️ 失败! HTTP {response.status_code}: {response.text}")
            except Exception as e:
                print(f"  ❌ 请求异常: {e}")
            print("-" * 60)

if __name__ == "__main__":
    asyncio.run(test_company_news())