"""
FIN-02 · 三表勾稽校验（落库前门禁）
==================================

docs/28 §3.4：勾稽失败**只标注、不丢弃**——仍入库，由前端标红透出，禁止静默丢数。

| 校验 | 断言 |
|:---|:---|
| balance_identity | assets ≈ liabilities + equity（含少数股东权益） |
| cash_flow_reconciliation | cfo + cfi + cff ≈ 现金净变动 |
| gross_profit | revenue − cost_of_revenue ≈ gross_profit |

判定用相对误差，阈值 0.5%；分母为 0 时退化到绝对误差（|Δ| ≤ 1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

TOLERANCE = 0.005
_ABS_FLOOR = 1.0

BALANCE_IDENTITY = "balance_identity"
CASH_FLOW_RECONCILIATION = "cash_flow_reconciliation"
GROSS_PROFIT = "gross_profit"

CHECKS: tuple[str, ...] = (BALANCE_IDENTITY, CASH_FLOW_RECONCILIATION, GROSS_PROFIT)


def rel_error(actual: float, expected: float) -> float:
    """相对误差；分母过小则退化为绝对误差，避免除零噪声。"""
    scale = max(abs(actual), abs(expected), _ABS_FLOOR)
    return abs(actual - expected) / scale


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    expected: float
    actual: float
    rel_error: float
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "rel_error": round(self.rel_error, 6),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IntegrityReport:
    failed: tuple[str, ...]
    passed: tuple[str, ...]
    skipped: tuple[str, ...]
    results: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "failed": list(self.failed),
            "passed": list(self.passed),
            "skipped": list(self.skipped),
            "results": [r.to_dict() for r in self.results],
        }


def _check(name: str, actual: float | None, expected: float | None, tol: float, expr: str) -> CheckResult | None:
    if actual is None or expected is None:
        return None
    err = rel_error(actual, expected)
    passed = err <= tol
    detail = f"{expr}: actual={actual:,.2f} expected={expected:,.2f} rel_err={err:.4%}"
    return CheckResult(name, passed, expected, actual, err, detail)


def check_balance_identity(values: Mapping[str, float], tol: float = TOLERANCE) -> CheckResult | None:
    """资产 = 负债 + 权益（权益含少数股东权益；缺 equity 则不校验）"""
    assets = values.get("total_assets")
    liabilities = values.get("total_liabilities")
    equity = values.get("stockholders_equity")
    if assets is None or liabilities is None or equity is None:
        return None
    equity_total = equity + (values.get("minority_interest") or 0.0)
    return _check(
        BALANCE_IDENTITY,
        assets,
        liabilities + equity_total,
        tol,
        "assets vs liabilities + equity",
    )


def check_cash_flow(values: Mapping[str, float], tol: float = TOLERANCE) -> CheckResult | None:
    """CFO + CFI + CFF ≈ 现金净变动"""
    cfo, cfi, cff = values.get("cfo"), values.get("cfi"), values.get("cff")
    net = values.get("net_change_in_cash")
    if cfo is None or cfi is None or cff is None or net is None:
        return None
    return _check(
        CASH_FLOW_RECONCILIATION,
        cfo + cfi + cff,
        net,
        tol,
        "cfo + cfi + cff vs net_change_in_cash",
    )


def check_gross_profit(values: Mapping[str, float], tol: float = TOLERANCE) -> CheckResult | None:
    """收入 − 成本 ≈ 毛利（三者齐备才校验）"""
    revenue, cogs, gross = values.get("revenue"), values.get("cost_of_revenue"), values.get("gross_profit")
    if revenue is None or cogs is None or gross is None:
        return None
    return _check(GROSS_PROFIT, revenue - cogs, gross, tol, "revenue - cost_of_revenue vs gross_profit")


def run_integrity_checks(values: Mapping[str, float], tol: float = TOLERANCE) -> IntegrityReport:
    """跑全部勾稽；缺项进 skipped，失败进 failed（**不删数据**）。"""
    results: list[CheckResult] = []
    skipped: list[str] = []
    for name, fn in (
        (BALANCE_IDENTITY, check_balance_identity),
        (CASH_FLOW_RECONCILIATION, check_cash_flow),
        (GROSS_PROFIT, check_gross_profit),
    ):
        result = fn(values, tol)
        if result is None:
            skipped.append(name)
        else:
            results.append(result)

    return IntegrityReport(
        failed=tuple(r.name for r in results if not r.passed),
        passed=tuple(r.name for r in results if r.passed),
        skipped=tuple(skipped),
        results=tuple(results),
    )


def failed_check_names(values: Mapping[str, float], tol: float = TOLERANCE) -> list[str]:
    """落库用的 `check_failed` 字段取值（docs/28 §4 FinancialFact）。"""
    return list(run_integrity_checks(values, tol).failed)
