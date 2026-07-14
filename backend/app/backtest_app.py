"""
回测用例（BE-ARCH-02）

数据加载（Snapshot → Futu → YFinance）+ 沙箱/内置策略执行。
Router 只做请求校验与 HTTP 映射。
"""

from __future__ import annotations

import asyncio
import re
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pandas as pd

from backend.app.market_data import market_data
from backend.core.utils import safe_truncate

# 延迟导入 backend.backtest（vectorbt/numba 重依赖），避免 import router 时拖垮其它测试。
# 测试可 patch 本模块同名属性（见 execute_backtest）。
DivergenceResonanceStrategy = None  # type: ignore[misc, assignment]
run_dynamic_sandbox_backtest = None  # type: ignore[misc, assignment]

_INTERVAL_MAP = {
    "1d": "K_DAY",
    "1m": "K_1M",
    "5m": "K_5M",
    "15m": "K_15M",
    "1h": "K_60M",
}
_PERIOD_DAYS = {
    "1mo": 22,
    "3mo": 65,
    "6mo": 130,
    "1y": 252,
    "2y": 504,
    "5y": 1260,
    "max": 2500,
}


class BacktestDataError(Exception):
    """回测数据不可用（由 Router 映射为 HTTP 400）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class BacktestParams:
    ticker: str
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    atr_multiplier: float = 2.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    debug_mode: bool = False
    data_snapshot_id: Optional[str] = None
    random_seed: Optional[int] = 42
    source_code: Optional[str] = None
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


async def load_backtest_frame(req: BacktestParams) -> tuple[pd.DataFrame, str]:
    """SnapshotReader → Futu → YFinance；失败抛 BacktestDataError。"""
    df: Optional[pd.DataFrame] = None
    msg = ""
    success = False
    ktype = _INTERVAL_MAP.get(req.interval, "K_DAY")
    num_days = _PERIOD_DAYS.get(req.period, 252)

    sid = req.data_snapshot_id or "latest_published"
    if sid != "live":
        try:
            from backend.core.database import SessionLocal
            from backend.services.datalake.snapshot_reader import SnapshotReader

            db = SessionLocal()
            try:
                reader = SnapshotReader(db)
                resolved = await reader.resolve_snapshot_id(sid)
                if resolved != "live":
                    snap_df = await reader.get_history(resolved, req.ticker, ktype=ktype, num=num_days)
                    if snap_df is not None and not snap_df.empty:
                        df = snap_df
                        success = True
                        msg = f"Snapshot:{resolved}"
            finally:
                db.close()
        except Exception as e:
            print(f"⚠️ [Backtest] 快照未命中: {e}")

    if df is None or df.empty:
        if req.data_source in ["auto", "futu"]:
            try:
                print(f"📡 [Backtest] 尝试从 Futu OpenD 拉取数据: {req.ticker}...")
                futu_res = await market_data.get_history(req.ticker, ktype=ktype, num=num_days)
                if futu_res.get("status") == "success" and futu_res.get("data"):
                    df = pd.DataFrame(futu_res["data"])
                    if not df.empty:
                        df.rename(
                            columns={
                                "open": "Open",
                                "high": "High",
                                "low": "Low",
                                "close": "Close",
                                "volume": "Volume",
                            },
                            inplace=True,
                        )
                        df["time"] = pd.to_datetime(df["time"])
                        df.set_index("time", inplace=True)
                        success = True
                        print(f"🌐 [Backtest] 成功拉取实时在线数据源 (Futu): {req.ticker} | 数量: {len(df)} 行")
            except Exception as e:
                msg = f"Futu 接口获取失败: {e}"

        if (df is None or df.empty) and req.data_source in ["auto", "yfinance"]:
            print(f"📡 [Backtest] 尝试从 YFinance 拉取数据: {req.ticker}...")
            success, df, msg = await market_data.fetch_yf_data(
                req.ticker,
                "history",
                ttl=3600,
                period=req.period,
                interval=req.interval,
            )
            if success and df is not None and not df.empty:
                print(f"🌐 [Backtest] 成功拉取实时在线数据源 (YFinance): {req.ticker} | 数量: {len(df)} 行")

        if not success or df is None or df.empty:
            raise BacktestDataError(f"回测数据加载失败: {msg}")

    assert df is not None
    return df, msg


def _load_backtest_engine():
    """按需加载；若测试已 patch 模块属性则直接复用。"""
    import backend.app.backtest_app as self_mod

    need_divergence = self_mod.DivergenceResonanceStrategy is None
    need_sandbox = self_mod.run_dynamic_sandbox_backtest is None
    if need_divergence or need_sandbox:
        from backend.backtest import (  # noqa: WPS433
            DivergenceResonanceStrategy as _DRS,
        )
        from backend.backtest import (
            run_dynamic_sandbox_backtest as _rdsb,
        )

        if need_divergence:
            self_mod.DivergenceResonanceStrategy = _DRS
        if need_sandbox:
            self_mod.run_dynamic_sandbox_backtest = _rdsb
    return self_mod.DivergenceResonanceStrategy, self_mod.run_dynamic_sandbox_backtest


async def execute_backtest(req: BacktestParams, df: pd.DataFrame) -> dict[str, Any]:
    """运行动态沙箱或内置底背离策略。"""
    print(
        f"\n📊 [Backtest Debug] 准备进入回测引擎推演 | 标的: {req.ticker} | 周期: {req.period} | 级别: {req.interval}"
    )
    print(f"   - 数据规模 (Shape): {df.shape}")
    print(f"   - 数据列名 (Columns): {df.columns.tolist()}")

    divergence_cls, sandbox_runner = _load_backtest_engine()

    if req.source_code and req.class_name:
        for mod in ["talib", "core", "core.strategy", "backtrader"]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = req.source_code
        safe_code = re.sub(r"^\s*import\s+talib.*$", "", safe_code, flags=re.MULTILINE)
        safe_code = re.sub(r"^\s*from\s+talib\s+import.*$", "", safe_code, flags=re.MULTILINE)
        safe_code = re.sub(
            r"^\s*from\s+[\w\.]+\s+import\s+BaseStrategy.*$",
            "",
            safe_code,
            flags=re.MULTILINE,
        )
        try:
            report = await asyncio.to_thread(
                sandbox_runner,
                safe_code,
                req.class_name,
                req.params or {},
                df,
                req.initial_capital,
                req.debug_mode,
            )
            return {"status": "success", "data": report}
        except Exception as e:
            tb_str = safe_truncate(traceback.format_exc(), max_length=1500)
            return {
                "status": "error",
                "message": (f"大模型策略执行期间发生异常: {type(e).__name__}: {str(e)}\n\n追踪详情:\n{tb_str}"),
            }

    try:
        engine = divergence_cls(
            df=df,
            initial_capital=req.initial_capital,
            atr_multiplier=req.atr_multiplier,
            commission_pct=req.commission_pct,
            slippage_pct=req.slippage_pct,
        )
        report = await asyncio.to_thread(engine.run)
        return {"status": "success", "data": report}
    except Exception as e:
        return {"status": "error", "message": f"内置策略执行异常: {str(e)}"}


async def attach_reproducibility(req: BacktestParams, report: dict[str, Any]) -> dict[str, Any]:
    """BT-02 / FE-PROD-04：在回测结果上附加 manifest + badge。"""
    import uuid

    from backend.core.database import SessionLocal
    from backend.engine.contracts import RunManifest
    from backend.services.backtest_report_service import is_reproducible
    from backend.services.datalake.snapshot_resolver import (
        SnapshotResolveError,
        SnapshotResolver,
    )

    code_src = req.source_code or f"builtin:DivergenceResonance:{req.ticker}"
    code_hash = RunManifest.compute_code_hash(code_src)
    data_mode = "unbound"
    manifest_hash = None
    snapshot_id = req.data_snapshot_id or "latest_published"

    db = SessionLocal()
    try:
        try:
            ref = SnapshotResolver(db).resolve(snapshot_id, manifest_hash=None)
            snapshot_id = ref.snapshot_id
            manifest_hash = ref.manifest_hash or None
            data_mode = ref.data_mode
        except SnapshotResolveError:
            if snapshot_id == "live":
                data_mode = "live"
            else:
                data_mode = "unbound"
        except Exception:
            data_mode = "unbound"

        reproducible = is_reproducible(
            code_hash=code_hash,
            manifest_hash=manifest_hash,
            random_seed=req.random_seed,
            data_mode=data_mode,
        )
        manifest = RunManifest(
            run_id=str(uuid.uuid4()),
            mode="backtest",
            code_hash=code_hash,
            params=req.params or {},
            data_snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            random_seed=req.random_seed,
            data_mode=data_mode,  # type: ignore[arg-type]
            reproducible=reproducible,
        )
        out = {**report, "manifest": manifest.to_summary()}
        out["badge"] = {
            "code_hash": code_hash[:12],
            "manifest_hash": (manifest_hash[:12] if manifest_hash else None),
            "reproducible": reproducible,
            "data_snapshot_id": snapshot_id,
            "data_mode": data_mode,
        }
        return out
    finally:
        db.close()


async def run_backtest(req: BacktestParams) -> dict[str, Any]:
    """完整用例：加载数据 → 执行策略 → 附加可复现性摘要。"""
    df, _msg = await load_backtest_frame(req)
    result = await execute_backtest(req, df)
    if result.get("status") == "success" and isinstance(result.get("data"), dict):
        result = {
            **result,
            "data": await attach_reproducibility(req, result["data"]),
        }
    return result
