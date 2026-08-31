"""
FIN-02 · 财报概念归一化引擎
===========================

把各源（SEC XBRL / 富途 / tushare）的原始标签映射为**标准科目**，纯函数、无 IO。

设计约束（docs/28 §3.1）：
- 映射关系**数据即配置**，写在 `concept_map.json`，禁止在服务代码里补 if-else；
- 标准科目 → 候选标签**有序链**，先命中先用；全部落空则该科目为 None（不猜、不插值）；
- 映射表带版本号，改动须走 PR + golden case 单测。

双时间轴取值（docs/28 §3.2）在 `collapse_versions` 实现：
唯一键 `(entity_id, concept, period_start, period_end, unit)`，
`value_as_reported` = `filed_at` 最早值，`value_latest` = 最新值，两者不等即 `restated`。
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

_MAP_PATH = Path(__file__).with_name("concept_map.json")

STATEMENTS: tuple[str, ...] = ("income", "balance", "cash")
PERIOD_TYPES: tuple[str, ...] = ("duration", "instant")


class ConceptMapError(RuntimeError):
    """概念映射表结构非法（配置错误应当即失败，不允许静默降级）"""


def _as_date(value: Any) -> date | None:
    """把 date / datetime / 'YYYY-MM-DD' / 'YYYYMMDD' 统一成 date。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning("无法解析日期: %r", value)
    return None


@dataclass(frozen=True)
class ConceptDef:
    """一个标准科目的定义"""

    key: str
    label: str
    statement: str
    period_type: str
    sign: float
    unit: str | None
    chains: Mapping[str, tuple[str, ...]]

    def chain(self, taxonomy: str) -> tuple[str, ...]:
        return self.chains.get(taxonomy, ())


@dataclass(frozen=True)
class ConceptMap:
    """概念映射表（不可变，加载时校验）"""

    version: str
    taxonomies: Mapping[str, Any]
    concepts: Mapping[str, ConceptDef]
    _index: Mapping[tuple[str, str], tuple[str, int]]
    _collisions: tuple[tuple[str, str, tuple[str, ...]], ...]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ConceptMap":
        raw = json.loads(Path(path or _MAP_PATH).read_text(encoding="utf-8"))
        version = raw.get("version")
        if not version:
            raise ConceptMapError("concept_map.json 缺少 version（映射表必须带版本号入库）")

        concepts: dict[str, ConceptDef] = {}
        for key, spec in (raw.get("concepts") or {}).items():
            statement = spec.get("statement")
            period_type = spec.get("period_type", "duration")
            if statement not in STATEMENTS:
                raise ConceptMapError(f"概念 {key} 的 statement 非法: {statement!r}")
            if period_type not in PERIOD_TYPES:
                raise ConceptMapError(f"概念 {key} 的 period_type 非法: {period_type!r}")
            if not spec.get("label"):
                raise ConceptMapError(f"概念 {key} 缺少 label（前端展示名）")
            chains = {
                tax: tuple(tags)
                for tax, tags in spec.items()
                if tax not in {"label", "statement", "period_type", "sign", "unit"} and isinstance(tags, list)
            }
            concepts[key] = ConceptDef(
                key=key,
                label=spec["label"],
                statement=statement,
                period_type=period_type,
                sign=float(spec.get("sign", raw.get("default_sign", 1))),
                unit=spec.get("unit"),
                chains=chains,
            )

        index: dict[tuple[str, str], tuple[str, int]] = {}
        seen: dict[tuple[str, str], list[str]] = defaultdict(list)
        for key, concept in concepts.items():
            for taxonomy, tags in concept.chains.items():
                for rank, tag in enumerate(tags):
                    slot = (taxonomy, tag)
                    seen[slot].append(key)
                    # 同标签多概念：按链内优先级（rank）取胜，rank 相同则按科目名排序保证确定性
                    current = index.get(slot)
                    candidate = (key, rank)
                    if current is None or (candidate[1], candidate[0]) < (current[1], current[0]):
                        index[slot] = candidate

        collisions = tuple((tax, tag, tuple(sorted(keys))) for (tax, tag), keys in seen.items() if len(keys) > 1)
        if collisions:
            logger.warning(
                "概念映射表存在 %d 处标签冲突（已按链内优先级取胜）: %s",
                len(collisions),
                collisions[:5],
            )

        return cls(
            version=version,
            taxonomies=raw.get("taxonomies") or {},
            concepts=concepts,
            _index=index,
            _collisions=collisions,
        )

    @property
    def collisions(self) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        return self._collisions

    def concepts_of(self, statement: str) -> tuple[str, ...]:
        return tuple(k for k, c in self.concepts.items() if c.statement == statement)

    def resolve(self, tag: str, taxonomy: str = "us-gaap") -> str | None:
        hit = self._index.get((taxonomy, tag))
        return hit[0] if hit else None


