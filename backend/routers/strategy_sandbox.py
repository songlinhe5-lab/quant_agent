"""
Strategy Sandbox 路由 — 策略沙箱回测、寻优、批量推演、蒙特卡洛与 OMS 部署端点。

从 strategy.py 拆分，共享 /strategy 前缀。
"""

import asyncio
import json
import os
import re
import sys
import time
import traceback
import uuid
from typing import Optional
from unittest.mock import MagicMock

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.backtest import (
    run_batch_sandbox_backtest,
    run_dynamic_sandbox_backtest,
    run_grid_search_backtest,
    run_monte_carlo_stress_test,
)
from backend.app.market_data import market_data
from backend.core.cpu_pool import run_cpu_bound, run_cpu_bound_with_progress
from backend.core.redis_client import redis_client
from backend.core.utils import safe_truncate
from backend.routers.auth import get_current_user
from backend.services.datalake.kline_warehouse import kline_warehouse

router = APIRouter(prefix="/strategy", tags=["Strategy Dev"])


# ─── 从 strategy.py 导入共享的限流中间件 ──────────────────────────────
def RateLimiter(
    max_requests: int = 10,
    window_seconds: int = 60,
    by_user: bool = False,
    global_max: Optional[int] = None,
    global_window: int = 60,
):
    """从 strategy.py 复制的限流依赖，避免循环导入。"""
    from starlette.status import HTTP_429_TOO_MANY_REQUESTS
    from fastapi import HTTPException, Request

    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key_prefix = "user" if by_user else "ip"
        key_value = client_ip

        redis_key = f"ratelimit:{key_prefix}:{key_value}:{max_requests}:{window_seconds}"
        current = await redis_client.get(redis_key)
        count = int(current) if current else 0

        if count >= max_requests:
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，{window_seconds} 秒内最多 {max_requests} 次",
            )

        pipe = redis_client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds)
        await pipe.execute()

    return dependency


# ─── Payload 模型 ──────────────────────────────────────────────────────


class RunSandboxPayload(BaseModel):
    source_code: str
    class_name: str
    params: dict
    ticker: str = "US.AAPL"
    period: str = "1y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    data_source: str = "auto"
    debug_mode: bool = False
    data_snapshot_id: Optional[str] = None
    random_seed: Optional[int] = 42
    persist_report: bool = False


class OptimizeSandboxPayload(BaseModel):
    source_code: str
    class_name: str
    param_grid: dict
    ticker: str = "US.AAPL"
    period: str = "1y"
    interval: str = "1d"
    target_metric: str = "sharpe_ratio"
    initial_capital: float = 100000.0
    data_source: str = "auto"


class MonteCarloSandboxPayload(BaseModel):
    source_code: str
    class_name: str
    params: dict
    ticker: str = "US.AAPL"
    period: str = "1y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    iterations: int = 100
    noise_level: float = 1.0
    data_source: str = "auto"
    noise_distribution: str = "laplace"


class BatchRunSandboxPayload(BaseModel):
    source_code: str
    class_name: str
    params: dict
    tickers: list[str] = Field(..., description="选出的批量候选股代码列表")
    period: str = "1y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    data_source: str = "auto"


# ─── 数据获取 ──────────────────────────────────────────────────────────


