"""
FIN-02: 概念归一化（mapper）— 单元测试
======================================

验证:
  1. 声明式概念映射（版本 / 结构校验 / 标签冲突优先级）
  2. 21 家 golden case（改映射即失败，跨 us-gaap / ifrs / tushare / futu）
  3. 归一化细节（时点/区间/脏值/符号，落空不猜值）
  4. 三源适配（companyfacts 展平 / 行式 from_rows）
  5. 双时间轴取值（as_reported / latest / restated）

全部为纯函数测试：不打外网、不连 DB/Redis。
"""

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from backend.domain.financials import (
    ConceptMap,
    ConceptMapError,
    ConceptMapper,
    RawFact,
    from_companyfacts,
    from_rows,
    load_concept_map,
)

GOLDEN_PATH = Path(__file__).parent / "data" / "financials_golden_fin02.json"


def _d(value):
    return date.fromisoformat(value) if value else None


def _load_golden():
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


GOLDEN_CASES = _load_golden()


def _raw_facts(case):
    return [
        RawFact(
            taxonomy=case["taxonomy"],
            tag=item["tag"],
            value=item["value"],
            unit=item.get("unit", ""),
            start=_d(item.get("start")),
            end=_d(item.get("end")),
            filed=_d(item.get("filed")),
            accn=item.get("accn"),
            form=item.get("form"),
        )
        for item in case["raw"]
    ]


# ─────────────────────────────────────────
#  1. 概念映射表
# ─────────────────────────────────────────


def test_concept_map_loads_with_version():
    cmap = load_concept_map()
    assert cmap.version
    assert len(cmap.concepts) >= 30
    assert set(cmap.concepts_of("income")) & {"revenue", "net_income"}
    assert set(cmap.concepts_of("balance")) & {"total_assets", "stockholders_equity"}
    assert set(cmap.concepts_of("cash")) & {"cfo", "cfi", "cff"}


def test_concept_map_has_no_tag_collisions():
    """同 taxonomy 内一个标签只应命中一个科目，冲突会让取值不可预测"""
    assert load_concept_map().collisions == ()


