"""
FIN-02 · 财报归一化领域层
=========================

纯函数、无 IO：概念映射（声明式）/ 期间推导 / 勾稽校验。
架构见 `docs/28 §三`，任务 `FIN-02`（`docs/TODO-engine.md`）。
"""

from backend.domain.financials.checks import (
    CHECKS,
    TOLERANCE,
    CheckResult,
    IntegrityReport,
    check_balance_identity,
    check_cash_flow,
    check_gross_profit,
    failed_check_names,
    rel_error,
    run_integrity_checks,
)
from backend.domain.financials.mapper import (
    ConceptDef,
    ConceptMap,
    ConceptMapError,
    ConceptMapper,
    NormalizedFact,
    RawFact,
    VersionedFact,
    from_companyfacts,
    from_rows,
    load_concept_map,
)
from backend.domain.financials.periods import (
    CUMULATIVE_PERIODS,
    DerivedValue,
    Period,
    PeriodError,
    classify_period,
    days_between,
    derive_quarters,
    fiscal_year_of,
    period_label,
    split_ytd,
)

__all__ = [
    # mapper
    "ConceptDef",
    "ConceptMap",
    "ConceptMapError",
    "ConceptMapper",
    "NormalizedFact",
    "RawFact",
    "VersionedFact",
    "from_companyfacts",
    "from_rows",
    "load_concept_map",
    # periods
    "CUMULATIVE_PERIODS",
    "DerivedValue",
    "Period",
    "PeriodError",
    "classify_period",
    "days_between",
    "derive_quarters",
    "fiscal_year_of",
    "period_label",
    "split_ytd",
    # checks
    "CHECKS",
    "TOLERANCE",
    "CheckResult",
    "IntegrityReport",
    "check_balance_identity",
    "check_cash_flow",
    "check_gross_profit",
    "failed_check_names",
    "rel_error",
    "run_integrity_checks",
]