async def _fetch_backtest_data(
    ticker: str,
    period: str,
    data_source: str = "auto",
    interval: str = "1d",
    snapshot_id: Optional[str] = None,
):  # noqa: E501
    """为沙箱回测获取历史数据。

    DQ-03c：默认优先 SnapshotReader(latest_published)；
    live 仅 ENGINE_ALLOW_LIVE_DATA 或显式 snapshot_id=live / 无快照时降级。
    """
    period_days_map = {
        "1mo": 22,
        "3mo": 65,
        "6mo": 130,
        "1y": 252,
        "2y": 504,
        "5y": 1260,
        "10y": 2520,
        "20y": 5040,
        "max": 10000,
    }  # noqa: E501
    num_days = period_days_map.get(period, 252)

    interval_map = {
        "1d": "K_DAY",
        "1m": "K_1M",
        "5m": "K_5M",
        "15m": "K_15M",
        "1h": "K_60M",
    }  # noqa: E501
    ktype = interval_map.get(interval, "K_DAY")

    multiplier = 1
    if interval == "1m":
        multiplier = 390  # noqa: E701
    elif interval == "5m":
        multiplier = 78  # noqa: E701
    elif interval == "15m":
        multiplier = 26  # noqa: E701
    elif interval == "1h":
        multiplier = 7  # noqa: E701
    num_bars = num_days * multiplier

    sid = snapshot_id if snapshot_id is not None else "latest_published"
    allow_live = os.getenv("ENGINE_ALLOW_LIVE_DATA", "false").lower() == "true"

    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"])
            out.set_index("time", inplace=True)
        out.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )
        return out

    # DQ-03c：快照优先（非 live）
    if sid != "live" and data_source in ["auto", "local", "snapshot"]:
        try:
            from backend.core.database import SessionLocal
            from backend.services.datalake.snapshot_reader import SnapshotReader
            from backend.services.datalake.snapshot_resolver import SnapshotResolveError

            db = SessionLocal()
            try:
                reader = SnapshotReader(db)
                resolved = await reader.resolve_snapshot_id(sid)
                if resolved != "live":
                    snap_df = await reader.get_history(resolved, ticker, ktype=ktype, num=num_bars)
                    if snap_df is not None and not snap_df.empty:
                        try:
                            from backend.core.metrics import DATALAKE_SNAPSHOT_READ

                            DATALAKE_SNAPSHOT_READ.labels(result="hit").inc()
                        except Exception:
                            pass
                        return True, _normalize_df(snap_df), f"Snapshot:{resolved}"
            except SnapshotResolveError as e:
                if data_source == "snapshot" or (not allow_live and sid != "latest_published"):
                    return False, None, f"DATA_SNAPSHOT_MISSING:{e}"
            finally:
                db.close()
        except Exception as e:
            print(f"⚠️ [Backtest] 快照读取失败，尝试 live 降级: {e}")

    if sid == "live" and not allow_live:
        return False, None, "DATA_SNAPSHOT_LIVE_FORBIDDEN:设置 ENGINE_ALLOW_LIVE_DATA=true 以允许 live"

    if data_source in ["auto", "local"]:
        try:
            local_df = await kline_warehouse.get_history(ticker, ktype=ktype, num=num_bars)  # noqa: E501

            if local_df is None or local_df.empty or len(local_df) < num_bars * 0.8:
                print(f"📦 [Backtest] 本地数仓数据不足 ({ticker} {ktype})，已拦截请求等待手动同步。")  # noqa: E501
                if data_source == "local" or num_days >= 1000:
                    return (
                        False,
                        None,
                        "LOCAL_DATA_MISSING:本地数仓数据不足，请手动触发 K 线数据拉取与落库。",
                    )  # noqa: E501
            else:
                if "time" in local_df.columns:
                    local_df["time"] = pd.to_datetime(local_df["time"])
                    local_df.set_index("time", inplace=True)
                local_df.rename(
                    columns={
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume",
                    },
                    inplace=True,
                )  # noqa: E501
                return True, local_df, "LocalDB"
        except Exception as e:
            print(f"⚠️ [Backtest] 本地数仓获取失败: {e}")

    if data_source in ["auto", "futu"]:
        try:
            futu_res = await market_data.get_history(ticker, ktype=ktype, num=num_bars)
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
                    )  # noqa: E501
                    df["time"] = pd.to_datetime(df["time"])
                    df.set_index("time", inplace=True)
                    return True, df, "Futu"
        except Exception as e:
            if data_source == "futu":
                return False, None, f"Futu 接口获取数据失败: {e}"
            pass

    if data_source == "auto":
        if (ticker.startswith("SH.") or ticker.startswith("SZ.")) and interval == "1d":
            try:
                ak_res = await market_data.get_stock_history_ak(ticker, num=num_bars)
                if ak_res.get("status") == "success" and ak_res.get("data"):
                    df = pd.DataFrame(ak_res["data"])
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
                        )  # noqa: E501
                        df["time"] = pd.to_datetime(df["time"])
                        df.set_index("time", inplace=True)
                        return True, df, "AKShare"
            except Exception:
                pass

        if (ticker.startswith("US.") or ("." not in ticker)) and interval == "1d":
            try:
                finnhub_res = await market_data.get_stock_history_fh(ticker, days_back=int(num_days * 1.5))  # noqa: E501
                if finnhub_res.get("status") == "success" and finnhub_res.get("data"):
                    df = pd.DataFrame(finnhub_res["data"])
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
                        )  # noqa: E501
                        df["time"] = pd.to_datetime(df["time"])
                        df.set_index("time", inplace=True)
                        return True, df, "Finnhub"
            except Exception as e:
                print(f"⚠️ [Backtest] Finnhub 兜底获取历史数据失败: {e}")

    if data_source in ["auto", "yfinance"]:
        yf_interval_map = {"1d": "1d", "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"}
        yf_interval = yf_interval_map.get(interval, "1d")
        return await market_data.fetch_yf_data(ticker, "history", ttl=3600, period=period, interval=yf_interval)  # noqa: E501

    return False, None, f"未匹配到支持的数据源或该数据源无法获取 {ticker} 数据。"