_CONCEPT_MAP: ConceptMap | None = None


def load_concept_map(path: str | Path | None = None, *, reload: bool = False) -> ConceptMap:
    """加载（并缓存）概念映射表。"""
    global _CONCEPT_MAP
    if path is not None:
        return ConceptMap.load(path)
    if _CONCEPT_MAP is None or reload:
        _CONCEPT_MAP = ConceptMap.load()
    return _CONCEPT_MAP


@dataclass(frozen=True)
class RawFact:
    """归一化前的原始事实：一行 = 某源某标签某期间某版本"""

    taxonomy: str
    tag: str
    value: Any
    unit: str = ""
    start: date | None = None
    end: date | None = None
    filed: date | None = None
    accn: str | None = None
    form: str | None = None


def from_companyfacts(payload: Mapping[str, Any], *, taxonomy: str | None = None) -> list[RawFact]:
    """展平 SEC `companyfacts` 响应（FIN-01 `sec_edgar` 直出的官方结构）。

    facts[taxonomy][tag].units[unit] -> [{start,end,val,accn,filed,form,fy,fp,frame}]
    """
    facts: list[RawFact] = []
    for tax, tags in (payload.get("facts") or {}).items():
        if taxonomy and tax != taxonomy:
            continue
        for tag, body in (tags or {}).items():
            for unit, rows in ((body or {}).get("units") or {}).items():
                for row in rows or []:
                    facts.append(
                        RawFact(
                            taxonomy=tax,
                            tag=tag,
                            value=row.get("val"),
                            unit=unit,
                            start=_as_date(row.get("start")),
                            end=_as_date(row.get("end")),
                            filed=_as_date(row.get("filed")),
                            accn=row.get("accn"),
                            form=row.get("form"),
                        )
                    )
    return facts


def from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    taxonomy: str,
    tag_field: str,
    value_field: str,
    unit_field: str | None = None,
    start_field: str | None = None,
    end_field: str | None = None,
    filed_field: str | None = None,
    accn_field: str | None = None,
    form_field: str | None = None,
    default_unit: str = "",
) -> list[RawFact]:
    """行式源的通用适配（tushare 列名 / 富途 display_name 均走这条）。"""
    facts: list[RawFact] = []
    for row in rows:
        facts.append(
            RawFact(
                taxonomy=taxonomy,
                tag=str(row.get(tag_field, "")),
                value=row.get(value_field),
                unit=str(row.get(unit_field, default_unit)) if unit_field else default_unit,
                start=_as_date(row.get(start_field)) if start_field else None,
                end=_as_date(row.get(end_field)) if end_field else None,
                filed=_as_date(row.get(filed_field)) if filed_field else None,
                accn=(str(row.get(accn_field)) if accn_field and row.get(accn_field) else None),
                form=(str(row.get(form_field)) if form_field and row.get(form_field) else None),
            )
        )
    return facts


@dataclass
class NormalizedFact:
    """归一化后的事实：标准科目 + 期间 + 版本时间轴"""

    entity_id: str
    concept: str
    statement: str
    value: float
    unit: str
    period_start: date | None
    period_end: date
    filed_at: date | None
    source: str
    source_tag: str
    taxonomy: str
    accession_no: str | None = None
    derived: bool = False
    check_failed: list[str] = field(default_factory=list)

    @property
    def fact_key(self) -> tuple[str, str, date | None, date, str]:
        """唯一键（docs/28 §3.2）：禁止只按 fy 去重"""
        return (self.entity_id, self.concept, self.period_start, self.period_end, self.unit)


@dataclass
class VersionedFact:
    """同唯一键下的双时间轴取值"""

    entity_id: str
    concept: str
    statement: str
    unit: str
    period_start: date | None
    period_end: date
    value_as_reported: float
    value_latest: float
    filed_as_reported: date | None
    filed_latest: date | None
    versions: int
    restated: bool
    source: str
    source_tag: str
    accession_no: str | None = None
    derived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "concept": self.concept,
            "statement": self.statement,
            "unit": self.unit,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat(),
            "value_as_reported": self.value_as_reported,
            "value_latest": self.value_latest,
            "filed_as_reported": self.filed_as_reported.isoformat() if self.filed_as_reported else None,
            "filed_latest": self.filed_latest.isoformat() if self.filed_latest else None,
            "versions": self.versions,
            "restated": self.restated,
            "source": self.source,
            "source_tag": self.source_tag,
            "accession_no": self.accession_no,
            "derived": self.derived,
        }