def test_concept_map_rejects_invalid_statement(tmp_path):
    bad = tmp_path / "bad_map.json"
    bad.write_text(
        json.dumps(
            {
                "version": "test",
                "concepts": {"revenue": {"label": "营收", "statement": "unknown", "us-gaap": ["Revenues"]}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConceptMapError):
        ConceptMap.load(bad)


def test_concept_map_rejects_invalid_period_type(tmp_path):
    bad = tmp_path / "bad_period.json"
    bad.write_text(
        json.dumps(
            {
                "version": "test",
                "concepts": {
                    "revenue": {
                        "label": "营收",
                        "statement": "income",
                        "period_type": "weekly",
                        "us-gaap": ["Revenues"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConceptMapError):
        ConceptMap.load(bad)


def test_tag_collision_prefers_higher_priority_chain(tmp_path):
    """同标签落在两个科目：链内 rank 小的取胜，且必须被记录为冲突"""
    path = tmp_path / "collide.json"
    path.write_text(
        json.dumps(
            {
                "version": "collide",
                "concepts": {
                    "revenue": {
                        "label": "营收",
                        "statement": "income",
                        "period_type": "duration",
                        "us-gaap": ["AmbiguousTag", "Revenues"],
                    },
                    "net_income": {
                        "label": "净利",
                        "statement": "income",
                        "period_type": "duration",
                        "us-gaap": ["NetIncomeLoss", "AmbiguousTag"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    cmap = load_concept_map(path)
    assert cmap.resolve("AmbiguousTag", "us-gaap") == "revenue"  # rank 0 优先于 rank 1
    assert cmap.collisions == (("us-gaap", "AmbiguousTag", ("net_income", "revenue")),)


def test_concept_map_rejects_missing_version_and_label(tmp_path):
    no_version = tmp_path / "no_version.json"
    no_version.write_text(json.dumps({"concepts": {}}), encoding="utf-8")
    with pytest.raises(ConceptMapError):
        ConceptMap.load(no_version)

    no_label = tmp_path / "no_label.json"
    no_label.write_text(
        json.dumps({"version": "test", "concepts": {"revenue": {"statement": "income", "us-gaap": ["Revenues"]}}}),
        encoding="utf-8",
    )
    with pytest.raises(ConceptMapError):
        ConceptMap.load(no_label)


# ─────────────────────────────────────────
#  2. 20 家 golden case（改映射即失败）
# ─────────────────────────────────────────


def test_golden_case_count():
    assert len(GOLDEN_CASES) >= 20


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["entity_id"])
def test_golden_cases_map_to_expected_concepts(case):
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(_raw_facts(case), entity_id=case["entity_id"])

    got = {f.concept: f.value for f in facts}
    assert got == pytest.approx(case["expected"])
    # 落空标签只计数、不猜值
    assert sum(mapper.stats["unmapped"].values()) == case["unmapped"]
    assert mapper.stats["skipped"] == {}
    # 每行都要带上原始标签与来源，便于回溯映射错误
    assert all(f.source_tag and f.entity_id == case["entity_id"] for f in facts)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["entity_id"])
def test_golden_cases_collapse_to_single_version(case):
    mapper = ConceptMapper(source="test")
    versioned = mapper.map_facts(_raw_facts(case), entity_id=case["entity_id"])
    assert len(versioned) == len(case["expected"])
    assert all(v.versions == 1 and not v.restated for v in versioned)


def test_unmapped_tag_is_counted_not_guessed():
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(
        [RawFact(taxonomy="us-gaap", tag="SomeFutureTag", value=1.0, end=date(2025, 12, 31))],
        entity_id="US:TEST",
    )
    assert facts == []
    assert mapper.stats["unmapped"] == {"us-gaap:SomeFutureTag": 1}


# ─────────────────────────────────────────
#  3. 归一化细节（时点/区间/脏值/符号）
# ─────────────────────────────────────────


def test_instant_concept_drops_period_start():
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(
        [
            RawFact(
                taxonomy="us-gaap",
                tag="Assets",
                value=100.0,
                unit="USD",
                start=date(2025, 1, 1),
                end=date(2025, 12, 31),
                filed=date(2026, 2, 1),
            )
        ],
        entity_id="US:TEST",
    )
    assert len(facts) == 1
    assert facts[0].period_start is None
    assert facts[0].period_end == date(2025, 12, 31)
    assert facts[0].statement == "balance"


def test_duration_without_start_is_skipped():
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(
        [RawFact(taxonomy="us-gaap", tag="Revenues", value=10.0, end=date(2025, 12, 31))],
        entity_id="US:TEST",
    )
    assert facts == []
    assert mapper.stats["skipped"] == {"duration_without_start": 1}


@pytest.mark.parametrize("bad_value", ["N/A", None, "", float("nan"), float("inf")])
def test_bad_value_is_skipped(bad_value):
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(
        [
            RawFact(
                taxonomy="us-gaap",
                tag="Revenues",
                value=bad_value,
                start=date(2025, 1, 1),
                end=date(2025, 12, 31),
            )
        ],
        entity_id="US:TEST",
    )
    assert facts == []
    assert mapper.stats["skipped"] == {"bad_value": 1}


def test_missing_period_end_is_skipped():
    mapper = ConceptMapper(source="test")
    facts = mapper.normalize(
        [RawFact(taxonomy="us-gaap", tag="Assets", value=10.0)],
        entity_id="US:TEST",
    )
    assert facts == []
    assert mapper.stats["skipped"] == {"no_period_end": 1}


def test_sign_is_applied_from_config(tmp_path):
    path = tmp_path / "sign_map.json"
    path.write_text(
        json.dumps(
            {
                "version": "sign-test",
                "concepts": {
                    "capex": {
                        "label": "资本开支",
                        "statement": "cash",
                        "period_type": "duration",
                        "sign": -1,
                        "us-gaap": ["PaymentsToAcquirePropertyPlantAndEquipment"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    mapper = ConceptMapper(load_concept_map(path))
    facts = mapper.normalize(
        [
            RawFact(
                taxonomy="us-gaap",
                tag="PaymentsToAcquirePropertyPlantAndEquipment",
                value=-500.0,
                start=date(2025, 1, 1),
                end=date(2025, 12, 31),
            )
        ],
        entity_id="US:TEST",
    )
    assert facts[0].value == 500.0  # 源以负数表示支出 → 乘 -1 归一


# ─────────────────────────────────────────
#  4. 三源适配
# ─────────────────────────────────────────


def test_from_companyfacts_flattens_units():
    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "val": 100,
                                "filed": "2026-01-31",
                                "accn": "0001-26-000001",
                                "form": "10-K",
                            }
                        ]
                    }
                }
            }
        },
    }
    raw = from_companyfacts(payload)
    assert len(raw) == 1
    assert raw[0].taxonomy == "us-gaap"
    assert raw[0].tag == "Revenues"
    assert raw[0].unit == "USD"
    assert raw[0].start == date(2025, 1, 1)
    assert raw[0].filed == date(2026, 1, 31)


def test_from_rows_adapter():
    rows = [
        {
            "display_name": "营业收入",
            "data": 712000000000,
            "currency": "CNY",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "filed": "2026-03-22",
        }
    ]
    raw = from_rows(
        rows,
        taxonomy="futu",
        tag_field="display_name",
        value_field="data",
        unit_field="currency",
        start_field="start",
        end_field="end",
        filed_field="filed",
    )
    assert raw[0].tag == "营业收入"
    assert raw[0].unit == "CNY"
    facts = ConceptMapper().normalize(raw, entity_id="HK:00700")
    assert facts[0].concept == "revenue"


# ─────────────────────────────────────────
#  5. 双时间轴取值
# ─────────────────────────────────────────


def _restatement_pair():
    return [
        RawFact(
            taxonomy="us-gaap",
            tag="Revenues",
            value=100.0,
            unit="USD",
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            filed=date(2026, 2, 1),
            accn="accn-1",
        ),
        RawFact(
            taxonomy="us-gaap",
            tag="Revenues",
            value=118.0,  # 一年后重述
            unit="USD",
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            filed=date(2027, 2, 1),
            accn="accn-2",
        ),
    ]


def test_collapse_versions_picks_as_reported_and_latest():
    versioned = ConceptMapper().map_facts(_restatement_pair(), entity_id="US:TEST")
    assert len(versioned) == 1
    v = versioned[0]
    assert v.value_as_reported == 100.0
    assert v.value_latest == 118.0
    assert v.restated is True
    assert v.versions == 2
    assert v.filed_as_reported == date(2026, 2, 1)
    assert v.filed_latest == date(2027, 2, 1)
    assert v.to_dict()["restated"] is True


def test_collapse_versions_no_restate_when_values_equal():
    pair = _restatement_pair()
    pair[1] = replace(pair[1], value=100.0)
    versioned = ConceptMapper().map_facts(pair, entity_id="US:TEST")
    assert versioned[0].restated is False
    assert versioned[0].versions == 2


def test_collapse_versions_keeps_distinct_periods_separate():
    """禁止只按 fy 去重：比较期与本期共用 fy 标签，合并会静默丢数"""
    facts = [
        RawFact("us-gaap", "Revenues", 40.0, "USD", date(2025, 1, 1), date(2025, 3, 31), date(2025, 5, 1)),
        RawFact("us-gaap", "Revenues", 200.0, "USD", date(2025, 1, 1), date(2025, 12, 31), date(2026, 2, 1)),
    ]
    versioned = ConceptMapper().map_facts(facts, entity_id="US:TEST")
    assert len(versioned) == 2
    assert {v.value_latest for v in versioned} == {40.0, 200.0}


def test_from_companyfacts_filters_by_taxonomy():
    payload = {
        "facts": {
            "us-gaap": {"Revenues": {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 1}]}}},
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 2}]}}},
        }
    }
    assert [r.taxonomy for r in from_companyfacts(payload)] == ["us-gaap", "dei"]
    assert [r.taxonomy for r in from_companyfacts(payload, taxonomy="us-gaap")] == ["us-gaap"]


def test_date_parsing_accepts_multiple_formats():
    raw = from_rows(
        [
            {
                "tag": "Revenues",
                "value": 1.0,
                "start": datetime(2025, 1, 1, 9, 30),
                "end": "20251231",
                "filed": "not-a-date",
            }
        ],
        taxonomy="us-gaap",
        tag_field="tag",
        value_field="value",
        start_field="start",
        end_field="end",
        filed_field="filed",
    )
    assert raw[0].start == date(2025, 1, 1)
    assert raw[0].end == date(2025, 12, 31)
    assert raw[0].filed is None  # 无法解析的日期不猜，置空


def test_mapper_resolve_and_reset_stats():
    mapper = ConceptMapper()
    assert mapper.resolve("Revenues") == "revenue"
    assert mapper.resolve("Revenues", "ifrs-full") is None
    assert mapper.resolve("Unknown") is None
    assert mapper.stats["unmapped"] == {"ifrs-full:Revenues": 1, "us-gaap:Unknown": 1}
    mapper.reset_stats()
    assert mapper.stats == {"unmapped": {}, "skipped": {}}


def test_load_concept_map_is_cached_and_reloadable():
    first = load_concept_map()
    assert load_concept_map() is first
    assert load_concept_map(reload=True) is not first
