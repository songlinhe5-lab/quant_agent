import asyncio
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.core.redis_client import redis_client
from backend.services.futu_service import futu_service
from backend.services.yfinance_service import format_yf_ticker, yf_service

# 💡 将数仓建立在根目录的 data/kline_warehouse 下，与代码库隔离
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "kline_warehouse"))  # noqa: E501
os.makedirs(DATA_DIR, exist_ok=True)


class KlineWarehouse:
    """
    本地 K 线数仓服务 (Parquet 格式)
    利用 Futu 的历史 K 线配额，进行稳定、增量、不重建的本地数据备份。
    为 VectorBT 回测系统提供纳秒级的极速读取支持。
    """

    def __init__(self):
        self.data_dir = DATA_DIR
        self._locks = {}

    def _get_file_path(self, ticker: str, ktype: str = "K_DAY") -> str:
        safe_ticker = ticker.replace(".", "_").replace("/", "_")
        # 💡 按 K 线周期分目录存储
        ktype_dir = os.path.join(self.data_dir, ktype)
        os.makedirs(ktype_dir, exist_ok=True)
        return os.path.join(ktype_dir, f"{safe_ticker}.parquet")

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 252) -> Optional[pd.DataFrame]:  # noqa: E501
        """供回测引擎调用：极速读取本地 Parquet K 线"""
        file_path = self._get_file_path(ticker, ktype)
        if not os.path.exists(file_path):
            return None

        try:

            def _read():
                # Parquet 格式的列式读取速度是 CSV 的上百倍
                df = pd.read_parquet(file_path)
                df = df.sort_values("time")
                return df.tail(num)

            # 放入线程池防止阻塞异步事件循环
            return await asyncio.to_thread(_read)
        except Exception as e:
            print(f"⚠️ [Kline Warehouse] 读取 {ticker} 本地数仓失败: {e}")
            return None

    async def update_ticker(self, ticker: str, ktype: str = "K_DAY", force_full: bool = False):  # noqa: E501
        """核心增量更新引擎：智能判断时间差，实现无缝追加拼接"""
        if ticker not in self._locks:
            self._locks[ticker] = asyncio.Lock()

        async with self._locks[ticker]:
            file_path = self._get_file_path(ticker, ktype)
            existing_df = None
            last_date = None

            if os.path.exists(file_path) and not force_full:
                try:
                    existing_df = await asyncio.to_thread(pd.read_parquet, file_path)
                    if not existing_df.empty:
                        existing_df["time"] = pd.to_datetime(existing_df["time"])
                        last_date = existing_df["time"].max()
                except Exception:
                    pass

            # 💡 增量拉取算法
            if last_date is None:
                num_to_fetch = 10000  # 首次冷启动，拉取过去 40 年全量数据 (确保能覆盖至少 20 年)  # noqa: E501
            else:
                # 计算相差天数，加上 10 天的冗余度 (防范节假日空缺与最新复权数据修正)
                days_diff = (datetime.now() - last_date).days
                if days_diff <= 0:
                    return True  # 已经是最新的了，直接跳过
                num_to_fetch = min(10000, days_diff + 10)

            new_data = None

            # 1. 优先使用富途拉取高质量前复权数据
            futu_res = await futu_service.get_history(ticker, ktype=ktype, num=num_to_fetch)  # noqa: E501
            if futu_res.get("status") == "success" and futu_res.get("data"):
                new_data = futu_res["data"]
                # 💡 强制长线保障：如果我们需要拉取超大跨度数据(>2000)，但富途分页受限返回的数据过少，废弃富途数据交由雅虎财经进行全量深度拉取  # noqa: E501
                if num_to_fetch > 2000 and len(new_data) < 2000:
                    print(
                        f"⚠️ [Kline Warehouse] 富途仅返回 {len(new_data)} 条历史数据，不足以支撑超长线回测，降级至雅虎财经获取全量历史..."
                    )  # noqa: E501
                    new_data = None

            if not new_data:
                print(f"⚠️ [Kline Warehouse] 尝试降级雅虎财经兜底拉取 {ticker} ...")
                # 2. 额度耗尽或历史长度不足时，无缝降级雅虎财经兜底
                yf_ticker = format_yf_ticker(ticker)
                period = "max" if last_date is None else "1mo"

                ktype_mapping = {
                    "K_1M": "1m",
                    "K_5M": "5m",
                    "K_15M": "15m",
                    "K_30M": "30m",
                    "K_60M": "60m",
                    "K_DAY": "1d",
                    "K_WEEK": "1wk",
                }
                yf_interval = ktype_mapping.get(ktype, "1d")

                success, yf_df, _ = await yf_service.fetch_yf_data(
                    yf_ticker, "history", ttl=0, period=period, interval=yf_interval
                )  # noqa: E501

                if success and yf_df is not None and not yf_df.empty:
                    if isinstance(yf_df.columns, pd.MultiIndex):
                        yf_df.columns = yf_df.columns.get_level_values(0)
                    yf_df = yf_df.reset_index()

                    # 兼容不同雅虎版本返回的日期列名
                    date_col = (
                        "Date" if "Date" in yf_df.columns else "Datetime" if "Datetime" in yf_df.columns else None
                    )  # noqa: E501
                    if date_col:
                        yf_df = yf_df.rename(
                            columns={
                                date_col: "time",
                                "Open": "open",
                                "High": "high",
                                "Low": "low",
                                "Close": "close",
                                "Volume": "volume",
                            }
                        )  # noqa: E501
                        yf_df["time"] = yf_df["time"].astype(str).str.split("+").str[0].str.replace("T", " ")  # noqa: E501
                        new_data = yf_df[["time", "open", "high", "low", "close", "volume"]].to_dict(orient="records")  # noqa: E501

            if not new_data:
                print(f"❌ [Kline Warehouse] {ticker} 增量更新失败：所有数据源均无法获取。")  # noqa: E501
                return False

            def _merge_and_save():
                new_df = pd.DataFrame(new_data)
                new_df["time"] = pd.to_datetime(new_df["time"])

                if existing_df is not None and not existing_df.empty:
                    merged = pd.concat([existing_df, new_df])
                else:
                    merged = new_df

                # 💡 核心策略：按时间去重，且 keep='last'。这能完美让今天拉取的最新复权K线，覆盖掉前几天存入的旧复权数据，保证精度！  # noqa: E501
                merged = merged.drop_duplicates(subset=["time"], keep="last").sort_values("time")  # noqa: E501
                merged.to_parquet(file_path, index=False)
                return len(new_df), len(merged)

            try:
                fetched_count, total_count = await asyncio.to_thread(_merge_and_save)
                print(
                    f"✅ [Kline Warehouse] {ticker} ({ktype}) 增量同步入库成功 | 抓取 {fetched_count} 条 | 现存 {total_count} 条。"
                )  # noqa: E501
                return True
            except Exception as e:
                print(f"❌ [Kline Warehouse] {ticker} 保存 Parquet 失败: {e}")
                return False

    async def daemon_sync_task(self):
        """后台守护进程：每天凌晨错峰执行全量资产的增量同步"""
        print("🚀 [Kline Warehouse] 启动本地 K 线数仓增量同步守护进程...")
        while True:
            try:
                # 设定每天凌晨 3:00 执行 (避开富途服务器 0点清算与后台其他的任务)
                now = datetime.now()
                if now.hour == 3 and now.minute == 0:
                    lock_key = f"quant:lock:kline_sync:{now.strftime('%Y%m%d')}"
                    # 分布式锁，防止集群多台机器同时拉取打爆富途 300 额度
                    if await redis_client.set(lock_key, "1", nx=True, ex=7200):
                        print("📦 [Kline Warehouse] 开始执行每日本地 K 线数仓同步...")

                        # 获取全量监控标的 (从监控池、行情池等汇总)
                        tickers_raw = await redis_client.hkeys("quant:settings:monitored_refcounts")  # noqa: E501
                        tickers = [t.decode("utf-8") if isinstance(t, bytes) else str(t) for t in tickers_raw]  # noqa: E501
                        default_tickers = [
                            "US.SPY",
                            "US.QQQ",
                            "HK.800000",
                            "SH.000001",
                            "US.AAPL",
                            "US.NVDA",
                        ]  # noqa: E501
                        all_tickers = list(set(tickers + default_tickers))

                        # 💡 循环同步不同周期的 K 线
                        for ktype_to_sync in ["K_DAY", "K_60M"]:
                            for t in all_tickers:
                                await self.update_ticker(t, ktype=ktype_to_sync)
                                # 💡 错峰防限流，富途历史 K 线接口有强频控
                                await asyncio.sleep(2.5)

                        print("✅ [Kline Warehouse] 每日 K 线数仓增量同步大动作完成！")

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Kline Warehouse] 同步任务守护进程异常: {e}")
                await asyncio.sleep(60)


kline_warehouse = KlineWarehouse()
