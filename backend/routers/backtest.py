import asyncio
import os
import re
import sys
import traceback
from typing import Dict, Optional
from unittest.mock import MagicMock

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.backtest_engine import (
    DivergenceResonanceStrategy,
    run_dynamic_sandbox_backtest,
)
from backend.core.utils import safe_truncate
from backend.services.futu_service import futu_service
from backend.services.yfinance_service import yf_service

router = APIRouter(prefix="/backtest", tags=["Backtesting Engine"])

class BacktestRequest(BaseModel):
    ticker: str
    period: str = "2y"     # 回测时间跨度 (1mo, 1y, 2y, max)
    interval: str = "1d"   # K 线粒度 (1m, 15m, 1h, 1d)
    initial_capital: float = 100000.0
    atr_multiplier: float = 2.0  # ATR 止损乘数
    commission_pct: float = 0.0005 # 手续费率 (默认万5)
    slippage_pct: float = 0.001   # 滑点比例 (默认千1)
    data_source: str = "auto"
    debug_mode: bool = False

    # 💡 新增：支持接收来自“策略研发工作台”的动态策略脚本
    source_code: Optional[str] = None
    class_name: Optional[str] = None
    params: Optional[Dict] = None

@router.post("/run")
async def run_backtest(req: BacktestRequest):
    """接收前端触发指令，拉取历史数据并运行高频回测"""

    df = None
    msg = ""
    success = False
    # 1. 优先探测本地是否有极速 Parquet 高频离线库
    if req.data_source == "auto" and req.interval in ["1m", "5m"]:
        parquet_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "parquet_db", f"{req.ticker}_{req.interval}.parquet"))  # noqa: E501
        if os.path.exists(parquet_path):
            print(f"⚡ [Backtest] 命中本地 Parquet 极速列存库: {parquet_path}")
            df = await asyncio.to_thread(pd.read_parquet, parquet_path)

            success = True
    # 2. 如果没有命中本地库，降级走 YFinance 网络拉取
    if df is None or df.empty:
        if req.data_source in ["auto", "futu"]:
            period_days_map = {"1mo": 22, "3mo": 65, "6mo": 130, "1y": 252, "2y": 504, "5y": 1260, "max": 2500}  # noqa: E501
            num_days = period_days_map.get(req.period, 252)
            interval_map = {"1d": "K_DAY", "1m": "K_1M", "5m": "K_5M", "15m": "K_15M", "1h": "K_60M"}  # noqa: E501
            ktype = interval_map.get(req.interval, "K_DAY")
            try:
                print(f"📡 [Backtest] 尝试从 Futu OpenD 拉取数据: {req.ticker}...")
                futu_res = await futu_service.get_history(req.ticker, ktype=ktype, num=num_days)  # noqa: E501
                if futu_res.get("status") == "success" and futu_res.get("data"):
                    df = pd.DataFrame(futu_res["data"])
                    if not df.empty:
                        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)  # noqa: E501
                        df['time'] = pd.to_datetime(df['time'])
                        df.set_index('time', inplace=True)
                        success = True
                        print(f"🌐 [Backtest] 成功拉取实时在线数据源 (Futu): {req.ticker} | 数量: {len(df)} 行")  # noqa: E501
            except Exception as e:
                msg = f"Futu 接口获取失败: {e}"

        if (df is None or df.empty) and req.data_source in ["auto", "yfinance"]:
            print(f"📡 [Backtest] 尝试从 YFinance 拉取数据: {req.ticker}...")
            success, df, msg = await yf_service.fetch_yf_data(req.ticker, "history", ttl=3600, period=req.period, interval=req.interval)  # noqa: E501
            if success and df is not None and not df.empty:
                print(f"🌐 [Backtest] 成功拉取实时在线数据源 (YFinance): {req.ticker} | 数量: {len(df)} 行")  # noqa: E501

        if not success or df is None or df.empty:
            raise HTTPException(status_code=400, detail=f"回测数据加载失败: {msg}")

    # 🔍 增加调试日志：打印即将喂给策略引擎的数据结构
    print(f"\n📊 [Backtest Debug] 准备进入回测引擎推演 | 标的: {req.ticker} | 周期: {req.period} | 级别: {req.interval}")  # noqa: E501
    if df is not None:
        print(f"   - 数据规模 (Shape): {df.shape}")
        print(f"   - 数据列名 (Columns): {df.columns.tolist()}")
        if isinstance(df.columns, pd.MultiIndex):
            print("   ⚠️ [警告] 发现 MultiIndex 多级列结构！如果您的策略代码使用 df['Close'] 取值，大概率会失效并导致回测结果为空。")  # noqa: E501
        print(f"   - [前2条数据预览]:\n{df.head(2)}\n")
        print(f"   - [末2条数据预览]:\n{df.tail(2)}\n")
    else:
        print("   - DataFrame 为 None！\n")

    # 3. 初始化引擎计算
    if req.source_code and req.class_name:
        # 🛡️ 动态策略执行模式：应用我们在策略工作台沉淀的防崩溃白名单与依赖拦截
        for mod in ['talib', 'core', 'core.strategy', 'backtrader']:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = req.source_code
        safe_code = re.sub(r'^\s*import\s+talib.*$', '', safe_code, flags=re.MULTILINE)
        safe_code = re.sub(r'^\s*from\s+talib\s+import.*$', '', safe_code, flags=re.MULTILINE)  # noqa: E501
        safe_code = re.sub(r'^\s*from\s+[\w\.]+\s+import\s+BaseStrategy.*$', '', safe_code, flags=re.MULTILINE)  # noqa: E501

        try:
            # 调度至底层通用的 Numba C 级极速沙箱引擎
            report = await asyncio.to_thread(
                run_dynamic_sandbox_backtest, safe_code, req.class_name, req.params or {}, df, req.initial_capital, req.debug_mode  # noqa: E501
            )
        except Exception as e:
            tb_str = safe_truncate(traceback.format_exc(), max_length=1500)
            return {"status": "error", "message": f"大模型策略执行期间发生异常: {type(e).__name__}: {str(e)}\n\n追踪详情:\n{tb_str}"}  # noqa: E501
    else:
        try:
            # 兜底内置：如果没有传入外部代码，继续使用系统内置的底背离共振策略
            engine = DivergenceResonanceStrategy(
                df=df,
                initial_capital=req.initial_capital,
                atr_multiplier=req.atr_multiplier,
                commission_pct=req.commission_pct,
                slippage_pct=req.slippage_pct
            )
            report = await asyncio.to_thread(engine.run)
        except Exception as e:
            return {"status": "error", "message": f"内置策略执行异常: {str(e)}"}

    return {"status": "success", "data": report}
