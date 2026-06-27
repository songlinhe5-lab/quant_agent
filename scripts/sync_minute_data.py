import os
import sys
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime

# 确保脚本可以引用到外层的模块（如果需要）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core.utils import safe_divide

# 配置你想要监控的高频股票池
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", 
    "0700.HK", "BABA", "09988.HK"
]

# 数据库存储路径 (按 Parquet 规范存放)
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "parquet_db"))

class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 15.0)
        return super().request(method, url, **kwargs)

def sync_minute_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"🚀 开始批量拉取 {len(TICKERS)} 只标的的分钟线数据...")
    
    # 💡 雅虎财经 API 限制：
    # 1m 颗粒度最大只能追溯 7 天，5m 最大 60 天。
    # 所以这个脚本非常适合部署为“每日收盘后执行一次”的增量拉取任务。
    try:
        df_batch = yf.download(
            tickers=" ".join(TICKERS),
            period="7d",       # 拉取最近7天数据以防前几天有遗漏
            interval="1m",     # 1分钟线
            group_by="ticker",
            threads=True,      # 开启多线程加速下载
            progress=True,
            session=TimeoutSession()
        )
    except Exception as e:
        print(f"❌ 批量拉取失败，疑似触发限流: {e}")
        return
        
    # 💡 防御性拦截：确保拉取到了有效数据，同时消除类型检查器关于 None 的报错
    if df_batch is None or df_batch.empty:
        print("⚠️ 批量拉取返回空数据，任务安全退出。")
        return

    for ticker in TICKERS:
        try:
            # 兼容不同股票组合触发的多级索引结构
            if isinstance(df_batch.columns, pd.MultiIndex):
                # 如果部分标的因为退市等原因无数据，进行安全探测
                if ticker not in df_batch.columns.get_level_values(0):
                    continue
                df_ticker = df_batch[ticker].dropna(how="all")
            else:
                # 当仅请求一个股票，或多个请求中最终只有一个标的成功时，yfinance 会降级返回单层索引
                df_ticker = df_batch.copy()
                
            if df_ticker.empty:
                print(f"⚠️ {ticker} 数据为空，跳过。")
                continue
            
            # 清理索引与无关列 (仅保留 OHLCV 核心字段)
            df_ticker.index.name = "datetime"
            core_cols = ["Open", "High", "Low", "Close", "Volume"]
            df_ticker = df_ticker[[c for c in core_cols if c in df_ticker.columns]]
            
            file_path = os.path.join(DATA_DIR, f"{ticker}_1m.parquet")
            
            # 💡 增量追加与去重逻辑
            if os.path.exists(file_path):
                old_df = pd.read_parquet(file_path)
                
                # 💡 新增：批量前复权对齐逻辑 (处理送转、拆股、大额分红导致的价格缺口)
                overlap_indices = old_df.index.intersection(df_ticker.index)
                if not overlap_indices.empty:
                    # 取重合段的第一个时间点来对比新老价格
                    sync_time = overlap_indices[0]
                    old_c = old_df.loc[sync_time, 'Close']
                    new_c = df_ticker.loc[sync_time, 'Close']
                    
                    old_c_val = old_c.iloc[0] if isinstance(old_c, pd.Series) else old_c
                    new_c_val = new_c.iloc[0] if isinstance(new_c, pd.Series) else new_c
                    
                    adj_ratio = safe_divide(new_c_val, old_c_val, default=1.0)
                    # 如果同一时刻价差超过 0.5% (容忍正常的浮点误差)，说明发生了除权除息/拆股
                    if abs(adj_ratio - 1.0) > 0.005:
                        print(f"🔄 探测到 {ticker} 发生除权除息，执行历史批量前复权 (复权因子: {adj_ratio:.4f})...")
                        for col in ["Open", "High", "Low", "Close"]:
                            if col in old_df.columns: old_df[col] = old_df[col] * adj_ratio
                        if "Volume" in old_df.columns: old_df["Volume"] = safe_divide(old_df["Volume"], adj_ratio)
                        
                # 将老数据与新拉取的最近7天数据合并
                combined_df = pd.concat([old_df, df_ticker])
                # 按时间戳去重，保留最新拉取的值 (修补前复权等调整)
                combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                combined_df.sort_index(inplace=True)
            else:
                combined_df = df_ticker
                
            # 落盘写入 (使用 snappy 压缩，体积小速度快)
            combined_df.to_parquet(file_path, engine="pyarrow", compression="snappy")
            print(f"✅ {ticker} 1m 高频线已落盘 -> 当前历史库总规模: {len(combined_df)} 条")
            
        except Exception as e:
            print(f"❌ 处理 {ticker} 时发生异常: {e}")

if __name__ == "__main__":
    sync_minute_data()