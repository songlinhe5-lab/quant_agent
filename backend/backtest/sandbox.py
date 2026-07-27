"""
沙箱安全与基础设施：AST 级代码扫描、高危模块拦截、目录穿越防护、超时/内存熔断、策略基类
"""

import ast
import builtins
import os
import sys
import time

import pandas as pd


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


# 💡 允许的安全装饰器：仅放行 Numba JIT 等纯性能优化装饰器。
# 回测引擎明确依赖 Numba 矢量化策略 (njit/jit)，故需放行其装饰器，
# 但仍封杀一切可能捕获闭包/篡改执行流的未授权装饰器 (如 staticmethod 之外的自定义装饰器)。
ALLOWED_DECORATORS = frozenset(
    {
        "njit",
        "jit",
        "vectorize",
        "guvectorize",
        "cfunc",
        "stencil",
    }
)


def _decorator_name(dec):
    """从装饰器 AST 节点提取名称，支持 @njit / @njit(...) / @numba.njit 等形式。"""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return None


# 💡 缓存已剥离 cache 参数的源码，避免对每个网格组合重复 AST 解析
_STRIP_CACHE_SOURCE: dict = {}


def strip_numba_cache_source(source_code: str) -> str:
    """返回剥离 Numba JIT 装饰器 cache= 参数后的源码。

    沙箱策略以字符串形式 exec，numba 无法为临时源码 ('<string>') 定位缓存文件，
    会抛 RuntimeError('cannot cache function ...: no locator available')。
    而缓存对一次性沙箱执行毫无收益，故移除 cache=True/False 等参数。
    """
    cached = _STRIP_CACHE_SOURCE.get(source_code)
    if cached is not None:
        return cached
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        # 交给后续流程报语法错误，此处原样返回
        _STRIP_CACHE_SOURCE[source_code] = source_code
        return source_code

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and _decorator_name(dec) in ALLOWED_DECORATORS:
                    dec.keywords = [k for k in dec.keywords if k.arg != "cache"]

    try:
        out = ast.unparse(tree)
    except Exception:
        out = source_code
    _STRIP_CACHE_SOURCE[source_code] = out
    return out


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
            "__future__",
            # 💡 Numba 矢量化是回测引擎的一等公民：放行导入，但运行期仍需经 _safe_import 与装饰器白名单双重校验
            "numba",
        }
        # 💡 新增：追踪当前所处的函数调用栈，用于侦测递归
        self.current_funcs = []

    def visit_FunctionDef(self, node):
        # 💡 安全风控：封杀未授权的函数装饰器，仅放行 Numba JIT 等纯性能优化装饰器。
        # 防止通过闭包和高阶函数篡改执行流或绕过递归检测。
        for dec in node.decorator_list:
            dname = _decorator_name(dec)
            if dname not in ALLOWED_DECORATORS:
                raise ValueError(
                    f"🚨 安全风控拦截：沙箱内严禁使用未授权装饰器 @{dname}！仅允许 Numba JIT 装饰器 (njit/jit/vectorize 等)。"  # noqa: E501
                )

        # 压入当前正在解析的函数名
        self.current_funcs.append(node.name)
        self.generic_visit(node)
        self.current_funcs.pop()

    def visit_ClassDef(self, node):
        # 💡 安全风控：封杀未授权的类装饰器，仅放行 Numba JIT 等性能优化装饰器
        for dec in node.decorator_list:
            dname = _decorator_name(dec)
            if dname not in ALLOWED_DECORATORS:
                raise ValueError(
                    f"🚨 安全风控拦截：沙箱内严禁使用未授权类装饰器 @{dname}！仅允许 Numba JIT 装饰器 (njit/jit 等)。"
                )
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


# ==========================================
# 沙箱基础设施：超时/内存熔断追踪器、策略基类
# ==========================================
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

        self._original_trace = sys.gettrace()
        self._trace_disabled = False

        # 💡 关键修复：如果检测到外部 trace 函数正在运行（如 coverage.py、pdb 等调试器），
        # 则禁用沙箱的 sys.settrace，避免覆盖外部 trace 导致覆盖率统计异常或调试中断。
        # sys.gettrace() 返回非 None 即表示有外部 trace 存在。
        if self._original_trace is not None:
            self._trace_disabled = True
            return self

        sys.settrace(self._trace_calls)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not getattr(self, "_trace_disabled", False):
            sys.settrace(self._original_trace)


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