# ─── 源码净化 & 可复现性 ────────────────────────────────────────────────


def _sanitize_source(code: str) -> str:
    """剥离策略源码中被禁止的 import（talib / BaseStrategy 等），与执行沙箱保持一致。"""
    code = re.sub(r"^\s*import\s+talib.*$", "", code, flags=re.MULTILINE)
    code = re.sub(r"^\s*from\s+talib\s+import.*$", "", code, flags=re.MULTILINE)
    code = re.sub(
        r"^\s*from\s+[\w\.]+\s+import\s+BaseStrategy.*$",
        "",
        code,
        flags=re.MULTILINE,
    )
    return code


async def _attach_reproducibility(report, safe_code, payload, persist: bool = False):
    """BT-02：为回测报告附加可复现性摘要（Snapshot + CodeHash + Manifest）。"""
    from backend.app.backtest.report_service import is_reproducible
    from backend.core.database import SessionLocal
    from backend.engine.contracts import RunManifest
    from backend.services.datalake.snapshot_resolver import SnapshotResolveError, SnapshotResolver

    code_hash = RunManifest.compute_code_hash(safe_code)
    data_mode = "unbound"
    manifest_hash = None
    snapshot_id = getattr(payload, "data_snapshot_id", None)
    db = SessionLocal()
    try:
        try:
            ref = SnapshotResolver(db).resolve(snapshot_id, manifest_hash=None)
            snapshot_id = ref.snapshot_id
            manifest_hash = ref.manifest_hash or None
            data_mode = ref.data_mode
        except SnapshotResolveError:
            data_mode = "unbound"
        except Exception:
            data_mode = "unbound"

        reproducible = is_reproducible(
            code_hash=code_hash,
            manifest_hash=manifest_hash,
            random_seed=getattr(payload, "random_seed", None),
            data_mode=data_mode,
        )
        manifest = RunManifest(
            run_id=str(uuid.uuid4()),
            mode="backtest",
            code_hash=code_hash,
            params=getattr(payload, "params", {}) or {},
            data_snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            random_seed=getattr(payload, "random_seed", None),
            data_mode=data_mode,  # type: ignore[arg-type]
            reproducible=reproducible,
        )
        if isinstance(report, dict):
            report = {**report, "manifest": manifest.to_summary()}

        if persist and isinstance(report, dict):
            from backend.app.backtest.report_service import BacktestReportService

            svc = BacktestReportService(db)
            row = svc.save(
                manifest,
                metrics=report.get("metrics") or report.get("stats") or {},
                equity_curve=report.get("equity_curve"),
                trades=report.get("trades"),
                symbol=getattr(payload, "ticker", ""),
            )
            report["persisted_run_id"] = row.run_id
            report["badge"] = svc.to_public_dict(row)["badge"]
    finally:
        db.close()
    return report


# ─── SSE 流式辅助 ──────────────────────────────────────────────────────


