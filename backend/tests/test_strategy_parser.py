"""单测：domain/strategy_parser.parse_strategy_parameters

覆盖：成功提取带类型/默认值的参数、Sphinx/Google 风格 docstring 解析、
语法错误/缩进错误/无策略类/保留字(self/args/kwargs/context)排除。
"""

import pytest

from backend.domain.strategy_parser import parse_strategy_parameters


def _find(params, name):
    for p in params:
        if p["name"] == name:
            return p
    return None


def test_extract_typed_params_with_defaults():
    src = '''
class MyStrategy(BaseStrategy):
    """我的策略

    :param fast_ma: 快速均线周期
    :param slow_ma: 慢速均线周期
    """
    def __init__(self, fast_ma: int = 10, slow_ma: int = 30, context=None):
        self.fast_ma = fast_ma
'''
    res = parse_strategy_parameters(src)
    assert res["status"] == "success"
    strategies = res["data"]
    assert len(strategies) == 1
    assert strategies[0]["class_name"] == "MyStrategy"

    params = strategies[0]["parameters"]
    fast = _find(params, "fast_ma")
    slow = _find(params, "slow_ma")
    assert fast is not None and slow is not None
    assert fast["type"] == "int" and fast["default"] == 10
    assert slow["type"] == "int" and slow["default"] == 30
    # 有默认值 -> 非必填；保留字 context 应被排除
    assert fast["required"] is False
    assert _find(params, "context") is None


def test_required_param_without_default():
    src = """
class TrendBot:
    def __init__(self, symbol: str):
        self.symbol = symbol
"""
    res = parse_strategy_parameters(src)
    assert res["status"] == "success"
    params = res["data"][0]["parameters"]
    sym = _find(params, "symbol")
    assert sym is not None
    assert sym["type"] == "str"
    assert sym["required"] is True


def test_google_style_docstring_description():
    src = '''
class MeanReversionBot:
    """均值回归

    fast_ma (int): 快速均线周期
    threshold (float): 触发阈值
    """
    def __init__(self, fast_ma=5, threshold=0.02):
        pass
'''
    res = parse_strategy_parameters(src)
    assert res["status"] == "success"
    params = res["data"][0]["parameters"]
    fast = _find(params, "fast_ma")
    thr = _find(params, "threshold")
    assert fast["type"] == "int" and fast["default"] == 5
    assert thr["type"] == "float" and thr["default"] == 0.02
    assert fast["description"] == "快速均线周期"
    assert thr["description"] == "触发阈值"


def test_infer_type_from_default_when_no_annotation():
    src = """
class FlagsStrategy:
    def __init__(self, enabled=True, label="abc", ratio=1.5):
        pass
"""
    res = parse_strategy_parameters(src)
    assert res["status"] == "success"
    params = res["data"][0]["parameters"]
    assert _find(params, "enabled")["type"] == "bool"
    assert _find(params, "label")["type"] == "string"
    assert _find(params, "ratio")["type"] == "float"


def test_syntax_error_returns_error():
    res = parse_strategy_parameters("def foo(:\n")
    assert res["status"] == "error"
    assert "语法" in res["message"]


def test_indentation_error_returns_error():
    res = parse_strategy_parameters("if True:\n    x = 1\n  y = 2\n")
    assert res["status"] == "error"
    assert "缩进" in res["message"]


def test_no_strategy_class_returns_error():
    res = parse_strategy_parameters("def helper():\n    return 1\n")
    assert res["status"] == "error"
    assert "未检测" in res["message"]


def test_excludes_args_and_kwargs():
    src = """
class AnyStrategy:
    def __init__(self, symbol: str, *args, **kwargs):
        pass
"""
    res = parse_strategy_parameters(src)
    assert res["status"] == "success"
    params = res["data"][0]["parameters"]
    assert _find(params, "args") is None
    assert _find(params, "kwargs") is None
    assert _find(params, "symbol") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
