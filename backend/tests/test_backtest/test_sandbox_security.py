"""
沙箱安全机制测试：_safe_stat, _safe_import, _safe_open, SandboxSecurityVisitor, _verify_safe_code
"""

import ast
import os

import pandas as pd
import pytest

from backend.backtest import (
    _SECURE_PREFIX,
    SAFE_BUILTINS,
    SANDBOX_DIR,
    SandboxSecurityVisitor,
    _safe_import,
    _safe_open,
    _safe_stat,
    _verify_safe_code,
)


# ─── _safe_stat ─────────────────────────────────────────────────────
class TestSafeStat:
    def test_normal_value(self):
        s = pd.Series({"sharpe": 1.5, "max_drawdown": -0.1})
        assert _safe_stat(s, "sharpe") == 1.5

    def test_missing_key(self):
        s = pd.Series({"a": 1})
        assert _safe_stat(s, "nonexistent") == 0.0

    def test_nan_value(self):
        s = pd.Series({"a": float("nan")})
        assert _safe_stat(s, "a") == 0.0

    def test_exception_handling(self):
        class BadSeries:
            def get(self, key, default):
                raise Exception("Test exception")

        assert _safe_stat(BadSeries(), "test") == 0.0


# ─── _safe_import ───────────────────────────────────────────────────
class TestSafeImport:
    def test_import_numpy_allowed(self):
        assert _safe_import("numpy") is not None

    def test_import_pandas_allowed(self):
        assert _safe_import("pandas") is not None

    def test_import_os_blocked(self):
        with pytest.raises(ImportError, match="高危底层模块"):
            _safe_import("os")

    def test_import_subprocess_blocked(self):
        with pytest.raises(ImportError, match="高危底层模块"):
            _safe_import("subprocess")

    def test_import_os_path_blocked(self):
        with pytest.raises(ImportError, match="高危底层模块"):
            _safe_import("os.path")


# ─── _safe_open ─────────────────────────────────────────────────────
class TestSafeOpen:
    def test_open_safe_file(self):
        test_file = os.path.join(SANDBOX_DIR, "test_safe_open.txt")
        with open(test_file, "w") as f:
            f.write("hello")
        try:
            with _safe_open("test_safe_open.txt", "r") as f:
                assert f.read() == "hello"
        finally:
            os.remove(test_file)

    def test_open_directory_traversal_blocked(self):
        with pytest.raises(PermissionError, match="目录穿越"):
            _safe_open("../../etc/passwd", "r")


# ─── SAFE_BUILTINS ──────────────────────────────────────────────────
class TestSafeBuiltins:
    def test_safe_builtins_exist(self):
        for name in ["print", "len", "range", "int", "float", "str"]:
            assert name in SAFE_BUILTINS

    def test_dangerous_builtins_removed(self):
        for name in ["eval", "exec", "compile", "globals", "locals"]:
            assert name not in SAFE_BUILTINS

    def test_safe_open_replaced(self):
        assert SAFE_BUILTINS["open"] is _safe_open

    def test_safe_import_replaced(self):
        assert SAFE_BUILTINS["__import__"] is _safe_import


