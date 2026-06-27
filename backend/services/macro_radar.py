import asyncio
import numpy as np
import pandas as pd
import yfinance as yf
import logging
from backend.services.fred_service import fred_service
from typing import Optional

logger = logging.getLogger("MacroRadar")

class MacroRadarEngine:
    """
    宏观风险 6 象限雷达计算引擎 (Macro Radar Engine)
    基于自适应波动率缩放 (Adaptive Z-Score Scaling) 将跨资产价格降维到统一量纲
    """
    
    # 核心映射标的字典 (Yahoo Finance Tickers)
    TICKERS = {
        "USD/JPY": "JPY=X",
        "VIX": "^VIX",
        "SPX": "^GSPC",
        "IXIC": "^IXIC",
        "HSI": "^HSI",
        "N225": "^N225",
        "XAU": "GC=F",
        "WTI": "CL=F",
        "10Y": "^TNX",
        "DXY": "DX-Y.NYB",
    }

    @staticmethod
    def calculate_adaptive_score(current_pct_change: float, history_closes: Optional[pd.Series], multiplier: float = 1.5, inverse: bool = False) -> float:
        """
        自适应波动率归一化 (Z-Score Scaling) -> Sigmoid [0, 100]
        """
        if history_closes is None or history_closes.empty or len(history_closes) < 2:
            return 50.0  # 数据不足兜底中性得分

        # 计算日收益率及其标准差 (历史波动率)
        daily_returns = history_closes.pct_change().dropna()
        rolling_volatility = daily_returns.std() * 100  # 转换为百分比
        
        # 兜底机制：防止“死水资产”因波动率趋近 0 导致除以 0 异常或 Z-Score 极度放大
        rolling_volatility = max(rolling_volatility, 0.5)
        
        # 计算 Z-Score 异动值
        z_score = current_pct_change / (rolling_volatility * multiplier)
        
        # 如果是逆向指标 (如 VIX 上涨代表恐慌，得分应降低)
        if inverse:
            z_score = -z_score
            
        # Sigmoid 映射：将 Z-Score 平滑挤压到 (0, 1) 然后乘以 100
        score = (1 / (1 + np.exp(-z_score))) * 100
        
        return round(score, 2)

    @staticmethod
    def calculate_spread_score(current_diff: float, history_series: Optional[pd.Series], multiplier: float = 1.5, inverse: bool = False) -> float:
        """
        针对利差数据(Spread)等包含负值或接近0的资产，使用绝对差值(Diff)计算 Z-Score
        """
        if history_series is None or history_series.empty or len(history_series) < 2:
            return 50.0

        # 计算绝对变动值 (bps) 的标准差
        daily_diffs = history_series.diff().dropna()
        rolling_volatility = daily_diffs.std()
        
        # 兜底机制：利差类指标波动率较小，设置最小基准防止除零
        rolling_volatility = max(rolling_volatility, 0.02)
        
        z_score = current_diff / (rolling_volatility * multiplier)
        if inverse:
            z_score = -z_score
            
        score = (1 / (1 + np.exp(-z_score))) * 100
        return round(score, 2)

    async def fetch_historical_data(self, ticker: str, period="60d") -> pd.Series:
        """
        异步拉取标的历史数据（支持优雅降级机制）
        """
        try:
            # 在实际生产中，可以优先尝试本地 Redis 缓存或 Futu 接口，降级才走 yfinance
            data = await asyncio.to_thread(yf.download, ticker, period=period, progress=False)
            if data is not None and not data.empty:
                # yfinance >= 0.2.x 可能会返回 MultiIndex columns
                if isinstance(data.columns, pd.MultiIndex):
                    return data['Close'][ticker].dropna()
                elif 'Close' in data:
                    return data['Close'].dropna()
        except Exception as e:
            logger.error(f"[MacroRadar] 获取 {ticker} 数据失败: {e}")
        return pd.Series(dtype=float)

    async def fetch_fred_data(self, series_id: str, limit=60) -> pd.Series:
        """异步拉取 FRED 宏观经济序列数据"""
        try:
            res = await fred_service.get_series_observations(series_id, limit=limit)
            if res.get("status") == "success" and res.get("data"):
                # FRED 默认是 desc 最新在前，翻转为 asc 时间正序列
                data = res["data"][::-1] 
                dates, values = [], []
                for d in data:
                    if d.get("value") is not None:
                        dates.append(d["date"])
                        values.append(float(d["value"]))
                if dates:
                    return pd.Series(values, index=pd.to_datetime(dates))
        except Exception as e:
            logger.error(f"[MacroRadar] 获取 FRED {series_id} 数据失败: {e}")
        return pd.Series(dtype=float)

    async def generate_radar_data(self) -> list[dict]:
        """
        全量并发获取数据并生成雷达图所需的 6 象限 JSON 结构
        """
        # 1. 并发获取所有底料数据 (整合 YFinance 与 FRED)
        yf_tasks = {name: self.fetch_historical_data(ticker) for name, ticker in self.TICKERS.items()}
        fred_tasks = {
            "HY_SPREAD": self.fetch_fred_data("BAMLH0A0HYM2"), 
            "T10Y2Y": self.fetch_fred_data("T10Y2Y")
        }
        
        all_tasks = {**yf_tasks, **fred_tasks}
        results = await asyncio.gather(*all_tasks.values(), return_exceptions=True)
        
        data_store = {}
        for name, res in zip(all_tasks.keys(), results):
            if isinstance(res, Exception):
                logger.error(f"[MacroRadar] 并发拉取 {name} 异常: {res}")
                data_store[name] = pd.Series(dtype=float)
            else:
                data_store[name] = res
                
        # 2. 计算 5 日涨跌幅 (pct_change) 与绝对变化量 (diff)
        changes = {}
        diffs = {}
        for name, series in data_store.items():
            if not series.empty and len(series) >= 5:
                current_price = float(series.iloc[-1])
                price_5d_ago = float(series.iloc[-5])
                chg = ((current_price - price_5d_ago) / price_5d_ago) * 100 if price_5d_ago != 0 else 0.0
                diff = current_price - price_5d_ago
                changes[name] = chg
                diffs[name] = diff
            else:
                changes[name] = 0.0
                diffs[name] = 0.0

        def get_score(name, inverse=False, multiplier=1.5):
            return self.calculate_adaptive_score(changes.get(name, 0.0), data_store.get(name), multiplier, inverse)

        def get_spread_score(name, inverse=False, multiplier=1.5):
            return self.calculate_spread_score(diffs.get(name, 0.0), data_store.get(name), multiplier, inverse)

        def avg(*scores):
            return sum(scores) / len(scores)

        # === 3. 计算 6 大象限得分 ===
        # 流动性加入高收益债利差 (HY_SPREAD) 作为信用紧缩指标
        liq_score = avg(get_score("USD/JPY", inverse=True), get_score("VIX", inverse=True), get_spread_score("HY_SPREAD", inverse=True))
        
        vix_series = data_store.get("VIX")
        vol_score = max(0, min(100, 100 - (float(vix_series.iloc[-1]) - 10) * 2.5)) if vix_series is not None and not vix_series.empty else 50.0
        eq_score = avg(get_score("SPX"), get_score("IXIC"), get_score("HSI"), get_score("N225"))
        com_score = avg(get_score("XAU"), get_score("WTI"))
        
        # 债券加入 10Y-2Y 长短端收益率倒挂程度 (T10Y2Y) 作为衰退指引
        bond_score = avg(get_score("10Y", inverse=True), get_spread_score("T10Y2Y", inverse=False))
        
        fx_score = get_score("DXY", inverse=True)

        # 4. 组装返回标准数据结构
        return [
            {"axis": "流动性", "current": round(liq_score, 1), "benchmark": 60},
            {"axis": "波动率", "current": round(vol_score, 1), "benchmark": 55},
            {"axis": "权益", "current": round(eq_score, 1), "benchmark": 60},
            {"axis": "商品", "current": round(com_score, 1), "benchmark": 55},
            {"axis": "债券", "current": round(bond_score, 1), "benchmark": 50},
            {"axis": "汇率", "current": round(fx_score, 1), "benchmark": 50},
        ]

macro_radar_engine = MacroRadarEngine()