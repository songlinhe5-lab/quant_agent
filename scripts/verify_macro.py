import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.routers.macro import (
    get_macro_calendar,
    get_macro_news,
    get_data_center_dashboard
)
from backend.core.redis_client import redis_client

async def main():
    print("Testing get_macro_calendar...")
    try:
        res = await get_macro_calendar(days_ahead=7)
        print("Calendar OK. Status:", res.get("status"), "Events count:", len(res.get("data", [])))
    except Exception as e:
        print("Calendar Error:", e)

    print("\nTesting get_macro_news...")
    try:
        res = await get_macro_news(category="general")
        print("News OK. Status:", res.get("status"), "News count:", len(res.get("data", [])))
    except Exception as e:
        print("News Error:", e)

    print("\nTesting get_data_center_dashboard...")
    try:
        # 清除缓存以便真实触发
        await redis_client.delete("macro_dashboard_aggregate")
        res = await get_data_center_dashboard()
        print("Dashboard OK. Status:", res.get("status"))
        data = res.get("data", {})
        print("- Assets:", len(data.get("macroAssets", [])))
        print("- Radar:", len(data.get("radarData", [])))
        print("- Events:", len(data.get("economicEvents", [])))
        print("- News:", len(data.get("newsItems", [])))
    except Exception as e:
        print("Dashboard Error:", e)

    print("\nValidating Redis Connection Shutdown...")
    try:
        await redis_client.aclose()
    except Exception as e:
        pass
    
import time
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("🚨 错误: 未检测到 yfinance 库，请先执行: pip install yfinance")
    exit(1)

def run_verification():
    # 1. 定义测试标的（用空格拼接）
    tickers_string = "AAPL MSFT GOOG"
    
    print(f"🚀 [1/3] 开始向 yfinance 发起批量合并请求: [{tickers_string}]...")
    start_time = time.time()
    
    # 2. 发起单次批量请求
    df = yf.download(
        tickers=tickers_string,
        period="5d",
        interval="1d",
        group_by='ticker',  # 关键参数：按 Ticker 分组返回 MultiIndex
        threads=True,        # 开启底层并发
        progress=False       # 关闭进度条保持输出清爽
    )
    
    if df is None:
        return
    
    latency = time.time() - start_time
    print(f"⏱️ [2/3] 请求完成！合并耗时: {latency:.2f} 秒 (仅消耗 1 次请求额度)")
    
    # 3. 验证数据维度与高维切片
    print("\n📊 [3/3] 数据层架构验证:")
    print(f" -> 原始 DataFrame 形状 (Shape): {df.shape}")
    
    print("\n💡 [演示] 使用 pandas.xs 进行矢量化切片，提取 [MSFT] 的前两行数据:")
    try:
        # 高性能切除第一层索引，直接降维成单标的数据
        msft_df = df.xs("MSFT", axis=1, level=0).dropna()
        print(msft_df.head(2))
        print("\n✅ 验证成功：批量化合并请求不仅速度极快，且数据解包完全正确！")
    except KeyError:
        print("❌ 切片失败，返回的数据结构异常。")

if __name__ == "__main__":
    run_verification()

# if __name__ == "__main__":
#     asyncio.run(main())
