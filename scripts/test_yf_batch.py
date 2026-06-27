import pandas as pd
import yfinance as yf
import time
from datetime import datetime

# 20 个测试标的 (包含美股、指数、外汇等不同类型，考验稳健性)
tickers = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", 
    "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX",
    "EURUSD=X", "JPY=X", "BTC-USD", "ETH-USD", "GC=F"
]
tickers_string = " ".join(tickers)

print(f"🚀 开始测试批量拉取 (共 {len(tickers)} 个 Ticker)")
print(f"📦 标的列表: {tickers_string}\n")

# 压测配置：大幅增加循环次数，缩短间隔时间
max_rounds = 50
test_interval = 2  # 间隔 2 秒，测试极限并发

for i in range(max_rounds):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔄 [第 {i+1}/{max_rounds} 轮] {now_str} - 开始发起批量请求...")
    
    start_time = time.time()
    try:
        # 批量请求
        data = yf.download(
            tickers_string, 
            period="5d", 
            interval="1d", 
            group_by='ticker', 
            threads=True,
            progress=False
        )
        
        latency = time.time() - start_time
        
        if data is None or data.empty:
            print(f"  ❌ 警告: 返回了空数据！可能触发了限流 (429)。")
            print(f"  🚨 压测中断: 间隔 {test_interval} 秒的高频拉取在第 {i+1} 轮被雅虎拦截！")
            break
        else:
            print(f"  ✅ 成功! 耗时: {latency:.2f}s | DataFrame 形状: {data.shape}")
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    prices = []
                    # 尝试两种不同的 yfinance MultiIndex 返回结构
                    if "AAPL" in data.columns.levels[0] or "AAPL" in data:
                        actual_tickers = list(data.columns.get_level_values(0).unique())
                        # 结构 A
                        for t in actual_tickers:
                            try: prices.append(f"{t}: {data[t]['Close'].dropna().iloc[-1]:.2f}")
                            except: pass
                    elif "Close" in data:
                        actual_tickers = list(data.columns.get_level_values(1).unique())
                        # 结构 B
                        for t in actual_tickers:
                            try: prices.append(f"{t}: {data['Close'][t].dropna().iloc[-1]:.2f}")
                            except: pass
                            
                    print(f"  📌 实际拿到的 Tickers 共 {len(actual_tickers)} 个")
                    print(f"  📊 所有标的最新收盘价: {', '.join(prices)}")
                else:
                    print(f"  ⚠️ 返回的不是 MultiIndex 结构，实际列名: {list(data.columns)[:10]}...")
            except Exception as slice_err:
                print(f"  ❌ 切片报错: {slice_err}")
                
    except Exception as e:
        print(f"  ❌ 发生严重异常: {e}")
        
    if i < max_rounds - 1:
        print(f"  ⏳ 休眠 {test_interval} 秒后进行下一轮压测...\n")
        time.sleep(test_interval)

print("\n🎉 批量拉取稳定性验证结束。")
