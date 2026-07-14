from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.backtest_app import BacktestDataError, BacktestParams, run_backtest
from backend.app.grid_search_app import (
    GridSearchError,
    GridSearchParams,
    run_grid_search,
)
from backend.app.monte_carlo_app import (
    MonteCarloError,
    MonteCarloParams,
    run_monte_carlo,
)
from backend.app.overfit_app import OverfitError, OverfitParams, run_overfit_check
from backend.app.walk_forward_app import (
    WalkForwardError,
    WalkForwardParams,
    run_walk_forward,
)

router = APIRouter(prefix="/backtest", tags=["Backtesting Engine"])


class BacktestRequest(BaseModel):
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
    params: Optional[Dict] = None


class WalkForwardRequest(BaseModel):
    """BT-03 Walk-Forward 滚动验证请求。"""

    ticker: str
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = Field(default="sma_cross", description="内置策略键，如 sma_cross")
    params: Dict = Field(default_factory=dict)
    param_grid: Optional[Dict[str, List]] = Field(
        default=None, description="可选：样本内网格寻优（笛卡尔积上限 48）"
    )
    train_bars: int = Field(default=120, ge=10)
    test_bars: int = Field(default=40, ge=5)
    step_bars: Optional[int] = Field(default=None, ge=1)
    anchored: bool = False
    target_metric: str = Field(default="sharpe", pattern="^(sharpe|total_return)$")


class MonteCarloRequest(BaseModel):
    """BT-04 蒙特卡洛压测：交易重排/自助抽样 + 分位曲线。"""

    ticker: str
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = Field(default="sma_cross")
    params: Dict = Field(default_factory=dict)
    iterations: int = Field(default=1000, ge=10, le=5000)
    method: str = Field(
        default="trade_bootstrap",
        pattern="^(trade_reshuffle|trade_bootstrap|return_bootstrap)$",
    )
    seed: Optional[int] = 42


class GridSearchRequest(BaseModel):
    """BT-05 参数网格搜索 + 夏普热力图矩阵。"""

    ticker: str
    param_grid: Dict[str, List] = Field(
        ..., description='例如 {"period": [10, 20, 30], "slow": [40, 60]}'
    )
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = "sma_cross"
    base_params: Dict = Field(default_factory=dict)
    target_metric: str = Field(
        default="sharpe", pattern="^(sharpe|total_return|max_drawdown)$"
    )
    max_workers: int = Field(default=0, ge=0, le=16, description="0=自动；1=串行")
    heatmap_x: Optional[str] = None
    heatmap_y: Optional[str] = None


class OverfitRequest(BaseModel):
    """BT-06 过拟合检测：Deflated Sharpe + 参数悬崖。"""

    ticker: str
    param_grid: Dict[str, List] = Field(
        ..., description="多重试炼参数网格（与 grid-search 同形）"
    )
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    data_source: str = "auto"
    data_snapshot_id: Optional[str] = None
    strategy_key: str = "sma_cross"
    base_params: Dict = Field(default_factory=dict)
    max_workers: int = Field(default=1, ge=0, le=16)
    dsr_warn_below: float = Field(default=0.95, ge=0.0, le=1.0)
    cliff_abs: float = Field(default=0.5, ge=0.0)
    cliff_rel: float = Field(default=0.35, ge=0.0, le=1.0)


@router.post("/run")
async def run_backtest_endpoint(req: BacktestRequest):
    """接收前端触发指令，拉取历史数据并运行高频回测（编排在 backtest_app）。"""
    params = BacktestParams(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        atr_multiplier=req.atr_multiplier,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        debug_mode=req.debug_mode,
        data_snapshot_id=req.data_snapshot_id,
        random_seed=req.random_seed,
        source_code=req.source_code,
        class_name=req.class_name,
        params=req.params,
    )
    try:
        return await run_backtest(params)
    except BacktestDataError as e:
        raise HTTPException(status_code=400, detail=e.message) from e


@router.post("/walk-forward")
async def walk_forward_endpoint(req: WalkForwardRequest):
    """BT-03：滚动窗口训练/验证 + 性能漂移检测（VectorBT 快路径）。"""
    params = WalkForwardParams(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        data_snapshot_id=req.data_snapshot_id,
        strategy_key=req.strategy_key,
        params=req.params or {},
        param_grid=req.param_grid,
        train_bars=req.train_bars,
        test_bars=req.test_bars,
        step_bars=req.step_bars,
        anchored=req.anchored,
        target_metric=req.target_metric,
    )
    try:
        return await run_walk_forward(params)
    except WalkForwardError as e:
        raise HTTPException(status_code=400, detail=e.message) from e


@router.post("/monte-carlo")
async def monte_carlo_endpoint(req: MonteCarloRequest):
    """BT-04：交易序列重排/自助抽样，输出 5/50/95 分位曲线与最坏回撤。"""
    params = MonteCarloParams(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        data_snapshot_id=req.data_snapshot_id,
        strategy_key=req.strategy_key,
        params=req.params or {},
        iterations=req.iterations,
        method=req.method,  # type: ignore[arg-type]
        seed=req.seed,
    )
    try:
        return await run_monte_carlo(params)
    except MonteCarloError as e:
        raise HTTPException(status_code=400, detail=e.message) from e


@router.post("/grid-search")
async def grid_search_endpoint(req: GridSearchRequest):
    """BT-05：参数网格并发回测 + 夏普热力图（ECharts heatmap 数据）。"""
    params = GridSearchParams(
        ticker=req.ticker,
        param_grid=req.param_grid,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        data_snapshot_id=req.data_snapshot_id,
        strategy_key=req.strategy_key,
        base_params=req.base_params or {},
        target_metric=req.target_metric,
        max_workers=req.max_workers,
        heatmap_x=req.heatmap_x,
        heatmap_y=req.heatmap_y,
    )
    try:
        return await run_grid_search(params)
    except GridSearchError as e:
        raise HTTPException(status_code=400, detail=e.message) from e


@router.post("/overfit")
async def overfit_endpoint(req: OverfitRequest):
    """BT-06：Deflated Sharpe Ratio + 相邻参数格性能悬崖检测。"""
    params = OverfitParams(
        ticker=req.ticker,
        param_grid=req.param_grid,
        period=req.period,
        interval=req.interval,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
        data_source=req.data_source,
        data_snapshot_id=req.data_snapshot_id,
        strategy_key=req.strategy_key,
        base_params=req.base_params or {},
        max_workers=req.max_workers,
        dsr_warn_below=req.dsr_warn_below,
        cliff_abs=req.cliff_abs,
        cliff_rel=req.cliff_rel,
    )
    try:
        return await run_overfit_check(params)
    except OverfitError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