def _sse_headers() -> dict:
    """SSE 流式响应头：禁用代理缓冲，保证进度实时下推。"""
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_backtest_run(payload, chan: "asyncio.Queue") -> None:
    """通用沙箱回测流式 runner：消费 /run-sandbox 同款逻辑并推送进度。"""
    try:
        for mod in ["talib", "core", "core.strategy", "backtrader"]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = _sanitize_source(payload.source_code)

        success, df, msg = await _fetch_backtest_data(
            payload.ticker,
            payload.period,
            payload.data_source,
            payload.interval,
            snapshot_id=payload.data_snapshot_id,
        )
        if not success or df is None or df.empty:
            await chan.put({"type": "error", "message": f"回测数据加载失败: {msg}"})
            return

        def on_progress(p):
            chan.put_nowait(p)

        report = await run_cpu_bound_with_progress(
            run_dynamic_sandbox_backtest,
            safe_code,
            payload.class_name,
            payload.params,
            df,
            payload.initial_capital,
            payload.debug_mode,
            on_progress=on_progress,
        )

        report = await _attach_reproducibility(report, safe_code, payload, persist=payload.persist_report)
        await chan.put({"type": "result", "data": report})
    except ValueError as ve:
        await chan.put({"type": "error", "message": str(ve), "error_code": "SANDBOX_RUNTIME_ERROR"})
    except Exception:
        tb = safe_truncate(traceback.format_exc(), max_length=1500)
        await chan.put({"type": "error", "message": f"沙箱运行崩溃:\n{tb}", "error_code": "SANDBOX_RUNTIME_ERROR"})


# ─── 流式沙箱端点 ──────────────────────────────────────────────────────


@router.post(
    "/run-sandbox/stream",
    dependencies=[Depends(RateLimiter(max_requests=10, window_seconds=60, by_user=True)), Depends(get_current_user)],
)
async def run_strategy_sandbox_stream(payload: RunSandboxPayload):
    """SSE 流式沙箱回测：实时推送撮合进度，结束返回完整报告。"""
    chan: "asyncio.Queue" = asyncio.Queue()
    task = asyncio.create_task(_stream_backtest_run(payload, chan))

    async def gen():
        try:
            while True:
                item = await chan.get()
                yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
                if item.get("type") in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_sse_headers())


# ─── 非流式沙箱端点 ────────────────────────────────────────────────────


@router.post(
    "/run-sandbox",
    dependencies=[
        Depends(RateLimiter(max_requests=10, window_seconds=60, by_user=True)),
        Depends(get_current_user),
    ],
)  # noqa: E501
async def run_strategy_sandbox(payload: RunSandboxPayload):
    """接收前端动态生成的策略代码与参数，放入本地沙箱进行极速回测推演"""
    try:
        for mod in ["talib", "core", "core.strategy", "backtrader"]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = _sanitize_source(payload.source_code)

        success, df, msg = await _fetch_backtest_data(
            payload.ticker,
            payload.period,
            payload.data_source,
            payload.interval,
            snapshot_id=payload.data_snapshot_id,
        )  # noqa: E501
        if not success or df is None or df.empty:
            return {"status": "error", "message": f"回测数据加载失败: {msg}"}

        report = await run_cpu_bound(
            run_dynamic_sandbox_backtest,
            safe_code,
            payload.class_name,
            payload.params,
            df,
            payload.initial_capital,
            payload.debug_mode,  # noqa: E501
        )

        report = await _attach_reproducibility(report, safe_code, payload, persist=payload.persist_report)

        return {"status": "success", "message": "真实历史推演完成", "data": report}

    except ValueError as ve:
        return {
            "status": "error",
            "error_code": "SANDBOX_RUNTIME_ERROR",
            "message": str(ve),
            "data": {
                "error_detail": {
                    "exc_type": "ValueError",
                    "exc_message": str(ve),
                    "lineno": None,
                    "traceback": traceback.format_exc(),
                    "debug_tail": [],
                }
            },
        }
    except Exception:
        tb = traceback.format_exc()
        lineno = None
        exc_type = "UnknownError"
        exc_message = ""
        try:
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_tb:
                tb_frames = traceback.extract_tb(exc_tb)
                for frame in reversed(tb_frames):
                    if frame.filename and "<string>" in frame.filename:
                        lineno = frame.lineno
                        break
            exc_type = exc_type.__name__ if exc_type else "UnknownError"
            exc_message = str(exc_value) if exc_value else ""
        except Exception:
            pass

        return {
            "status": "error",
            "error_code": "SANDBOX_RUNTIME_ERROR",
            "message": f"沙箱运行崩溃:\n{safe_truncate(tb, max_length=1500)}",
            "data": {
                "error_detail": {
                    "exc_type": exc_type,
                    "exc_message": exc_message,
                    "lineno": lineno,
                    "traceback": tb,
                    "debug_tail": [],
                }
            },
        }  # noqa: E501


