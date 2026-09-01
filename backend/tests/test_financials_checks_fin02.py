"""
FIN-02: 三表勾稽校验（checks）— 单元测试
========================================

验证:
  1. 资产负债恒等（权益含少数股东权益）
  2. 现金流勾稽（CFO + CFI + CFF ≈ 现金净变动）
  3. 毛利一致（收入 − 成本 ≈ 毛利）
  4. 缺项跳过、失败只标注不丢数（勾稽是门禁不是过滤器）

全部为纯函数测试：不打外网、不连 DB/Redis。
"""

import pytest

from backend.domain.financials import (
    TOLERANCE,
    check_balance_identity,
    check_cash_flow,
    check_gross_profit,
    failed_check_names,
    rel_error,
    run_integrity_checks,
)

# ─────────────────────────────────────────
#  7. 勾稽校验
# ─────────────────────────────────────────


def test_balance_identity_passes():
    result = check_balance_identity({"total_assets": 601.0, "total_liabilities": 341.0, "stockholders_equity": 260.0})
    assert result is not None and result.passed


def test_balance_identity_includes_minority_interest():
    """少数股东权益漏算会导致恒等式假失败，必须计入权益侧"""
    values = {
        "total_assets": 1000.0,
        "total_liabilities": 400.0,
        "stockholders_equity": 500.0,
        "minority_interest": 100.0,
    }
    assert check_balance_identity(values).passed is True
    assert check_balance_identity({**values, "minority_interest": 0.0}).passed is False


def test_balance_identity_fails_within_half_percent_tolerance():
    broken = {"total_assets": 1000.0, "total_liabilities": 400.0, "stockholders_equity": 500.0}
    result = check_balance_identity(broken)
    assert result.passed is False
    assert result.rel_error > TOLERANCE
    assert result.name == "balance_identity"


def test_cash_flow_reconciliation():
    values = {"cfo": 130.7, "cfi": -95.0, "cff": -30.0, "net_change_in_cash": 5.7}
    assert check_cash_flow(values).passed is True
    assert check_cash_flow({**values, "net_change_in_cash": 20.0}).passed is False


def test_gross_profit_consistency():
    values = {"revenue": 100.0, "cost_of_revenue": 60.0, "gross_profit": 40.0}
    assert check_gross_profit(values).passed is True
    assert check_gross_profit({**values, "gross_profit": 35.0}).passed is False


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"total_assets": 100.0},
        {"cfo": 1.0, "cfi": 2.0},
        {"revenue": 10.0, "cost_of_revenue": 4.0},
    ],
)
def test_missing_inputs_are_skipped(values):
    assert check_balance_identity(values) is None
    assert check_cash_flow(values) is None
    assert check_gross_profit(values) is None


def test_run_integrity_checks_reports_pass_fail_skip():
    report = run_integrity_checks(
        {
            "total_assets": 601.0,
            "total_liabilities": 341.0,
            "stockholders_equity": 260.0,
            "cfo": 130.7,
            "cfi": -95.0,
            "cff": -30.0,
            "net_change_in_cash": 5.7,
            "revenue": 100.0,
            "cost_of_revenue": 60.0,
            "gross_profit": 40.0,
        }
    )
    assert report.passed == ("balance_identity", "cash_flow_reconciliation", "gross_profit")
    assert report.failed == ()
    assert report.skipped == ()
    assert len(report.results) == 3
    assert report.as_dict()["failed"] == []


def test_failed_checks_are_reported_not_dropped():
    values = {
        "total_assets": 1000.0,
        "total_liabilities": 400.0,
        "stockholders_equity": 500.0,
        "cfo": 10.0,
        "cfi": 20.0,
        "cff": 30.0,
        "net_change_in_cash": 100.0,
    }
    assert failed_check_names(values) == ["balance_identity", "cash_flow_reconciliation"]
    report = run_integrity_checks(values)
    assert report.skipped == ("gross_profit",)
    assert [r.name for r in report.results if not r.passed] == ["balance_identity", "cash_flow_reconciliation"]


def test_rel_error_handles_zero_denominator():
    assert rel_error(0.0, 0.0) == 0.0
    assert rel_error(0.5, 0.0) == 0.5  # 退化为绝对误差
    assert rel_error(101.0, 100.0) == pytest.approx(1 / 101)  # 分母取两侧较大值
