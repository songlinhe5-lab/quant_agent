"""
FIN-02: 期间推导（periods）— 单元测试
======================================

验证:
  1. 跨度判定（91 / 182 / 273 / 365 天分档）
  2. 非 12 月财年（苹果 9 月等错位年度）
  3. YTD 拆分（Q2 = H1 − Q1，Q3 = 9M − H1）
  4. Q4 推导（FY − 9M；无 9M 只给 H2，禁把 H2 当 Q4）

全部为纯函数测试：不打外网、不连 DB/Redis。
"""

from datetime import date

import pytest

from backend.domain.financials import (
    CUMULATIVE_PERIODS,
    NormalizedFact,
    PeriodError,
    classify_period,
    derive_quarters,
    fiscal_year_of,
    period_label,
    split_ytd,
)

# ─────────────────────────────────────────
#  6. 期间推导
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2025, 1, 1), date(2025, 3, 31), "Q1"),
        (date(2025, 4, 1), date(2025, 6, 30), "Q2"),
        (date(2025, 1, 1), date(2025, 6, 30), "H1"),
        (date(2025, 1, 1), date(2025, 9, 30), "9M"),
        (date(2025, 1, 1), date(2025, 12, 31), "FY"),
    ],
)
def test_classify_period_bands(start, end, expected):
    period = classify_period(start, end, 12)
    assert period.fiscal_period == expected
    assert period.fiscal_year == 2025
    assert period.is_instant is False


def test_classify_instant_period():
    period = classify_period(None, date(2025, 9, 30), 12)
    assert period.is_instant is True
    assert period.fiscal_period == "Q3"
    assert period.days == 0


def test_fiscal_year_with_non_december_year_end():
    # 苹果 9 月财年：2025-09-27 属 FY2025，2025-12-27 已属 FY2026
    assert fiscal_year_of(date(2025, 9, 27), 9) == 2025
    assert fiscal_year_of(date(2025, 12, 27), 9) == 2026
    assert classify_period(date(2024, 9, 29), date(2025, 9, 27), 9).label == "FY2025"
    assert classify_period(date(2025, 9, 28), date(2025, 12, 27), 9).label == "FY2026 Q1"


def test_fiscal_year_end_month_validation():
    with pytest.raises(PeriodError):
        fiscal_year_of(date(2025, 12, 31), 13)


def test_period_requires_end():
    with pytest.raises(PeriodError):
        classify_period(None, None, 12)


def test_derive_quarters_from_cumulative():
    result = derive_quarters(
        {
            "Q1": (date(2025, 1, 1), date(2025, 3, 31), 30.0),
            "H1": (date(2025, 1, 1), date(2025, 6, 30), 70.0),
            "9M": (date(2025, 1, 1), date(2025, 9, 30), 100.0),
            "FY": (date(2025, 1, 1), date(2025, 12, 31), 150.0),
        }
    )
    assert result["Q1"].value == 30.0 and result["Q1"].derived is False
    assert result["Q2"].value == 40.0 and result["Q2"].derived is True
    assert result["Q3"].value == 30.0 and result["Q3"].derived is True
    assert result["Q4"].value == 50.0 and result["Q4"].derived is True
    assert result["Q4"].start == date(2025, 10, 1) and result["Q4"].end == date(2025, 12, 31)


def test_derive_quarters_falls_back_to_h2_without_9m():
    """没有 9M 时只能给 H2，禁止把 H2 当 Q4"""
    result = derive_quarters(
        {
            "H1": (date(2025, 1, 1), date(2025, 6, 30), 70.0),
            "FY": (date(2025, 1, 1), date(2025, 12, 31), 150.0),
        }
    )
    assert "Q4" not in result
    assert "Q3" not in result
    assert result["H2"].value == 80.0


def test_derive_quarters_without_fy_gives_no_q4():
    result = derive_quarters({"Q1": (date(2025, 1, 1), date(2025, 3, 31), 30.0)})
    assert set(result) == {"Q1"}


def test_split_ytd_marks_derived_quarters():
    def fact(start, end, value):
        return NormalizedFact(
            entity_id="US:TEST",
            concept="revenue",
            statement="income",
            value=value,
            unit="USD",
            period_start=start,
            period_end=end,
            filed_at=date(2026, 2, 1),
            source="sec",
            source_tag="Revenues",
            taxonomy="us-gaap",
        )

    facts = [
        fact(date(2025, 1, 1), date(2025, 3, 31), 30.0),
        fact(date(2025, 1, 1), date(2025, 6, 30), 70.0),
        fact(date(2025, 1, 1), date(2025, 9, 30), 100.0),
        fact(date(2025, 1, 1), date(2025, 12, 31), 150.0),
    ]
    out = split_ytd(facts)
    derived = [f for f in out if f.derived]
    assert len(derived) == 3
    assert {f.value for f in derived} == {40.0, 30.0, 50.0}
    q4 = [f for f in derived if f.period_start == date(2025, 10, 1)][0]
    assert q4.value == 50.0 and q4.period_end == date(2025, 12, 31)
    assert split_ytd(facts, include_source=False) == derived


def test_split_ytd_skips_instant_facts():
    instant = NormalizedFact(
        entity_id="US:TEST",
        concept="total_assets",
        statement="balance",
        value=100.0,
        unit="USD",
        period_start=None,
        period_end=date(2025, 12, 31),
        filed_at=date(2026, 2, 1),
        source="sec",
        source_tag="Assets",
        taxonomy="us-gaap",
    )
    assert split_ytd([instant]) == [instant]


def test_period_equality_and_repr():
    a = classify_period(date(2025, 1, 1), date(2025, 12, 31), 12)
    b = classify_period(date(2025, 1, 1), date(2025, 12, 31), 12)
    c = classify_period(None, date(2025, 12, 31), 12)
    assert a == b
    assert a != c
    assert a != "FY2025"
    assert len({a, b}) == 1
    assert "FY2025" in repr(a)


def test_period_label_and_cumulative_flags():
    assert period_label(2025, "FY") == "FY2025"
    assert period_label(2025, "Q1") == "FY2025 Q1"
    assert period_label(2025, "H1") == "FY2025 H1"
    assert classify_period(date(2025, 1, 1), date(2025, 6, 30), 12).cumulative is True
    assert classify_period(date(2025, 1, 1), date(2025, 3, 31), 12).cumulative is False
    assert "H1" in CUMULATIVE_PERIODS