@router.post("/optimize-sandbox", dependencies=[Depends(get_current_user)])
async def optimize_strategy_sandbox(payload: OptimizeSandboxPayload):
    """接收带有数组的参数网格，并发极速寻找全局最优参数解"""
    try:
        for mod in ["talib", "core", "core.strategy", "backtrader"]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = _sanitize_source(payload.source_code)

        success, df, msg = await _fetch_backtest_data(
            payload.ticker, payload.period, payload.data_source, payload.interval
        )  # noqa: E501
        if not success or df is None or df.empty:
            return {"status": "error", "message": f"回测数据加载失败: {msg}"}

        top_results = await run_cpu_bound(
            run_grid_search_backtest,
            safe_code,
            payload.class_name,
            payload.param_grid,
            df,
            payload.initial_capital,
            payload.target_metric,  # noqa: E501
        )

        if not top_results:
            return {
                "status": "error",
                "message": "网格搜索未找到任何产生有效交易的参数组合。",
            }  # noqa: E501

        return {"status": "success", "message": "网格优化寻优完成", "data": top_results}

    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception:
        return {
            "status": "error",
            "message": f"寻优沙箱崩溃:\n{safe_truncate(traceback.format_exc(), max_length=1500)}",
        }  # noqa: E501


@router.post("/run-batch-sandbox", dependencies=[Depends(get_current_user)])
async def run_batch_strategy_sandbox(payload: BatchRunSandboxPayload):
    """针对 Screener 选股池结果执行横截面批量并发回测"""
    try:
        safe_code = _sanitize_source(payload.source_code)

        async def fetch_one(t):
            success, df, _ = await _fetch_backtest_data(t, payload.period, payload.data_source, payload.interval)  # noqa: E501
            return t, df if success else None

        fetch_tasks = [fetch_one(t) for t in payload.tickers]
        results = await asyncio.gather(*fetch_tasks)
        dfs = {t: df for t, df in results if df is not None and not df.empty}

        if not dfs:
            return {
                "status": "error",
                "message": "获取选股池任何标的的历史回测数据均失败。",
            }  # noqa: E501

        report = await run_cpu_bound(
            run_batch_sandbox_backtest,
            safe_code,
            payload.class_name,
            payload.params,
            dfs,
            payload.initial_capital,  # noqa: E501
        )

        return {"status": "success", "message": "全候选池批量推演完成", "data": report}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception:
        return {
            "status": "error",
            "message": f"批量回测崩溃:\n{safe_truncate(traceback.format_exc(), max_length=1500)}",
        }  # noqa: E501


