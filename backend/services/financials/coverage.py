"""
FIN-09 · XBRL 覆盖率审计（docs/28 §九验收：缺失期显式列出，禁止补零）
====================================================================

对单个实体的 financial_facts 做核心科目 × 最近 N 个财年的覆盖盘点：
  - 目标期 = 最近 `years` 个自然年的 **FY（年度）期**；
  - 缺失期间显式列出（`missing`），绝不拿 0 或估算值填充；
  - `coverage_pct` 可手算复现（covered / expected）。

注意：这是**审计工具**不是数据——上市不足 `years` 年的公司缺失属正常披露边界，
报告里如实列出即可，调用方自行解读。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

# 验收关注的核心科目（三表各取代表，与 statement-grid 主行对齐）
CORE_CONCEPTS: tuple[tuple[str, str], ...] = (
    ("revenue", "income"),
    ("net_income", "income"),
    ("total_assets", "balance"),
    ("total_equity", "balance"),
    ("cfo", "cash"),
)


def audit_coverage(
    facts: Iterable[Mapping[str, Any]],
    *,
    today: date | None = None,
    years: int = 10,
) -> dict[str, Any]:
    """facts（含 fiscal_year / fiscal_period / concept / value_latest）→ 覆盖报告。

    facts 可以是 ORM 对象或 dict，统一 getattr 取值。
    """
    today = today or date.today()
    target_years = list(range(today.year - years + 1, today.year + 1))

    # concept → {fiscal_year: 有值}（FY 期、任一口径有值即算覆盖）
    covered: dict[str, set[int]] = {concept: set() for concept, _ in CORE_CONCEPTS}
    for f in facts:
        concept = getattr(f, "concept", None)
        if concept not in covered:
            continue
        if getattr(f, "fiscal_period", None) != "FY":
            continue
        if getattr(f, "value_latest", None) is None and getattr(f, "value_as_reported", None) is None:
            continue
        fy = getattr(f, "fiscal_year", None)
        if isinstance(fy, int):
            covered[concept].add(fy)

    per_concept: list[dict[str, Any]] = []
    total_expected = 0
    total_covered = 0
    for concept, statement in CORE_CONCEPTS:
        have = covered[concept] & set(target_years)
        missing = [y for y in target_years if y not in have]
        expected = len(target_years)
        total_expected += expected
        total_covered += len(have)
        per_concept.append(
            {
                "concept": concept,
                "statement": statement,
                "covered_years": sorted(have),
                "missing_years": missing,
                "coverage_pct": round(len(have) / expected, 4) if expected else 0.0,
            }
        )

    return {
        "window": {"start_year": target_years[0], "end_year": target_years[-1], "years": years},
        "concepts": per_concept,
        "missing": [{"concept": c["concept"], "years": c["missing_years"]} for c in per_concept if c["missing_years"]],
        "coverage_pct": round(total_covered / total_expected, 4) if total_expected else 0.0,
    }