class ConceptMapper:
    """原始标签 → 标准科目（含双时间轴折叠）"""

    def __init__(
        self,
        concept_map: ConceptMap | None = None,
        *,
        source: str = "sec",
        default_taxonomy: str = "us-gaap",
    ) -> None:
        self.map = concept_map or load_concept_map()
        self.source = source
        self.default_taxonomy = default_taxonomy
        self._unmapped: Counter[str] = Counter()
        self._skipped: Counter[str] = Counter()

    @property
    def stats(self) -> dict[str, dict[str, int]]:
        return {"unmapped": dict(self._unmapped), "skipped": dict(self._skipped)}

    def reset_stats(self) -> None:
        self._unmapped.clear()
        self._skipped.clear()

    def resolve(self, tag: str, taxonomy: str | None = None) -> str | None:
        concept = self.map.resolve(tag, taxonomy or self.default_taxonomy)
        if concept is None:
            self._unmapped[f"{taxonomy or self.default_taxonomy}:{tag}"] += 1
        return concept

    def normalize(
        self,
        raw_facts: Iterable[RawFact],
        *,
        entity_id: str,
        source: str | None = None,
    ) -> list[NormalizedFact]:
        """归一化一批原始事实；落空的标签与脏数据只计数，不猜值。"""
        out: list[NormalizedFact] = []
        src = source or self.source
        for raw in raw_facts:
            concept_key = self.map.resolve(raw.tag, raw.taxonomy or self.default_taxonomy)
            if concept_key is None:
                self._unmapped[f"{raw.taxonomy}:{raw.tag}"] += 1
                continue
            concept = self.map.concepts[concept_key]

            period_end = raw.end
            if period_end is None:
                self._skipped["no_period_end"] += 1
                continue
            period_start = raw.start
            if concept.period_type == "duration" and period_start is None:
                self._skipped["duration_without_start"] += 1
                continue
            if concept.period_type == "instant":
                period_start = None  # 时点值，不带区间

            try:
                value = float(raw.value) * concept.sign
            except (TypeError, ValueError):
                self._skipped["bad_value"] += 1
                continue
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                self._skipped["bad_value"] += 1
                continue

            out.append(
                NormalizedFact(
                    entity_id=entity_id,
                    concept=concept.key,
                    statement=concept.statement,
                    value=value,
                    unit=raw.unit or concept.unit or "",
                    period_start=period_start,
                    period_end=period_end,
                    filed_at=raw.filed,
                    source=src,
                    source_tag=raw.tag,
                    taxonomy=raw.taxonomy or self.default_taxonomy,
                    accession_no=raw.accn,
                )
            )
        return out

    @staticmethod
    def collapse_versions(facts: Sequence[NormalizedFact]) -> list[VersionedFact]:
        """按唯一键折叠出 as-reported / latest（重述追踪的副产品）。"""
        buckets: dict[tuple[Any, ...], list[NormalizedFact]] = defaultdict(list)
        for fact in facts:
            buckets[fact.fact_key].append(fact)

        out: list[VersionedFact] = []
        for key, group in buckets.items():
            ordered = sorted(group, key=lambda f: (f.filed_at or date.min, f.accession_no or ""))
            first, last = ordered[0], ordered[-1]
            restated = len(ordered) > 1 and not math.isclose(first.value, last.value, rel_tol=1e-9, abs_tol=1e-9)
            out.append(
                VersionedFact(
                    entity_id=key[0],
                    concept=key[1],
                    statement=last.statement,
                    unit=key[4],
                    period_start=key[2],
                    period_end=key[3],
                    value_as_reported=first.value,
                    value_latest=last.value,
                    filed_as_reported=first.filed_at,
                    filed_latest=last.filed_at,
                    versions=len(ordered),
                    restated=restated,
                    source=last.source,
                    source_tag=last.source_tag,
                    accession_no=last.accession_no,
                    derived=last.derived,
                )
            )
        return sorted(out, key=lambda v: (v.concept, v.period_end))

    def map_facts(
        self,
        raw_facts: Iterable[RawFact],
        *,
        entity_id: str,
        source: str | None = None,
    ) -> list[VersionedFact]:
        """归一化 + 双时间轴折叠的便捷入口。"""
        return self.collapse_versions(self.normalize(raw_facts, entity_id=entity_id, source=source))