@router.post("/monte-carlo-sandbox", dependencies=[Depends(get_current_user)])
async def monte_carlo_strategy_sandbox(payload: MonteCarloSandboxPayload):
    """蒙特卡洛压力测试接口：注入随机噪音进行百次模拟，验证策略鲁棒性"""
    try:
        for mod in ["talib", "core", "core.strategy", "backtrader"]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        safe_code = _sanitize_source(payload.source_code)

        success, df, msg = await _fetch_backtest_data(
            payload.ticker, payload.period, payload.data_source, payload.interval
        )  # noqa: E501
        if not success or df is None or df.empty:
            return {"status": "error", "message": f"回测数据加载失败: {msg}"}

        stock_features = {}
        info_success, info_data, _ = await market_data.fetch_yf_data(payload.ticker, "info", ttl=86400)  # noqa: E501
        if info_success and isinstance(info_data, dict):
            stock_features["market_cap"] = info_data.get("marketCap")
            stock_features["beta"] = info_data.get("beta")

        summary = await run_cpu_bound(
            run_monte_carlo_stress_test,
            safe_code,
            payload.class_name,
            payload.params,
            df,  # noqa: E501
            payload.initial_capital,
            payload.iterations,
            payload.noise_level,
            payload.noise_distribution,
            stock_features,  # noqa: E501
        )

        return {"status": "success", "message": "蒙特卡洛压力测试完成", "data": summary}

    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception:
        return {
            "status": "error",
            "message": f"蒙特卡洛沙箱崩溃:\n{safe_truncate(traceback.format_exc(), max_length=1500)}",
        }  # noqa: E501


@router.post("/deploy-to-oms", dependencies=[Depends(get_current_user)])
async def deploy_to_oms(payload: RunSandboxPayload):
    """将沙箱中跑通的最优策略进行物理持久化，并通过 BotRuntimeManager 启动真实 Bot 算力节点 (OMS-05)"""
    try:
        strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "live"))  # noqa: E501
        os.makedirs(strategies_dir, exist_ok=True)

        file_path = os.path.join(strategies_dir, f"{payload.class_name.lower()}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            header = "from __future__ import annotations\nimport numpy as np\nimport pandas as pd\nfrom typing import Dict, Any, Optional\nfrom backend.backtest import BaseStrategySandbox as BaseStrategy\n\n"  # noqa: E501
            f.write(header + payload.source_code)

        from backend.workers.oms.bot_runtime import bot_runtime

        bot_id = f"bot_{payload.class_name.lower()}_{int(time.time())}"
        await bot_runtime.start_bot(
            bot_id=bot_id,
            name=payload.class_name,
            ticker=payload.ticker,
            class_name=payload.class_name,
            params=payload.params or {},
        )

        return {
            "status": "success",
            "message": f"策略已物理挂载至 {file_path}，Bot 算力节点 {bot_id} 已启动！",
            "data": {"bot_id": bot_id, "file": file_path},
        }  # noqa: E501
    except Exception as e:
        return {"status": "error", "message": f"部署失败: {str(e)}"}

@router.post("/optimize-sandbox/stream", dependencies=[Depends(get_current_user)])
async def optimize_strategy_sandbox_stream(payload: OptimizeSandboxPayload):
    """SSE 流式寻优：实时推送网格遍历进度，结束返回 Top 组合。"""
    chan: "asyncio.Queue" = asyncio.Queue()

    async def runner():
        try:
            for mod in ["talib", "core", "core.strategy", "backtrader"]:
                if mod not in sys.modules:
                    sys.modules[mod] = MagicMock()

            safe_code = _sanitize_source(payload.source_code)

            success, df, msg = await _fetch_backtest_data(
                payload.ticker, payload.period, payload.data_source, payload.interval
            )
            if not success or df is None or df.empty:
                await chan.put({"type": "error", "message": f"回测数据加载失败: {msg}"})
                return

            def on_progress(p):
                chan.put_nowait(p)

            top_results = await run_cpu_bound_with_progress(
                run_grid_search_backtest,
                safe_code,
                payload.class_name,
                payload.param_grid,
                df,
                payload.initial_capital,
                payload.target_metric,
                on_progress=on_progress,
            )

            if not top_results:
                await chan.put({"type": "error", "message": "网格搜索未找到任何产生有效交易的参数组合。"})
                return
            await chan.put({"type": "result", "data": top_results})
        except ValueError as ve:
            await chan.put({"type": "error", "message": str(ve)})
        except Exception:
            await chan.put(
                {"type": "error", "message": f"寻优沙箱崩溃:\n{safe_truncate(traceback.format_exc(), max_length=1500)}"}
            )

    task = asyncio.create_task(runner())

    async def gen():
        try:
            while True:
                item = await chan.get()
                yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
                if item.get("type") in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_sse_headers())
