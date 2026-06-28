import ast
import builtins
import collections
import datetime
import itertools
import math
import os
import random
import sys
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

import numpy as np
import pandas as pd
import vectorbt as vbt


# ==========================================
# 🛡️ 核心风控：沙箱环境白名单与高危模块拦截
# ==========================================
def _safe_stat(stats_series, key):
    """安全提取 VectorBT 回测指标"""
    try:
        val = stats_series.get(key, 0.0)
        return float(val) if not pd.isna(val) else 0.0
    except Exception:
        return 0.0


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    dangerous_modules = {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "urllib",
        "requests",
        "pathlib",
        "pty",
        "multiprocessing",
        "threading",
        "concurrent",
        "_thread",
    }
    if name in dangerous_modules or any(name.startswith(f"{m}.") for m in dangerous_modules):
        raise ImportError(f"🚨 触发风控熔断：安全沙箱已拦截高危底层模块 '{name}' 的导入行为！")
    return __import__(name, globals, locals, fromlist, level)


# 💡 设定严格的沙箱文件读写目录，并自动创建
SANDBOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "sandbox_workspace"))
os.makedirs(SANDBOX_DIR, exist_ok=True)
# 确保目录以分隔符结尾，防范前缀匹配攻击 (如 sandbox_workspace2 绕过)
_SECURE_PREFIX = SANDBOX_DIR if SANDBOX_DIR.endswith(os.sep) else SANDBOX_DIR + os.sep


def _safe_open(
    file,
    mode="r",
    buffering=-1,
    encoding=None,
    errors=None,
    newline=None,
    closefd=True,
    opener=None,
):
    """带目录穿越防护的安全 open() 包装器"""
    # 剥除绝对路径前缀，防止利用 Linux 绝对路径如 /etc/passwd 绕过拼接
    safe_file = str(file).lstrip("/").lstrip("\\")
    abs_path = os.path.abspath(os.path.join(_SECURE_PREFIX, safe_file))

    # 核心防御：检查最终解析出的绝对物理路径，是否仍然位于隔离区内
    if not abs_path.startswith(_SECURE_PREFIX):
        raise PermissionError(
            f"🚨 安全风控拦截：沙箱环境严禁进行目录穿越 (Directory Traversal) 访问越权文件！(尝试访问: {file})"
        )

    return open(abs_path, mode, buffering, encoding, errors, newline, closefd, opener)


# 剥离读写文件 (open)、直接执行代码 (eval/exec) 及反射内存的高危内建权限
SAFE_BUILTINS = {
    k: v for k, v in builtins.__dict__.items() if k not in ("eval", "exec", "open", "compile", "globals", "locals")
}
SAFE_BUILTINS["__import__"] = _safe_import
SAFE_BUILTINS["open"] = _safe_open


class SandboxSecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        # 禁用可能被用于反射、动态执行、绕过的敏感函数名
        self.forbidden_names = {
            "getattr",
            "setattr",
            "delattr",
            "hasattr",
            "eval",
            "exec",
            "globals",
            "locals",
            "vars",
            "compile",
            "__import__",
            "sys",
            "os",
        }
        # 禁用魔术属性访问，切断对象树遍历的逃逸路径
        self.forbidden_attrs = {
            "__class__",
            "__subclasses__",
            "__base__",
            "__bases__",
            "__mro__",
            "__dict__",
            "__builtins__",
            "__globals__",
            "__getattribute__",
            "__code__",
            "__closure__",
            "__func__",
            "__self__",
            # 💡 性能风控：彻底封杀 Pandas 极度低效的行级遍历迭代器
            "iterrows",
            "itertuples",
            "iteritems",
        }
        # 💡 数据科学与量化白名单：允许大模型在代码中导入这些绝对安全的计算库
        self.allowed_modules = {
            "numpy",
            "pandas",
            "math",
            "datetime",
            "collections",
            "itertools",
            "scipy",
            "statsmodels",
            "sklearn",
            "lightgbm",
            "xgboost",
            "typing",
            "typing_extensions",
        }
        # 💡 新增：追踪当前所处的函数调用栈，用于侦测递归
        self.current_funcs = []

    def visit_FunctionDef(self, node):
        # 💡 安全风控：彻底封杀所有函数装饰器，防止通过闭包和高阶函数篡改执行流或绕过递归检测  # noqa: E501
        if node.decorator_list:
            dec_name = getattr(
                node.decorator_list[0],
                "id",
                getattr(getattr(node.decorator_list[0], "func", None), "id", "..."),
            )
            raise ValueError(
                f"🚨 安全风控拦截：沙箱内严禁使用函数装饰器 (如 @{dec_name})！请保持策略代码极简。"  # noqa: E501
            )

        # 压入当前正在解析的函数名
        self.current_funcs.append(node.name)
        self.generic_visit(node)
        self.current_funcs.pop()

    def visit_ClassDef(self, node):
        # 💡 安全风控：彻底封杀所有类装饰器
        if node.decorator_list:
            raise ValueError("🚨 安全风控拦截：沙箱内严禁使用类装饰器！")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in self.forbidden_names:
            raise ValueError(f"🚨 安全风控拦截：禁止使用高危函数/变量 '{node.id}'！")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in self.forbidden_attrs:
            raise ValueError(f"🚨 安全风控拦截：禁止访问高危魔术属性 '{node.attr}'！")
        self.generic_visit(node)

    def _check_range_iter(self, iter_node, context_name: str):
        """抽取公共逻辑：侦测危险的 range() 迭代器，防范低效运算与瞬间 OOM 内存炸弹"""
        if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name) and iter_node.func.id == "range":
            for arg in iter_node.args:
                # 1. 封堵低效的 range(len(df))
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "len":
                    raise ValueError(
                        f"🚨 性能风控拦截：严禁在 {context_name} 中使用 `range(len(...))` 遍历数据！请务必使用 Pandas 的矢量化运算。"  # noqa: E501
                    )
                # 2. 封堵硬编码超大常数 (如 range(10000000))
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, int) and arg.value > 10000:
                    raise ValueError(
                        f"🚨 内存风控拦截：严禁在 {context_name} 中使用超大范围 `range({arg.value})`，存在瞬间内存溢出 (OOM) 风险！"  # noqa: E501
                    )
                # 3. 封堵幂运算或乘法 (如 range(10**9) 或 range(1000 * 1000))
                elif isinstance(arg, ast.BinOp):
                    raise ValueError(
                        f"🚨 内存风控拦截：严禁在 {context_name} 的 range() 内进行数学表达式运算，存在 OOM 风险！"  # noqa: E501
                    )

    def visit_For(self, node):
        self._check_range_iter(node.iter, "for 循环")
        self.generic_visit(node)

    def visit_ListComp(self, node):
        for comp in node.generators:
            self._check_range_iter(comp.iter, "列表推导式 (List Comprehension)")
        self.generic_visit(node)

    def visit_DictComp(self, node):
        for comp in node.generators:
            self._check_range_iter(comp.iter, "字典推导式 (Dict Comprehension)")
        self.generic_visit(node)

    def visit_SetComp(self, node):
        for comp in node.generators:
            self._check_range_iter(comp.iter, "集合推导式 (Set Comprehension)")
        self.generic_visit(node)

    def visit_While(self, node):
        # 💡 性能与安全双重风控：彻底封杀 while 循环，防止大模型幻觉导致无限死循环或极度低效的参数逼近  # noqa: E501
        raise ValueError(
            "🚨 性能风控拦截：沙箱内严禁使用 `while` 循环！请务必使用 Numpy/Pandas 的矢量化矩阵运算来替代，以防死循环彻底耗尽系统算力。"  # noqa: E501
        )

    def visit_Call(self, node):
        # 💡 性能风控：侦测直接递归 (func()) 与类方法递归 (self.func())
        if self.current_funcs:
            current_func = self.current_funcs[-1]

            # 侦测独立函数递归 func()
            if isinstance(node.func, ast.Name) and node.func.id == current_func:
                raise ValueError(
                    f"🚨 性能风控拦截：沙箱内严禁使用递归调用 `{current_func}()`！请务必使用 Numpy/Pandas 的矢量化矩阵运算来替代，以防爆栈 (Stack Overflow)。"  # noqa: E501
                )

            # 侦测类方法递归 self.func()
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                if node.func.attr == current_func:
                    raise ValueError(
                        f"🚨 性能风控拦截：沙箱内严禁使用类方法递归 `self.{current_func}()`！请务必使用 Numpy/Pandas 的矢量化矩阵运算来替代，以防爆栈。"  # noqa: E501
                    )

        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            base_module = alias.name.split(".")[0]
            if base_module not in self.allowed_modules:
                raise ValueError(f"🚨 安全风控拦截：沙箱内禁止导入非白名单模块 '{alias.name}'。")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            base_module = node.module.split(".")[0]
            if base_module not in self.allowed_modules:
                raise ValueError(f"🚨 安全风控拦截：沙箱内禁止从非白名单模块 '{node.module}' 导入。")
        self.generic_visit(node)


