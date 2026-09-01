"""
FIN-04: 报表视图装配（views）— 单元测试
=======================================

验证 docs/28 §四 `StatementView` 的装配语义：
  1. 列 = 期间（财年老→新），行 = 标准科目，展示名一律取自 concept_map
  2. 缺失不补零：拿不到的格子是 None
  3. 同 (科目, 期间) 多版本冲突按 filed_latest 仲裁，且**不得**误伤同列其他科目
  4. common-size / YoY / derived / restated / check_failed 逐格透出
  5. 口径与 PIT 日期必须让前端看得见（basis / as_of / source_mix / currency）

纯函数装配，不打 DB 也不打外网。
"""

from datetime import date

from backend.core.financials_models import FilingRecord, FinancialFact
from backend.services.financials import views


def _fact(
    concept: str,
    *,
    value: float,
    fy: int,
    fp: str = "FY",
    statement: str = "income",
    unit: str = "USD",
    source: str = "sec",
    as_reported: float | None = None,
    filed: date = date(2026, 2, 1),
    filed_last: date | None = None,
    derived: bool = False,
    check_failed: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> FinancialFact:
    """构造未落库的 ORM 对象：列默认值在 flush 才生效，故这里全量显式给。"""
    return FinancialFact(
        entity_id="US:CIK0000320193",
        concept=concept,
        statement=statement,
        period_start=start,
        period_start_key=start.isoformat() if start else "",
        period_end=end or date(fy, 12, 31),
        fiscal_year=fy,
        fiscal_period=fp,
        unit=unit,
        value_as_reported=as_reported if as_reported is not None else value,
        value_latest=value,
        restated=as_reported is not None and as_reported != value,
        derived=derived,
        filed_as_reported=filed,
        filed_latest=filed_last or filed,
        source=source,
        source_tag=concept,
        check_failed=check_failed,
    )


# ─────────────────────────────────────────
#  1. 骨架：行列顺序与展示名
# ─────────────────────────────────────────


def test_periods_ascending_and_rows_sorted_by_concept():
    view = views.build_statement_view(
        [
            _fact("net_income", value=20.0, fy=2025),
            _fact("revenue", value=100.0, fy=2024),
            _fact("revenue", value=125.0, fy=2025),
            _fact("gross_profit", value=45.0, fy=2025),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert view["periods"] == ["FY2024", "FY2025"]
    assert [r["concept"] for r in view["rows"]] == ["gross_profit", "net_income", "revenue"]
    # 展示名来自 concept_map（数据即配置，禁硬编码文案）
    assert [r["label"] for r in view["rows"]] == ["毛利润", "净利润", "营业收入"]
    revenue = next(r for r in view["rows"] if r["concept"] == "revenue")
    assert revenue["values"] == [100.0, 125.0]


def test_quarter_and_ytd_columns_sort_within_same_fiscal_year():
    view = views.build_statement_view(
        [
            _fact("revenue", value=40.0, fy=2025, fp="Q1", end=date(2025, 3, 31)),
            _fact("revenue", value=90.0, fy=2025, fp="H1", end=date(2025, 6, 30)),
            _fact("revenue", value=200.0, fy=2025, fp="FY", end=date(2025, 12, 31)),
            _fact("revenue", value=30.0, fy=2025, fp="Q2", end=date(2025, 6, 30)),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert view["periods"] == ["FY2025 Q1", "FY2025 Q2", "FY2025 H1", "FY2025"]


# ─────────────────────────────────────────
#  2. 缺失不补零
# ─────────────────────────────────────────


def test_missing_cell_is_none_never_zero():
    view = views.build_statement_view(
        [
            _fact("revenue", value=100.0, fy=2024),
            _fact("revenue", value=125.0, fy=2025),
            _fact("net_income", value=20.0, fy=2025),  # 2024 没给
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    row = next(r for r in view["rows"] if r["concept"] == "net_income")
    assert row["values"] == [None, 20.0]  # 空位是 None 而非 0.0


# ─────────────────────────────────────────
#  3. 版本仲裁
# ─────────────────────────────────────────


def test_conflict_same_concept_period_keeps_lately_filed_regardless_of_order():
    late_first = [
        _fact("revenue", value=118.0, fy=2025, filed=date(2026, 2, 1), filed_last=date(2027, 2, 1)),
        _fact("revenue", value=100.0, fy=2025, filed=date(2026, 2, 1)),
    ]
    early_first = list(reversed(late_first))
    for facts in (late_first, early_first):
        view = views.build_statement_view(facts, entity_id="US:CIK0000320193", statement="income")
        assert view["rows"][0]["values"] == [118.0]  # 保留最近一次披露


def test_same_column_different_concepts_are_not_swallowed_as_old_versions():
    """回归：仲裁键曾只按列，导致晚处理但 filed 更早的科目被整格丢掉。"""
    view = views.build_statement_view(
        [
            _fact("revenue", value=118.0, fy=2025, filed_last=date(2027, 2, 1)),  # 被重述过
            _fact("cost_of_revenue", value=70.0, fy=2025, filed=date(2026, 2, 1)),  # 从未重述
            _fact("net_income", value=25.0, fy=2025, filed=date(2026, 5, 1)),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert [r["concept"] for r in view["rows"]] == ["cost_of_revenue", "net_income", "revenue"]
    assert all(r["values"][0] is not None for r in view["rows"])


# ─────────────────────────────────────────
#  4. common-size / YoY
# ─────────────────────────────────────────


def test_common_size_uses_statement_base_concept():
    view = views.build_statement_view(
        [
            _fact("revenue", value=100.0, fy=2025),
            _fact("net_income", value=25.0, fy=2025),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert next(r for r in view["rows"] if r["concept"] == "net_income")["common_size"] == [25.0]
    assert next(r for r in view["rows"] if r["concept"] == "revenue")["common_size"] == [100.0]


def test_common_size_none_when_base_missing_or_zero():
    view = views.build_statement_view(
        [
            _fact("net_income", value=25.0, fy=2025),  # 没有 revenue 基线
            _fact("net_income", value=10.0, fy=2024),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert view["rows"][0]["common_size"] == [None, None]

    zero_base = views.build_statement_view(
        [
            _fact("revenue", value=0.0, fy=2025),
            _fact("net_income", value=25.0, fy=2025),
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert next(r for r in zero_base["rows"] if r["concept"] == "net_income")["common_size"] == [None]


def test_balance_common_size_baseline_is_total_assets():
    view = views.build_statement_view(
        [
            _fact("total_assets", value=500.0, fy=2025, statement="balance"),
            _fact("total_liabilities", value=300.0, fy=2025, statement="balance"),
        ],
        entity_id="US:CIK0000320193",
        statement="balance",
    )
    row = next(r for r in view["rows"] if r["concept"] == "total_liabilities")
    assert row["common_size"] == [60.0]


def test_yoy_only_compares_same_span():
    view = views.build_statement_view(
        [
            _fact("revenue", value=100.0, fy=2024),
            _fact("revenue", value=125.0, fy=2025),
            _fact("revenue", value=30.0, fy=2025, fp="Q1", end=date(2025, 3, 31)),  # 无 FY2024 Q1
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert view["periods"] == ["FY2024", "FY2025 Q1", "FY2025"]
    row = view["rows"][0]  # 只有 revenue 一个科目
    assert row["values"] == [100.0, 30.0, 125.0]
    assert row["yoy"] == [None, None, 0.25]  # 季度绝不跟年度比


def test_yoy_none_when_previous_missing_or_zero():
    view = views.build_statement_view(
        [
            _fact("revenue", value=125.0, fy=2025),  # FY2024 缺席
        ],
        entity_id="US:CIK0000320193",
        statement="income",
    )
    assert view["rows"][0]["yoy"] == [None]


# ─────────────────────────────────────────
#  5. 口径可见性 / PIT / 来源 / 币种
# ─────────────────────────────────────────


def test_basis_and_as_of_are_echoed_for_frontend():
    facts = [_fact("revenue", value=118.0, fy=2025, as_reported=100.0, filed_last=date(2027, 2, 1))]
    latest = views.build_statement_view(facts, entity_id="X", statement="income", basis="latest")
    reported = views.build_statement_view(facts, entity_id="X", statement="income", basis="as_reported")
    pit = views.build_statement_view(facts, entity_id="X", statement="income", as_of=date(2026, 6, 1))

    assert latest["basis"] == "latest" and latest["as_of"] is None
    assert latest["rows"][0]["values"] == [118.0]
    assert reported["rows"][0]["values"] == [100.0]
    # PIT：重述（2027-02-01）当时尚未发生，市场只知首次披露值
    assert pit["rows"][0]["values"] == [100.0]
    assert pit["as_of"] == "2026-06-01"


def test_flags_and_integrity_expose_derived_restated_check_failed():
    facts = [
        _fact("revenue", value=125.0, fy=2025, as_reported=100.0, filed_last=date(2027, 2, 1)),
        _fact("net_income", value=30.0, fy=2025, derived=True, check_failed=["gross_profit"]),
    ]
    view = views.build_statement_view(facts, entity_id="X", statement="income")
    ni = next(r for r in view["rows"] if r["concept"] == "net_income")
    assert ni["derived"] == [True] and ni["restated"] == [False] and ni["check_failed"] == [["gross_profit"]]
    rev = next(r for r in view["rows"] if r["concept"] == "revenue")
    assert rev["restated"] == [True]

    integrity = view["integrity"]
    assert integrity["failed_periods"] == ["FY2025"]
    assert integrity["failures"] == {"FY2025": ["gross_profit"]}
    assert integrity["total_facts"] == 2
    assert integrity["derived_facts"] == 1 and integrity["restated_facts"] == 1


def test_source_mix_counted_and_currency_mixed_is_blank():
    mixed = views.build_statement_view(
        [
            _fact("revenue", value=1.0, fy=2025, source="sec"),
            _fact("net_income", value=2.0, fy=2025, source="futu"),
            _fact("gross_profit", value=3.0, fy=2025, source="futu"),
        ],
        entity_id="X",
        statement="income",
    )
    assert mixed["source_mix"] == {"sec": 1, "futu": 2}
    assert mixed["currency"] == "USD"

    multi = views.build_statement_view(
        [
            _fact("revenue", value=1.0, fy=2025, unit="USD"),
            _fact("net_income", value=2.0, fy=2025, unit="HKD"),
        ],
        entity_id="X",
        statement="income",
    )
    assert multi["currency"] == ""  # 多币种并存：置空让前端标源，不挑一个当真值

    shares = views.build_statement_view(
        [_fact("revenue", value=1.0, fy=2025, unit="USD"), _fact("net_income", value=2.0, fy=2025, unit="shares")],
        entity_id="X",
        statement="income",
    )
    assert shares["currency"] == "USD"  # 份额不是币种，不参与币种判定


# ─────────────────────────────────────────
#  6. 科目明细 / 重述 diff / 申报时间轴
# ─────────────────────────────────────────


def test_fact_view_carries_full_provenance():
    items = views.build_fact_view([_fact("revenue", value=118.0, fy=2025, as_reported=100.0)])
    assert len(items) == 1
    assert items[0]["value_as_reported"] == 100.0 and items[0]["value_latest"] == 118.0
    assert items[0]["fiscal_period"] == "FY" and items[0]["source"] == "sec"


def test_restatement_view_delta_and_pct_with_zero_guard():
    facts = [
        _fact("revenue", value=118.0, fy=2025, as_reported=100.0),
        _fact("net_income", value=5.0, fy=2024, as_reported=0.0),  # 分母 0 → 相对差不猜
    ]
    rows = views.build_restatement_view(facts)
    rev = next(r for r in rows if r["concept"] == "revenue")
    assert rev["delta"] == 18.0 and round(rev["delta_pct"], 4) == 0.18 and rev["label"] == "营业收入"
    ni = next(r for r in rows if r["concept"] == "net_income")
    assert ni["delta"] == 5.0 and ni["delta_pct"] is None


def test_filing_view_shape():
    rows = views.build_filing_view(
        [
            FilingRecord(
                entity_id="US:CIK0000320193",
                form_type="10-K",
                fiscal_year=2025,
                filed_at=date(2025, 10, 31),
                accession_no="0000320193-25-000123",
                doc_url="https://www.sec.gov/Archives/edgar/data/320193/x/a.html",
                lang="en",
                rag_indexed=False,
            )
        ]
    )
    assert rows[0]["form_type"] == "10-K" and rows[0]["filed_at"] == "2025-10-31"
    assert rows[0]["rag_indexed"] is False
