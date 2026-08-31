"""
FIN-02: 端到端链路（companyfacts → 归一 → 单季拆分 → 勾稽）
============================================================

三个模块各自有单测（`test_financials_{mapper,periods,checks}_fin02.py`），
本文件锁的是**串起来**的行为：SEC 一手响应进，可落库的事实 + 勾稽结论出。
"""

from datetime import date

from backend.domain.financials import (
    ConceptMapper,
    classify_period,
    from_companyfacts,
    run_integrity_checks,
    split_ytd,
)

# 苹果 9 月财年（FY2025 = 2024-09-29 ~ 2025-09-27）：
# 10-Q 报的是**累计**口径（Q1 / H1 / 9M），年报才是 FY；资产与负债是时点值。
COMPANYFACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "start": "2024-09-29",
                            "end": "2024-12-28",
                            "val": 124300000000,
                            "accn": "a1",
                            "filed": "2025-01-30",
                            "form": "10-Q",
                        },
                        {
                            "start": "2024-09-29",
                            "end": "2025-03-29",
                            "val": 250000000000,
                            "accn": "a2",
                            "filed": "2025-05-01",
                            "form": "10-Q",
                        },
                        {
                            "start": "2024-09-29",
                            "end": "2025-06-28",
                            "val": 360000000000,
                            "accn": "a3",
                            "filed": "2025-07-31",
                            "form": "10-Q",
                        },
                        {
                            "start": "2024-09-29",
                            "end": "2025-09-27",
                            "val": 416161000000,
                            "accn": "a4",
                            "filed": "2025-10-31",
                            "form": "10-K",
                        },
                    ]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        {"end": "2025-09-27", "val": 359000000000, "accn": "a4", "filed": "2025-10-31", "form": "10-K"}
                    ]
                }
            },
            "Liabilities": {
                "units": {
                    "USD": [
                        {"end": "2025-09-27", "val": 285000000000, "accn": "a4", "filed": "2025-10-31", "form": "10-K"}
                    ]
                }
            },
            "StockholdersEquity": {
                "units": {
                    "USD": [
                        {"end": "2025-09-27", "val": 74000000000, "accn": "a4", "filed": "2025-10-31", "form": "10-K"}
                    ]
                }
            },
        }
    },
}


def test_end_to_end_from_companyfacts_to_integrity():
    mapper = ConceptMapper(source="sec")
    facts = mapper.normalize(from_companyfacts(COMPANYFACTS), entity_id="US:CIK0000320193")

    assert {"revenue", "total_assets", "total_liabilities", "stockholders_equity"} <= {f.concept for f in facts}
    # 四个期间全部保留：禁止只按 fy 去重（比较期与本期共用 fy 标签）
    assert [f.period_end for f in facts if f.concept == "revenue"] == [
        date(2024, 12, 28),
        date(2025, 3, 29),
        date(2025, 6, 28),
        date(2025, 9, 27),
    ]
    # 财年错位：2025-09-27 属 FY2025（苹果 9 月财年）
    fy = next(f for f in facts if f.concept == "revenue" and f.period_end == date(2025, 9, 27))
    assert classify_period(fy.period_start, fy.period_end, 9).label == "FY2025"

    values = {f.concept: f.value for f in facts if f.period_end == date(2025, 9, 27)}
    report = run_integrity_checks(values)
    assert report.failed == ()  # 359 ≈ 285 + 74
    assert report.passed == ("balance_identity",)


def test_end_to_end_ytd_split_derives_q2_q3_q4():
    mapper = ConceptMapper(source="sec")
    facts = mapper.normalize(from_companyfacts(COMPANYFACTS), entity_id="US:CIK0000320193")
    out = split_ytd(facts, fiscal_year_end_month=9)

    derived = [f for f in out if f.derived and f.concept == "revenue"]
    by_start = {f.period_start: f.value for f in derived}
    # Q1 + H1 + 9M + FY → Q2 = H1 − Q1，Q3 = 9M − H1，Q4 = FY − 9M（Q4 永远是推导值）
    assert by_start == {
        date(2024, 12, 29): 250000000000 - 124300000000,
        date(2025, 3, 30): 360000000000 - 250000000000,
        date(2025, 6, 29): 416161000000 - 360000000000,
    }
    assert all(f.derived for f in derived)