# ─── SandboxSecurityVisitor + _verify_safe_code ─────────────────────
class TestSandboxSecurityVisitor:
    def _check(self, code: str):
        _verify_safe_code(code)

    # --- 安全代码通过 ---
    def test_safe_code_passes(self):
        self._check("import numpy as np\nimport pandas as pd\ndef calc(data):\n    return data.rolling(20).mean()")

    def test_allowed_import_numpy(self):
        self._check("import numpy as np")

    def test_allowed_import_pandas(self):
        self._check("import pandas as pd")

    def test_allowed_import_from_numpy(self):
        self._check("from numpy import array")

    def test_allowed_class_def(self):
        self._check("class MyStrategy:\n    def calc(self, df):\n        return df.mean()")

    def test_allowed_function_def(self):
        self._check("def calculate(df):\n    return df.mean()")

    # --- 高危函数拦截 ---
    def test_blocked_eval(self):
        with pytest.raises(ValueError, match="eval"):
            self._check("result = eval('1+1')")

    def test_blocked_exec(self):
        with pytest.raises(ValueError, match="exec"):
            self._check("exec('print(1)')")

    def test_blocked_os(self):
        with pytest.raises(ValueError, match="os"):
            self._check("os.system('ls')")

    def test_blocked_getattr(self):
        with pytest.raises(ValueError, match="getattr"):
            self._check("x = getattr(obj, 'attr')")

    # --- 魔术属性拦截 ---
    def test_blocked_class_attr(self):
        with pytest.raises(ValueError, match="__class__"):
            self._check("x = obj.__class__")

    def test_blocked_subclasses(self):
        with pytest.raises(ValueError, match="__subclasses__"):
            self._check("x = obj.__subclasses__")

    def test_blocked_bases(self):
        with pytest.raises(ValueError, match="__bases__"):
            self._check("x = obj.__bases__")

    def test_blocked_iterrows(self):
        with pytest.raises(ValueError, match="iterrows"):
            self._check("df.iterrows()")

    # --- 装饰器拦截 ---
    def test_blocked_function_decorator(self):
        with pytest.raises(ValueError, match="装饰器"):
            self._check("@staticmethod\ndef my_func():\n    pass")

    def test_blocked_class_decorator(self):
        with pytest.raises(ValueError, match="装饰器"):
            self._check("@some_decorator\nclass MyClass:\n    pass")

    # --- range 拦截 ---
    def test_blocked_range_len(self):
        with pytest.raises(ValueError, match="range\\(len"):
            self._check("for i in range(len(df)):\n    print(i)")

    def test_blocked_large_range(self):
        with pytest.raises(ValueError, match="超大范围"):
            self._check("def process():\n    for i in range(10000000):\n        pass")

    def test_blocked_range_binop(self):
        with pytest.raises(ValueError, match="数学表达式"):
            self._check("def process():\n    for i in range(10 ** 9):\n        pass")

    def test_blocked_list_comp_range_len(self):
        with pytest.raises(ValueError, match="range\\(len"):
            self._check("[x for x in range(len(df))]")

    def test_blocked_dict_comp_range_len(self):
        with pytest.raises(ValueError, match="range\\(len"):
            self._check("{x: x for x in range(len(df))}")

    def test_blocked_set_comp_range_len(self):
        with pytest.raises(ValueError, match="range\\(len"):
            self._check("{x for x in range(len(df))}")

    def test_allowed_set_comp(self):
        visitor = SandboxSecurityVisitor()
        tree = ast.parse("{x for x in range(10)}")
        visitor.visit(tree)

    # --- while 拦截 ---
    def test_blocked_while(self):
        with pytest.raises(ValueError, match="while"):
            self._check("while True:\n    pass")

    # --- 递归拦截 ---
    def test_blocked_direct_recursion(self):
        with pytest.raises(ValueError, match="递归"):
            self._check("def factorial(n):\n    return n * factorial(n - 1)")

    def test_blocked_self_recursion(self):
        with pytest.raises(ValueError, match="递归"):
            self._check("class MyStrategy:\n    def calc(self, df):\n        return self.calc(df)")

    # --- 导入拦截 ---
    def test_blocked_import_requests(self):
        with pytest.raises(ValueError, match="非白名单模块"):
            self._check("import requests")

    def test_blocked_from_os_import(self):
        with pytest.raises(ValueError, match="非白名单模块"):
            self._check("from os import path")

    def test_blocked_from_requests_import(self):
        with pytest.raises(ValueError, match="非白名单模块"):
            self._check("from requests import get")

    # --- 语法错误检测 ---
    def test_syntax_error(self):
        with pytest.raises(ValueError, match="语法错误"):
            self._check("def invalid syntax here")


# ─── 沙箱目录结构 ───────────────────────────────────────────────────
class TestSandboxDir:
    def test_sandbox_dir_exists(self):
        assert os.path.isdir(SANDBOX_DIR)

    def test_secure_prefix(self):
        assert _SECURE_PREFIX.endswith(os.sep)