def _verify_safe_code(source_code: str):
    """静态源码扫描 (AST级)：彻底封堵基于反射、拼接字符串和魔术方法的沙箱逃逸"""
    try:
        tree = ast.parse(source_code)
    except IndentationError as e:
        raise ValueError(
            f"策略源码存在缩进错误 (IndentationError): {e.msg} (第 {e.lineno} 行)。请严格检查代码的空格与缩进对齐。"  # noqa: E501
        )
    except SyntaxError as e:
        raise ValueError(f"策略源码存在语法错误，拒绝执行: {e.msg} (第 {e.lineno} 行)")

    visitor = SandboxSecurityVisitor()
    visitor.visit(tree)


class SandboxTimeoutException(Exception):
    pass


class SandboxMemoryException(Exception):
    pass


class SandboxTimeoutTracer:
    """基于 sys.settrace 的沙箱执行追踪器，防范死循环与内存溢出 (OOM)"""

    def __init__(self, timeout_seconds: float, max_memory_mb: float = 500.0):
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.start_time = 0.0
        self.start_memory = 0.0
        self.call_count = 0
        self.psutil_proc = None

        try:
            import os

            import psutil

            self.psutil_proc = psutil.Process(os.getpid())
        except ImportError:
            pass  # 如果宿主机未安装 psutil 则平滑降级，仅执行时间检测

    def _trace_calls(self, frame, event, arg):
        # 1. 检查执行时间
        if time.perf_counter() - self.start_time > self.timeout_seconds:
            raise SandboxTimeoutException(f"沙箱执行超时 ({self.timeout_seconds}s)！已强制阻断以保护系统资源。")

        # 2. 抽样检查内存增量 (每执行 5000 步指令检查一次，将系统调用开销降至 0)
        if self.psutil_proc:
            self.call_count += 1
            if self.call_count % 5000 == 0:
                try:
                    # 获取当前进程的 RSS 物理常驻内存，并转化为 MB
                    current_memory = self.psutil_proc.memory_info().rss / (1024 * 1024)
                    if current_memory - self.start_memory > self.max_memory_mb:
                        raise SandboxMemoryException(
                            f"沙箱内存溢出熔断！在执行期间增量消耗超过了 {self.max_memory_mb} MB，已强制打断防 OOM。"  # noqa: E501
                        )
                except Exception:
                    pass

        return self._trace_calls

    def __enter__(self):
        self.start_time = time.perf_counter()
        if self.psutil_proc:
            try:
                self.start_memory = self.psutil_proc.memory_info().rss / (1024 * 1024)
            except Exception:
                self.start_memory = 0.0
        sys.settrace(self._trace_calls)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.settrace(None)


class BaseStrategySandbox:
    """供大模型动态沙箱回测继承的策略基类桩"""

    df: pd.DataFrame  # 💡 添加类型注解，使得继承该类的子类在被静态分析时能被正确识别

    def __init__(self):
        self._position_size = 0
        self._position_data = {}
        self.df = pd.DataFrame()

    def has_position(self) -> bool:
        return self._position_size != 0

    def get_position(self) -> dict:
        return self._position_data


