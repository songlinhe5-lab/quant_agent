import os
import time
import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    print("🚨 错误: 请先安装依赖: pip install yfinance pandas pyarrow")
    exit(1)

class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 15.0)
        return super().request(method, url, **kwargs)

def extract_and_save_quant_data():
    # 1. 配置：定义您的股票池与存储路径
    ticker_list = ["AAPL", "MSFT", "GOOG", "AMZN", "NVDA"] 
    tickers_string = " ".join(ticker_list)
    output_dir = "./quant_data_storage"
    
    # 创建本地数据数仓目录
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"🚀 【1/4 网络层】开始打包发起 Bulk Download, 标的总数: {len(ticker_list)}...")
    start_time = time.time()
    
    try:
        # 2. 批量单次请求，获取所有历史数据（此处以最大历史 max 为例，可改为 1y / 5y）
        df = yf.download(
            tickers=tickers_string,
            period="max",
            interval="1d",
            group_by='ticker',
            threads=True,
            progress=True,
            session=TimeoutSession()
        )
    except Exception as e:
        print(f"❌ 网络请求或解析发生严重异常: {e}")
        return

    download_latency = time.time() - start_time
    print(f"⏱️ 【2/4 性能指标】大资产包下载完成，耗时: {download_latency:.2f} 秒.")

    if df is None or df.empty:
        print("🚨 [警告] 未获取到任何数据，请检查网络或 Ticker 符号是否正确。")
        return

    print("\n📦 【3/4 逻辑层】开始进行底层高维索引切片与数据清洗...")
    
    # 3. 遍历股票池，矢量化提取单标的数据并落盘
    success_count = 0
    for ticker in ticker_list:
        try:
            # 检查该 Ticker 是否存在于返回的 MultiIndex 第一层中
            # if ticker not in df.columns.levels[0]:
            #     print(f"⚠️ 标的 {ticker} 未包含在 Yahoo 返回的数据中，跳过。")
            #     continue
                
            # 高性能切除顶层 Ticker 索引，直接获取该股票的 OHLCAV 矩阵
            ticker_df = df.xs(ticker, axis=1, level=0).dropna(how="all")
            
            if ticker_df.empty:
                continue
                
            # 重置索引，将 Date 转为标准的列，方便后续数据库导入或多机对齐
            ticker_df = ticker_df.reset_index()
            
            # 4. 【数据层】落盘：采用高效的 Parquet 格式（保留时间戳索引与数据类型）
            parquet_path = os.path.join(output_dir, f"{ticker}_daily.parquet")
            ticker_df.to_parquet(parquet_path, index=False, engine='pyarrow')
            
            # 同时备份一份可读的 CSV（可选）
            csv_path = os.path.join(output_dir, f"{ticker}_daily.csv")
            ticker_df.to_csv(csv_path, index=False)
            
            print(f"  -> ✅ 标的 [{ticker}] 提取成功: 包含 {len(ticker_df)} 行交易数据 -> 已序列化至本地")
            success_count += 1
            
        except Exception as ticker_err:
            print(f"❌ 处理标的 {ticker} 时发生数据切片错误: {ticker_err}")

    print(f"\n🏁 【4/4 系统提示】全数据提取任务结束！成功上架数仓: {success_count}/{len(ticker_list)} 只标的。")
    print(f"📂 数据文件存储绝对路径: {os.path.abspath(output_dir)}")

if __name__ == "__main__":
    extract_and_save_quant_data()