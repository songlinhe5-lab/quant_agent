"""
ALERT-COND-01: 自由表达式求值引擎的跨语言 golden 测试

以 frontend/src/features/quotes/custom-indicator/expr-golden.json 为唯一事实来源（ground truth，
由前端 TS 引擎回填 expected），断言后端 Python 端 (backend.services.alert.expr_evaluator) 在以下维度
与前端 1:1 一致：
  - ok（是否成功求值）
  - is_bool（结果是否为布尔序列）
  - values（逐元素数值，容差 1e-6）

此外验证 ExprEvaluator 类（被 AlertEngine 实际调用）的 feed / evaluate / evaluate_rule 链路。
"""

import sys
from pathlib import Path

import pytest

# 确保 backend 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.alert_models import AlertRule, AlertRuleType  # noqa: E402
from backend.services.alert.expr_evaluator import (  # noqa: E402
    ExprEvaluator,
    evaluate_expr,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "features"
    / "quotes"
    / "custom-indicator"
    / "expr-golden.json"
)

with open(GOLDEN_PATH, "r", encoding="utf-8") as _f:
    _golden = __import__("json").load(_f)

BARS = _golden["bars"]
CASES = _golden["cases"]


def _approx(a, b, tol=1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < tol


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_parity(case):
    """后端 Python 表达式引擎语义与前端 TS ground truth 完全一致"""
    r = evaluate_expr(case["expr"], BARS, case.get("params", {}))
    exp = case["expected"]

    assert r["ok"] == exp["ok"], f"[{case['name']}] ok 不一致: py={r['ok']} ts={exp['ok']} err={r.get('error')}"
    if not exp["ok"]:
        # 错误类 case 只比对 ok 标志即可
        return

    assert r["is_bool"] == exp["is_bool"], f"[{case['name']}] is_bool 不一致: py={r['is_bool']} ts={exp['is_bool']}"
    assert len(r["values"]) == len(exp["values"]), (
        f"[{case['name']}] 长度不一致: py={len(r['values'])} ts={len(exp['values'])}"
    )
    for i, (a, b) in enumerate(zip(r["values"], exp["values"])):
        assert _approx(a, b), f"[{case['name']}] 第 {i} 个元素不一致: py={a} ts={b}"


def _feed_all(ev: ExprEvaluator, ticker: str):
    for b in BARS:
        ev.feed(
            ticker,
            {
                "time": b.get("time"),
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b.get("volume", 0.0),
            },
        )


def test_evaluator_class_matches_module_fn():
    """ExprEvaluator.evaluate 与 evaluate_expr 模块函数输出一致"""
    ev = ExprEvaluator()
    _feed_all(ev, "AAPL")
    for c in CASES:
        r1 = evaluate_expr(c["expr"], BARS, c.get("params", {}))
        ok, is_bool, values = ev.evaluate("AAPL", c["expr"], c.get("params", {}))
        assert ok == r1["ok"]
        if ok:
            assert is_bool == r1["is_bool"]
            assert len(values) == len(r1["values"])
            for a, b in zip(values, r1["values"]):
                assert _approx(a, b)


def test_evaluate_rule_triggers_on_last_true():
    """evaluate_rule: 末根布尔为真时触发，trigger_value 为末值"""
    ev = ExprEvaluator()
    _feed_all(ev, "AAPL")
    rule = AlertRule(
        rule_id="r-expr-1",
        name="收盘价站上100",
        ticker="AAPL",
        rule_type=AlertRuleType.EXPR,
        threshold=0.0,
        metadata={"expr": "CLOSE > 100", "expr_params": {}},
    )
    triggered, tv = ev.evaluate_rule(rule)
    assert triggered is True
    assert tv is not None
    assert abs(tv - BARS[-1]["close"]) < 1e-6


def test_evaluate_rule_no_trigger_when_last_false():
    """evaluate_rule: 末根布尔为假时不触发"""
    ev = ExprEvaluator()
    _feed_all(ev, "AAPL")
    # 构造一个末根为假的布尔表达式：收盘价 <= 100
    rule = AlertRule(
        rule_id="r-expr-2",
        name="收盘价不高于100",
        ticker="AAPL",
        rule_type=AlertRuleType.EXPR,
        threshold=0.0,
        metadata={"expr": "CLOSE <= 100", "expr_params": {}},
    )
    triggered, tv = ev.evaluate_rule(rule)
    assert triggered is False
    assert tv is None


def test_evaluate_rule_rejects_non_bool_result():
    """evaluate_rule: 数值型表达式（非布尔）不触发"""
    ev = ExprEvaluator()
    _feed_all(ev, "AAPL")
    rule = AlertRule(
        rule_id="r-expr-3",
        name="RSI数值",
        ticker="AAPL",
        rule_type=AlertRuleType.EXPR,
        threshold=0.0,
        metadata={"expr": "RSI(14)", "expr_params": {}},
    )
    triggered, tv = ev.evaluate_rule(rule)
    assert triggered is False
    assert tv is None