class EventDrivenBacktestEngine:
    """
    高保真事件驱动回测引擎 (Event-Driven Backtester)
    支持逐根 K 线推进、限价单穿透、动态止损以及真实的滑点与手续费磨损计算
    """

    def __init__(
        self,
        strategy_instance,
        df: pd.DataFrame,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0005,
        slippage_pct: float = 0.001,
        debug_mode: bool = False,
    ):
        self.strategy = strategy_instance
        self.df = df.copy()
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.debug_mode = debug_mode
        self.cash = initial_capital
        self.position = 0
        self.equity_curve = []
        self.trades = []
        self.total_friction_cost = 0.0
        self.pending_orders = []  # 💡 新增：挂单簿
        self.debug_logs = []  # 💡 新增：逐 K 线调试日志

    def _execute_buy(self, base_price: float, date_str: str, stop_loss: Optional[float] = None):
        """内部撮合：买入执行"""
        exec_price = base_price * (1 + self.slippage_pct)
        turnover = self.cash * 0.95
        fee = turnover * self.commission_pct
        trade_value = turnover - fee
        shares = int(trade_value / exec_price)

        if shares > 0:
            real_turnover = shares * exec_price
            real_fee = real_turnover * self.commission_pct
            self.cash -= real_turnover + real_fee
            self.position = shares
            self.total_friction_cost += real_fee + (shares * base_price * self.slippage_pct)

            if hasattr(self.strategy, "_position_size"):
                self.strategy._position_size = shares
                self.strategy._position_data = {
                    "size": shares,
                    "entry_price": exec_price,
                    "stop_loss": stop_loss,
                }

            self.trades.append(
                {
                    "date": date_str,
                    "action": "BUY",
                    "price": round(exec_price, 2),
                    "shares": shares,
                    "profit": 0.0,
                }
            )

    def _execute_sell(self, base_price: float, date_str: str):
        """内部撮合：卖出平仓执行"""
        exec_price = base_price * (1 - self.slippage_pct)
        revenue = self.position * exec_price
        fee = revenue * self.commission_pct

        buy_trades = [t for t in self.trades if t["action"] == "BUY"]
        last_buy_price = buy_trades[-1]["price"] if buy_trades else exec_price
        profit = revenue - fee - (self.position * last_buy_price)
        self.cash += revenue - fee

        self.total_friction_cost += fee + (self.position * base_price * self.slippage_pct)

        self.trades.append(
            {
                "date": date_str,
                "action": "SELL",
                "price": round(exec_price, 2),
                "shares": self.position,
                "profit": round(profit, 2),
            }
        )

        self.position = 0
        if hasattr(self.strategy, "_position_size"):
            self.strategy._position_size = 0
            self.strategy._position_data = {}

    def run(self) -> dict:
        df = self.df.dropna().copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()].copy()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col.lower()] = df[col]

        if len(df) < 10:
            raise ValueError("回测数据长度不足 (至少需要 10 根 K 线)")

        benchmark_start_price = float(df.iloc[0]["close"])

        for i in range(10, len(df)):
            window_df = df.iloc[: i + 1]
            current_bar = window_df.iloc[-1]
            current_price = float(current_bar["close"])
            current_open = float(current_bar.get("open", current_price))
            current_high = float(current_bar.get("high", current_price))
            current_low = float(current_bar.get("low", current_price))
            date_str = str(current_bar.name).split(" ")[0].split("T")[0]

            # --- 1. 检查并撮合历史挂单 (Limit Orders) ---
            for order in list(self.pending_orders):
                if order["action"] == "buy" and self.position == 0:
                    # 若最低价穿透了买入限价，判定为成交
                    if current_low <= order["limit_price"]:
                        # 模拟真实市场跳空：若开盘价即低于限价，以更优的开盘价成交
                        base_price = min(order["limit_price"], current_open)
                        self._execute_buy(base_price, date_str, order.get("stop_loss"))
                        self.pending_orders.remove(order)

                elif order["action"] == "sell" and self.position > 0:
                    # 若最高价穿透了卖出限价，判定为成交
                    if current_high >= order["limit_price"]:
                        # 模拟跳空：若开盘价即高于限价，以更优的开盘价成交
                        base_price = max(order["limit_price"], current_open)
                        self._execute_sell(base_price, date_str)
                        self.pending_orders.remove(order)

            # --- 2. 动态止损与风控拦截 ---
            if hasattr(self.strategy, "_position_data") and self.position > 0:
                sl = self.strategy._position_data.get("stop_loss")
                # 💡 优化：根据最低价 current_low 判定是否触发止损，而非基于收盘价，大幅提高防回撤精度  # noqa: E501
                if sl and current_low <= sl:
                    base_price = min(sl, current_open)  # 如果开盘跳空跌破止损，按劣势的开盘价强平
                    self._execute_sell(base_price, date_str)

                    # 如果触发了止损，需要清理之前可能遗留的止盈限价单
                    self.pending_orders = [o for o in self.pending_orders if o["action"] != "sell"]

            # --- 3. 策略产生新信号 ---
            signal = None
            if hasattr(self.strategy, "on_bar"):
                signal = self.strategy.on_bar(window_df)
            elif hasattr(self.strategy, "on_tick"):
                signal = self.strategy.on_tick(window_df)

            # --- 4. 信号与订单分发 ---
            if signal and isinstance(signal, dict):
                action = str(signal.get("action", "")).lower()
                limit_price = signal.get("limit_price")

                if action == "cancel":
                    self.pending_orders.clear()

                elif action == "buy" and self.position == 0:
                    if limit_price:
                        self.pending_orders.append(
                            {
                                "action": "buy",
                                "limit_price": float(limit_price),
                                "stop_loss": signal.get("stop_loss"),
                            }
                        )
                    else:
                        self._execute_buy(current_price, date_str, signal.get("stop_loss"))

                elif action in ["sell", "close"] and self.position > 0:
                    if limit_price:
                        self.pending_orders.append({"action": "sell", "limit_price": float(limit_price)})
                    else:
                        self._execute_sell(current_price, date_str)
                        self.pending_orders.clear()  # 平仓后清空可能存在的止盈挂单

            # --- 5. 记录 Debug 日志 ---
            current_equity = self.cash + self.position * current_price
            if self.debug_mode:
                sig_str = str(signal) if signal else "Hold"
                log_line = f"[{date_str}] P:{current_price:.2f} | Pos:{self.position} | Cash:{self.cash:.2f} | Eq:{current_equity:.2f} | Sig:{sig_str} | Pending:{len(self.pending_orders)}"  # noqa: E501
                self.debug_logs.append(log_line)

            self.equity_curve.append(
                {
                    "date": date_str,
                    "equity": round(current_equity, 2),
                    "benchmark": round(
                        self.initial_capital * (current_price / benchmark_start_price),
                        2,
                    ),
                    "price": round(current_price, 2),
                }
            )

        current_equity = self.cash + self.position * current_price
        total_return_val = (current_equity - self.initial_capital) / self.initial_capital

        if len(self.equity_curve) > 0:
            equity_series = pd.Series([e["equity"] for e in self.equity_curve])
            daily_returns = equity_series.pct_change().dropna()
            sharpe_ratio = (
                (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
                if len(daily_returns) > 0 and daily_returns.std() != 0
                else 0.0
            )
            cummax = equity_series.cummax()
            drawdowns = (equity_series - cummax) / cummax
            max_drawdown = drawdowns.min() if len(drawdowns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
            max_drawdown = 0.0

        sell_trades = [t for t in self.trades if t["action"] == "SELL"]
        winning_trades = [t for t in sell_trades if t["profit"] > 0]
        win_rate = len(winning_trades) / len(sell_trades) if len(sell_trades) > 0 else 0.0

        return {
            "metrics": {
                "engine": "🐢 Event-Driven",
                "total_return": f"{total_return_val * 100:.2f}%",
                "sharpe_ratio": f"{sharpe_ratio:.2f}",
                "max_drawdown": f"{max_drawdown * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_friction_cost": f"${self.total_friction_cost:,.2f}",
            },
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "debug_logs": self.debug_logs,
        }


def run_dynamic_sandbox_backtest(
    source_code: str,
    class_name: str,
    params: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    debug_mode: bool = False,
) -> dict:
    """
    运行大模型生成的动态策略 (真实逐 K 线事件驱动沙箱)
    """
    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

        strategy_instance = StrategyClass(**params)

    # 💡 [极速架构]: 侦测大模型生成的代码是否符合 Numba 矢量化规范，如果符合，无缝挂载到底层 C 级引擎极速运行  # noqa: E501
    # 💡 如果开启了 debug_mode，主动降级回高保真事件驱动引擎以捕获逐 K 线内部状态
    if (
        not debug_mode
        and hasattr(strategy_instance, "_calculate_indicators")
        and hasattr(strategy_instance, "_generate_signals")
    ):
        print(
            f"⚡️ [Backtest Engine] 检测到 {class_name} 支持矢量化，启用 Numba 高频引擎进行回测！"  # noqa: E501
        )

        # 💡 兼容大小写：防止大模型写 df['close'] 导致 KeyError: 'close'
        df_copy = df.copy()
        if isinstance(df_copy.columns, pd.MultiIndex):
            df_copy.columns = df_copy.columns.get_level_values(0)
        df_copy = df_copy.loc[:, ~df_copy.columns.duplicated()].copy()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df_copy.columns:
                df_copy[col.lower()] = df_copy[col]

        strategy_instance.df = df_copy
        with SandboxTimeoutTracer(timeout_seconds=5.0):
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()

        if len(res_df) < 10:
            raise ValueError("回测数据长度不足 (清洗 NaN 后数据少于 10 根)")

        entries = res_df["signal"] == 1
        exits = res_df["signal"] == 0
        short_entries = res_df["signal"] == -1
        short_exits = res_df["signal"] == 0

        # 智能推导大模型可能使用的止损乘数变量名
        atr_multi = params.get(
            "atr_multiplier",
            params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
        )
        sl_trail_pct = (res_df["atr"] * float(atr_multi)) / res_df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=res_df["Close"],
            open=res_df["Open"],
            high=res_df["High"],
            low=res_df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=short_exits,
            init_cash=float(initial_capital),
            fees=0.0005,
            slippage=0.001,
            sl_trail=sl_trail_pct,
            upon_long_conflict="reverse",
            upon_short_conflict="reverse",
            freq="1D",
        )

        stats = pf.stats()
        total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
        sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
        max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        total_fees = _safe_stat(stats, "Total Fees Paid")

        equity_curve = []
        trades = []

        equity_s = pf.value()
        benchmark_start_price = res_df["Close"].iloc[0]

        for date, eq in equity_s.items():
            date_str = str(date).split(" ")[0].split("T")[0]
            price = res_df.loc[date, "Close"]
            equity_curve.append(
                {
                    "date": date_str,
                    "equity": round(eq, 2),
                    "benchmark": round(initial_capital * (price / benchmark_start_price), 2),
                }
            )

        if not pf.trades.records_readable.empty:
            for _, tr in pf.trades.records_readable.iterrows():
                # 提取开仓点 (Entry)
                entry_date_str = str(tr["Entry Timestamp"]).split(" ")[0].split("T")[0]
                entry_action = "BUY" if tr["Direction"] == "Long" else "SHORT"
                trades.append(
                    {
                        "date": entry_date_str,
                        "action": entry_action,
                        "price": round(tr["Entry Price"], 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": 0.0,
                    }
                )

                # 提取平仓点 (Exit)
                exit_date_str = str(tr["Exit Timestamp"]).split(" ")[0].split("T")[0]
                exit_action = "SELL" if tr["Direction"] == "Long" else "COVER"
                trades.append(
                    {
                        "date": exit_date_str,
                        "action": exit_action,
                        "price": round(tr["Exit Price"], 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": round(tr["PnL"], 2),
                    }
                )

            # 保证前端收到的时间轴是正序的
            trades.sort(key=lambda x: x["date"])

        return {
            "metrics": {
                "engine": "⚡ VectorBT",
                "total_return": f"{total_return_val * 100:.2f}%",
                "sharpe_ratio": f"{sharpe_ratio:.2f}",
                "max_drawdown": f"{max_drawdown * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_friction_cost": f"${total_fees:,.2f}",
            },
            "equity_curve": equity_curve,
            "trades": trades,
            "limit_orders": [],
        }

    # =========================================================================
    # 启用全新的高保真事件驱动引擎兜底 (处理无法被 Numba 矢量化的复杂脚本)
    # =========================================================================
    if debug_mode:
        print(
            "🐛 [Backtest Engine] 调试模式已开启，强制降级至高保真事件驱动引擎以捕获逐 K 线状态！"  # noqa: E501
        )
    engine = EventDrivenBacktestEngine(strategy_instance, df, initial_capital=initial_capital, debug_mode=debug_mode)
    with SandboxTimeoutTracer(timeout_seconds=10.0):
        return engine.run()


class DivergenceResonanceStrategy:
    """
    [高频回测引擎]
    RSI/MACD 动能背离 + KDJ 交叉共振策略
    基于完全矢量化运算 (Vectorized) 实现百万级 K 线的极速回测
    """

    def __init__(
        self,
        df: pd.DataFrame,
        initial_capital: float = 100000.0,
        atr_multiplier: float = 2.0,
        commission_pct: float = 0.0005,
        slippage_pct: float = 0.001,
    ):
        self.df = df.copy()
        if isinstance(self.df.columns, pd.MultiIndex):
            self.df.columns = self.df.columns.get_level_values(0)
        self.df = self.df.loc[:, ~self.df.columns.duplicated()].copy()

        self.initial_capital = initial_capital
        self.atr_multiplier = atr_multiplier
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

    def _calculate_indicators(self):
        df = self.df

        # 1. MACD
        exp1 = df["Close"].ewm(span=12, adjust=False).mean()
        exp2 = df["Close"].ewm(span=26, adjust=False).mean()
        df["macd_diff"] = exp1 - exp2
        df["macd_dea"] = df["macd_diff"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = (df["macd_diff"] - df["macd_dea"]) * 2

        # 2. RSI (14)
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # 3. KDJ (9, 3, 3)
        low_min = df["Low"].rolling(window=9, min_periods=1).min()
        high_max = df["High"].rolling(window=9, min_periods=1).max()
        rsv = (df["Close"] - low_min) / (high_max - low_min + 1e-9) * 100
        df["k"] = rsv.fillna(50).ewm(com=2, adjust=False).mean()
        df["d"] = df["k"].ewm(com=2, adjust=False).mean()
        df["j"] = 3 * df["k"] - 2 * df["d"]

        # 4. ATR (14) - 用于波动率动态止损
        prev_close = df["Close"].shift(1)
        tr1 = df["High"] - df["Low"]
        tr2 = (df["High"] - prev_close).abs()
        tr3 = (df["Low"] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    def _generate_signals(self):
        df = self.df

        # 💡 高维矩阵位移：彻底消灭 for 循环，获取过去 T-N 的数据状态
        df["prev_close"] = df["Close"].shift(1)
        df["min_5"] = df["Close"].rolling(5).min().shift(1)
        df["max_5"] = df["Close"].rolling(5).max().shift(1)

        df["prev_rsi"] = df["rsi"].shift(1)
        df["prev_hist"] = df["macd_hist"].shift(1)
        df["prev_k"] = df["k"].shift(1)
        df["prev_d"] = df["d"].shift(1)

        # 💡 新增：计算过去 5 日平均成交量，用于过滤无效的背离信号
        df["vol_ma5"] = df["Volume"].rolling(5).mean().shift(1)

        # ==========================================
        # 🚀 核心算法：矩阵运算级形态识别
        # ==========================================
        is_new_low = (df["Close"] < df["prev_close"]) & (df["Close"] <= df["min_5"])
        is_new_high = (df["Close"] > df["prev_close"]) & (df["Close"] >= df["max_5"])

        # 💡 成交量过滤：只有在“缩量（动能衰竭）”或“放量（资金介入/出逃）”时，背离信号才算有效，过滤掉大量无量横盘的假信号  # noqa: E501
        is_vol_confirmed = (df["Volume"] < df["vol_ma5"] * 0.8) | (df["Volume"] > df["vol_ma5"] * 1.2)

        # 买入条件组 (底背离 + 低位金叉 + 成交量确认)
        rsi_bottom = is_new_low & (df["rsi"] > df["prev_rsi"]) & (df["rsi"] < 40) & is_vol_confirmed
        macd_bottom = is_new_low & (df["macd_hist"] < 0) & (df["macd_hist"] > df["prev_hist"]) & is_vol_confirmed
        kdj_golden = (df["k"] > df["d"]) & (df["prev_k"] <= df["prev_d"]) & (df["k"] < 50)

        # 卖出条件组 (顶背离 + 高位死叉 + 成交量确认)
        rsi_top = is_new_high & (df["rsi"] < df["prev_rsi"]) & (df["rsi"] > 60) & is_vol_confirmed
        macd_top = is_new_high & (df["macd_hist"] > 0) & (df["macd_hist"] < df["prev_hist"]) & is_vol_confirmed
        kdj_death = (df["k"] < df["d"]) & (df["prev_k"] >= df["prev_d"]) & (df["k"] > 50)

        # 多指标共振：至少一个背离配合 KDJ 交叉 -> 触发交易信号
        df["signal"] = 0
        buy_mask = (rsi_bottom | macd_bottom) & kdj_golden
        sell_mask = (rsi_top | macd_top) & kdj_death

        df.loc[buy_mask, "signal"] = 1
        df.loc[sell_mask, "signal"] = -1

    def run(self) -> Dict[str, Any]:
        self._calculate_indicators()
        self._generate_signals()
        df = self.df.dropna().copy()

        entries = df["signal"] == 1
        exits = df["signal"] == 0
        short_entries = df["signal"] == -1
        short_exits = df["signal"] == 0

        sl_trail_pct = (df["atr"] * self.atr_multiplier) / df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=df["Close"],
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=short_exits,
            init_cash=float(self.initial_capital),
            fees=self.commission_pct,
            slippage=self.slippage_pct,
            sl_trail=sl_trail_pct,
            upon_long_conflict="reverse",
            upon_short_conflict="reverse",
            freq="1D",
        )

        stats = pf.stats()
        total_return = _safe_stat(stats, "Total Return [%]") / 100.0
        ann_return = _safe_stat(stats, "Ann. Return [%]") / 100.0
        sharpe = _safe_stat(stats, "Sharpe Ratio")
        max_dd = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        total_trades = int(_safe_stat(stats, "Total Trades"))
        profit_factor = _safe_stat(stats, "Profit Factor")
        total_friction_cost = _safe_stat(stats, "Total Fees Paid")

        trades_list = []
        if not pf.trades.records_readable.empty:
            for _, tr in pf.trades.records_readable.iterrows():
                # 提取开仓点 (Entry)
                entry_date_str = str(tr["Entry Timestamp"]).split(" ")[0].split("T")[0]
                entry_action = "BUY" if tr["Direction"] == "Long" else "SHORT"
                trades_list.append(
                    {
                        "date": entry_date_str,
                        "action": entry_action,
                        "price": round(tr["Entry Price"], 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": 0.0,
                    }
                )

                # 提取平仓点 (Exit)
                exit_date_str = str(tr["Exit Timestamp"]).split(" ")[0].split("T")[0]
                exit_action = "SELL" if tr["Direction"] == "Long" else "COVER"
                trades_list.append(
                    {
                        "date": exit_date_str,
                        "action": exit_action,
                        "price": round(tr["Exit Price"], 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": round(tr["PnL"], 2),
                    }
                )
            trades_list.sort(key=lambda x: x["date"])

        # 为前端图表下发重采样的数据点
        df_chart = df.copy()
        df_chart["date"] = df_chart.index.astype(str).str.split(" ").str[0].str.split("T").str[0]
        df_chart["price"] = df_chart["Close"]
        df_chart["equity"] = pf.value().values
        df_chart["benchmark"] = self.initial_capital * (df_chart["Close"] / df_chart["Close"].iloc[0])
        equity_curve = (
            df_chart[["date", "equity", "benchmark", "price"]]
            .iloc[:: max(1, len(df_chart) // 200)]
            .to_dict(orient="records")
        )

        return {
            "metrics": {
                "total_return": f"{total_return * 100:.2f}%",
                "annualized_return": f"{ann_return * 100:.2f}%",
                "sharpe_ratio": f"{sharpe:.2f}",
                "max_drawdown": f"{max_dd * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_trades": total_trades,
                "profit_factor": f"{profit_factor:.2f}",
                "total_friction_cost": f"${total_friction_cost:,.2f}",
            },
            "equity_curve": equity_curve,
            "trades": trades_list,
            "limit_orders": [],
        }


def run_grid_search_backtest(
    source_code: str,
    class_name: str,
    param_grid: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    target_metric: str = "sharpe_ratio",
) -> list:
    """
    基于 Numba 的极速网格搜索 (Grid Search) 回测引擎。
    自动遍历 param_grid 中的所有参数组合的笛卡尔积，返回按 target_metric 降序排列的 Top N 结果。
    """  # noqa: E501
    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    # 💡 核心：构建所有参数组合的笛卡尔积 (例如: fast_ma=[10,20], slow_ma=[30,40] -> 4 种组合)  # noqa: E501
    combinations = list(itertools.product(*values))

    print(f"🚀 [Grid Search] 启动极速寻优！开始遍历 {len(combinations)} 组参数组合...")

    # 💡 兼容处理：自动为 DataFrame 附加小写的 ohlcv 列，防止大模型使用小写引发 KeyError
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()].copy()

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col.lower()] = df[col]

    results = []
    last_error = None
    for combo in combinations:
        params = dict(zip(keys, combo))
        try:
            with SandboxTimeoutTracer(timeout_seconds=3.0):
                strategy_instance = StrategyClass(**params)

                # 💡 性能防线：对于网格搜索，强烈建议只运行 Numba 矢量化的策略，拒绝运行老旧的 for 循环引擎  # noqa: E501
                if not (
                    hasattr(strategy_instance, "_calculate_indicators")
                    and hasattr(strategy_instance, "_generate_signals")
                ):
                    raise ValueError(
                        "Grid Search 仅支持 Numba 矢量化策略。请让大模型实现 _calculate_indicators 等函数。"  # noqa: E501
                    )

                strategy_instance.df = df.copy()
                strategy_instance._calculate_indicators()
                strategy_instance._generate_signals()

            res_df = strategy_instance.df
            if "signal" not in res_df.columns:
                res_df["signal"] = 0
            if "atr" not in res_df.columns:
                res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

            res_df = res_df.dropna().copy()
            if len(res_df) < 10:
                raise ValueError("回测数据长度不足 (清洗 NaN 后数据少于 10 根)")

            entries = res_df["signal"] == 1
            exits = res_df["signal"] == 0
            short_entries = res_df["signal"] == -1
            short_exits = res_df["signal"] == 0

            atr_multi = params.get(
                "atr_multiplier",
                params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
            )
            sl_trail_pct = (res_df["atr"] * float(atr_multi)) / res_df["Close"]

            pf = vbt.Portfolio.from_signals(
                close=res_df["Close"],
                open=res_df["Open"],
                high=res_df["High"],
                low=res_df["Low"],
                entries=entries,
                exits=exits,
                short_entries=short_entries,
                short_exits=short_exits,
                init_cash=float(initial_capital),
                fees=0.0005,
                slippage=0.001,
                sl_trail=sl_trail_pct,
                upon_long_conflict="reverse",
                upon_short_conflict="reverse",
                freq="1D",
            )

            stats = pf.stats()
            total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
            sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
            max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
            win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
            total_trades = int(_safe_stat(stats, "Total Trades"))

            results.append(
                {
                    "params": params,
                    "raw_metrics": {
                        "total_return": total_return_val,
                        "sharpe_ratio": sharpe_ratio,
                        "max_drawdown": max_drawdown,
                        "win_rate": win_rate,
                        "total_trades": total_trades,
                    },
                }
            )
        except Exception as e:
            last_error = e
            continue  # 容错：跳过报错的异常组合

    if not results:
        if last_error is not None:
            # 💡 将单纯的文本抛出，升级为带异常类型的抛出，方便在前端直观定位死因
            raise ValueError(
                f"全部参数组合均执行失败，未产生有效交易。\n诊断信息: {type(last_error).__name__}: {last_error}"  # noqa: E501
            )
        return []

    # 💡 按照设定的核心指标 (例如 sharpe_ratio 或 win_rate) 进行全局降序排列
    results.sort(key=lambda x: x["raw_metrics"].get(target_metric, 0.0), reverse=True)

    # 截取 Top 10 并格式化输出给前端
    return [
        {
            "params": r["params"],
            "metrics": {
                "total_return": f"{r['raw_metrics']['total_return'] * 100:.2f}%",
                "sharpe_ratio": f"{r['raw_metrics']['sharpe_ratio']:.2f}",
                "max_drawdown": f"{r['raw_metrics']['max_drawdown'] * 100:.2f}%",
                "win_rate": f"{r['raw_metrics']['win_rate'] * 100:.2f}%",
                "total_trades": r["raw_metrics"]["total_trades"],
            },
        }
        for r in results[:10]
    ]


def run_monte_carlo_stress_test(
    source_code: str,
    class_name: str,
    params: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    iterations: int = 100,
    noise_level: float = 1.0,
    noise_distribution: str = "laplace",
    stock_features: Optional[dict] = None,
) -> dict:
    """
    基于 Numba 引擎的蒙特卡洛压力测试 (Monte Carlo Stress Test)
    通过向历史价格注入高斯噪声，重复运行 N 次回测，评估策略在未知市场扰动下的鲁棒性。
    """
    local_scope = {}
    global_scope = {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }

    # 💡 终极类型防线：强制开启注解延迟解析，彻底免疫大模型幻觉生成的 Any[str] 等非法类型导致的沙箱崩溃  # noqa: E501
    if "from __future__ import annotations" not in source_code:
        source_code = "from __future__ import annotations\n" + source_code

    _verify_safe_code(source_code)

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()].copy()

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col.lower()] = df[col]

    base_close = df["Close"].to_numpy(dtype=np.float64)
    returns = pd.Series(base_close).pct_change().dropna()
    hist_vol = returns.std() if len(returns) > 1 else 0.02

    results = []
    print(f"🎲 [Monte Carlo] 启动蒙特卡洛压力测试，将进行 {iterations} 次加噪模拟...")

    # 💡 动态调整噪音水平：根据资产的多维特征进行自适应扰动惩罚
    dynamic_noise_multiplier = 1.0
    if stock_features:
        market_cap = stock_features.get("market_cap")
        if market_cap is not None and market_cap < 2_000_000_000.0:
            dynamic_noise_multiplier *= 2.0
            print(
                "📊 [Monte Carlo] 属性感知: 检测到小盘股 (市值 < 20亿)，环境噪音自动翻倍。"  # noqa: E501
            )

        beta = stock_features.get("beta")
        if beta is not None and beta > 1.5:
            dynamic_noise_multiplier *= 1.5
            print(
                "📊 [Monte Carlo] 属性感知: 检测到高波动标的 (Beta > 1.5)，环境噪音放大 50%。"  # noqa: E501
            )

    for i in range(iterations):
        noisy_df = df.copy()

        # 💡 结合动态惩罚系数计算目标标准差
        target_std = hist_vol * noise_level * dynamic_noise_multiplier

        if noise_distribution == "laplace":
            # 拉普拉斯分布 (双指数分布)：尖峰胖尾，方差为 2 * scale^2。为了对齐目标波动率，scale = std / sqrt(2)  # noqa: E501
            scale = target_std / np.sqrt(2)
            noise = np.random.laplace(0, scale, len(noisy_df))
        elif noise_distribution == "t":
            # 学生 t-分布 (df=3)：具有极强的肥尾特性，方差为 df / (df - 2) = 3。对齐波动率 scale = std / sqrt(3)  # noqa: E501
            scale = target_std / np.sqrt(3)
            noise = np.random.standard_t(df=3, size=len(noisy_df)) * scale
        else:
            # 经典高斯正态分布：尾部过于平滑，容易低估极端风险
            noise = np.random.normal(0, target_std, len(noisy_df))

        noise_multiplier = 1.0 + noise

        # 💡 新增：给成交量 (Volume) 注入对数正态分布噪音 (Log-Normal Noise)
        # 成交量不能为负且呈典型的右偏分布，真实市场中常有“地量”和“天量”的流动性突变。
        # 设定成交量的波动率倍数大于价格波动率，为了保持期望值为 1.0（长期平均成交量不变），mean 设为 -0.5 * sigma^2  # noqa: E501
        vol_sigma = target_std * 2.0 * dynamic_noise_multiplier
        vol_mu = -0.5 * (vol_sigma**2)
        volume_multiplier = np.random.lognormal(mean=vol_mu, sigma=vol_sigma, size=len(noisy_df))

        noisy_df["Close"] = noisy_df["Close"] * noise_multiplier
        noisy_df["Open"] = noisy_df["Open"] * noise_multiplier
        noisy_df["High"] = noisy_df["High"] * noise_multiplier
        noisy_df["Low"] = noisy_df["Low"] * noise_multiplier
        if "Volume" in noisy_df.columns:
            noisy_df["Volume"] = np.maximum(1.0, noisy_df["Volume"] * volume_multiplier)

        with SandboxTimeoutTracer(timeout_seconds=3.0):
            strategy_instance = StrategyClass(**params)
            if not (
                hasattr(strategy_instance, "_calculate_indicators") and hasattr(strategy_instance, "_generate_signals")
            ):
                raise ValueError("Monte Carlo 测试仅支持 Numba 矢量化策略。")

            strategy_instance.df = noisy_df
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()
        if len(res_df) < 10:
            continue

        atr_multi = float(
            params.get(
                "atr_multiplier",
                params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
            )
        )

        entries = res_df["signal"] == 1
        short_entries = res_df["signal"] == -1
        exits = res_df["signal"] == 0
        sl_trail_pct = (res_df["atr"] * atr_multi) / res_df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=res_df["Close"],
            open=res_df["Open"],
            high=res_df["High"],
            low=res_df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=exits,
            init_cash=float(initial_capital),
            fees=0.0005,
            slippage=0.001,
            sl_trail=sl_trail_pct,
            upon_long_conflict="reverse",
            upon_short_conflict="reverse",
            freq="1D",
        )

        stats = pf.stats()
        total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
        sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
        max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        profit_factor = _safe_stat(stats, "Profit Factor")
        total_trades = _safe_stat(stats, "Total Trades")

        results.append(
            {
                "total_return": total_return_val,
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown": max_drawdown,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_trades": total_trades,
            }
        )

    if not results:
        raise ValueError("蒙特卡洛测试失败，所有模拟均未产生有效数据。")

    returns_arr = np.array([r["total_return"] for r in results], dtype=np.float64)
    sharpes_arr = np.array([r["sharpe_ratio"] for r in results], dtype=np.float64)
    mdds_arr = np.array([r["max_drawdown"] for r in results], dtype=np.float64)
    win_rates_arr = np.array([r["win_rate"] for r in results], dtype=np.float64)
    pfs_arr = np.array([r["profit_factor"] for r in results], dtype=np.float64)
    trades_arr = np.array([r["total_trades"] for r in results], dtype=np.float64)

    return {
        "iterations": len(results),
        "mean_return": f"{np.mean(returns_arr) * 100:.2f}%",
        "median_return": f"{np.median(returns_arr) * 100:.2f}%",
        "worst_return": f"{np.min(returns_arr) * 100:.2f}%",
        "best_return": f"{np.max(returns_arr) * 100:.2f}%",
        "win_rate_of_simulations": f"{(np.sum(returns_arr > 0) / len(returns_arr)) * 100:.2f}%",  # noqa: E501
        "mean_sharpe": f"{np.mean(sharpes_arr):.2f}",
        "worst_max_drawdown": f"{np.min(mdds_arr) * 100:.2f}%",
        "mean_win_rate": f"{np.mean(win_rates_arr) * 100:.2f}%",
        "mean_profit_factor": f"{np.mean(pfs_arr):.2f}",
        "mean_total_trades": int(np.mean(trades_arr)),
        # Raw data available for plotting the bell curve on the frontend!
        "raw_returns": returns_arr.tolist(),
        # Raw data available for plotting the box plot on the frontend!
        "raw_max_drawdowns": mdds_arr.tolist(),
    }


def run_batch_sandbox_backtest(
    source_code: str,
    class_name: str,
    params: dict,
    dfs: Dict[str, pd.DataFrame],
    initial_capital: float = 100000.0,
) -> dict:
    """
    基于 VectorBT 的多标的横截面批量回测引擎。
    支持对选股器 (Screener) 产出的备选池进行统一并行回测，输出合并的投资组合绩效指标。
    """
    if not dfs:
        raise ValueError("未提供任何回测数据源 (DataFrames 字典为空)")

    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }

    if "from __future__ import annotations" not in source_code:
        source_code = "from __future__ import annotations\n" + source_code

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    close_dict, open_dict, high_dict, low_dict = {}, {}, {}, {}
    entries_dict, exits_dict, short_entries_dict, short_exits_dict = {}, {}, {}, {}
    sl_trail_dict = {}

    atr_multi = float(
        params.get(
            "atr_multiplier",
            params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
        )
    )
    valid_tickers = []

    for ticker, df in dfs.items():
        if df.empty or len(df) < 10:
            continue

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()].copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col.lower()] = df[col]

        with SandboxTimeoutTracer(timeout_seconds=3.0):
            strategy_instance = StrategyClass(**params)
            if not (
                hasattr(strategy_instance, "_calculate_indicators") and hasattr(strategy_instance, "_generate_signals")
            ):
                raise ValueError("批量回测仅支持纯 Pandas Numba 矢量化策略。")

            strategy_instance.df = df
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()
        if len(res_df) < 10:
            continue

        close_dict[ticker] = res_df["Close"]
        open_dict[ticker] = res_df["Open"]
        high_dict[ticker] = res_df["High"]
        low_dict[ticker] = res_df["Low"]
        entries_dict[ticker] = res_df["signal"] == 1
        exits_dict[ticker] = res_df["signal"] == 0
        short_entries_dict[ticker] = res_df["signal"] == -1
        short_exits_dict[ticker] = res_df["signal"] == 0
        sl_trail_dict[ticker] = (res_df["atr"] * atr_multi) / res_df["Close"]

        valid_tickers.append(ticker)

    if not valid_tickers:
        raise ValueError("所有备选池标的清洗后有效数据均不足，批量回测终止。")

    # 将标的矩阵对其，由于交易日历可能略有差异，合并为一个包含全部日期的 Multi-Column DataFrame  # noqa: E501
    close_df = pd.DataFrame(close_dict).ffill()
    open_df = pd.DataFrame(open_dict).ffill()
    high_df = pd.DataFrame(high_dict).ffill()
    low_df = pd.DataFrame(low_dict).ffill()
    entries_df = pd.DataFrame(entries_dict).fillna(False)
    exits_df = pd.DataFrame(exits_dict).fillna(False)
    short_entries_df = pd.DataFrame(short_entries_dict).fillna(False)
    short_exits_df = pd.DataFrame(short_exits_dict).fillna(False)
    sl_trail_df = pd.DataFrame(sl_trail_dict).fillna(0.02)

    # 资金等权分配 (Equally Weighted)
    per_asset_capital = initial_capital / len(valid_tickers)

    # 🚀 核心：通过 group_by=True，将多个标的的独立交易合成为一个主组合 (Portfolio)
    pf = vbt.Portfolio.from_signals(
        close=close_df,
        open=open_df,
        high=high_df,
        low=low_df,
        entries=entries_df,
        exits=exits_df,
        short_entries=short_entries_df,
        short_exits=short_exits_df,
        init_cash=per_asset_capital,
        fees=0.0005,
        slippage=0.001,
        sl_trail=sl_trail_df,
        upon_long_conflict="reverse",
        upon_short_conflict="reverse",
        freq="1D",
        group_by=True,
    )

    stats = pf.stats()
    total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
    sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
    max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
    win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
    profit_factor = _safe_stat(stats, "Profit Factor")
    total_trades = int(_safe_stat(stats, "Total Trades"))

    # 聚合后的净值曲线
    equity_s = pf.value()
    equity_curve = [{"date": str(d).split(" ")[0].split("T")[0], "equity": round(e, 2)} for d, e in equity_s.items()]

    return {
        "metrics": {
            "engine": "⚡ VectorBT (Batch Pool)",
            "total_return": f"{total_return_val * 100:.2f}%",
            "sharpe_ratio": f"{sharpe_ratio:.2f}",
            "max_drawdown": f"{max_drawdown * 100:.2f}%",
            "win_rate": f"{win_rate * 100:.2f}%",
            "profit_factor": f"{profit_factor:.2f}",
            "total_trades": total_trades,
        },
        "valid_tickers": valid_tickers,
        "equity_curve": equity_curve,
    }
