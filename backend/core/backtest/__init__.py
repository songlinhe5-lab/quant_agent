"""
回测引擎子包：沙箱安全、事件驱动引擎、矢量化策略、网格搜索/蒙特卡洛/批量回测
"""

from .event_engine import EventDrivenBacktestEngine, run_dynamic_sandbox_backtest
from .runners import run_batch_sandbox_backtest, run_grid_search_backtest, run_monte_carlo_stress_test
from .sandbox import (
    SAFE_BUILTINS,
    SANDBOX_DIR,
    BaseStrategySandbox,
    SandboxMemoryException,
    SandboxSecurityVisitor,
    SandboxTimeoutException,
    SandboxTimeoutTracer,
    _safe_import,
    _safe_open,
    _safe_stat,
    _SECURE_PREFIX,
    _verify_safe_code,
)
from .strategies import DivergenceResonanceStrategy

__all__ = [
    # sandbox
    "_safe_stat",
    "_safe_import",
    "_safe_open",
    "SANDBOX_DIR",
    "_SECURE_PREFIX",
    "SAFE_BUILTINS",
    "SandboxSecurityVisitor",
    "_verify_safe_code",
    "SandboxTimeoutException",
    "SandboxMemoryException",
    "SandboxTimeoutTracer",
    "BaseStrategySandbox",
    # event_engine
    "EventDrivenBacktestEngine",
    "run_dynamic_sandbox_backtest",
    # strategies
    "DivergenceResonanceStrategy",
    # runners
    "run_grid_search_backtest",
    "run_monte_carlo_stress_test",
    "run_batch_sandbox_backtest",
]
