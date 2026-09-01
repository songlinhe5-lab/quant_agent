"""
FIN-06 · 同业与行业引擎（docs/28 §5.2）
========================================

peer set 解析 + EDGAR `frames` 截面分位 + 行业聚合。三条红线：
  1. frames 一次请求拿**全市场**某 tag 的取值，禁止 N 次单票请求拼截面
  2. 样本 < PEER_MIN_SAMPLE 禁止出分位结论（`fin_peer_sample_too_small`，docs/28 §六）
  3. 时点科目必须用 `I` 后缀帧、流量用 CY / CY..Qn，用错后缀 SEC 直接 404（docs/28 §3.3）

本模块纯函数无 IO：Registry 取数在 `service.get_peers`，这里只算。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

# docs/28 §5.2：样本 < 8 家时禁止出分位结论（防噪音）
PEER_MIN_SAMPLE = 8

# instant 期间 → frames 的季度槽（期末所在季）：H1 末=Q2、9M 末=Q3、FY 末=Q4
_INSTANT_SLOT = {"Q1": "Q1", "Q2": "Q2", "H1": "Q2", "Q3": "Q3", "9M": "Q3", "Q4": "Q4", "FY": "Q4"}
# duration 期间 → frames 帧只到 Q3；Q4/H1/9M 流量截面不存在（宁缺毋假）
_DURATION_SLOT = {"Q1": "Q1", "Q2": "Q2", "Q3": "Q3"}


def frame_period(fiscal_year: int, fiscal_period: str, *, is_instant: bool) -> str | None:
    """(财年, 期间, 口径) → EDGAR frames 帧（如 CY2024Q3I）。无对应帧 → None（调用方拒绝）。"""
    period = (fiscal_period or "").upper()
    if is_instant:
        quarter = _INSTANT_SLOT.get(period)
        return f"CY{fiscal_year}{quarter}I" if quarter else None
    quarter = "FY" if period == "FY" else _DURATION_SLOT.get(period)
    return f"CY{fiscal_year}" if quarter == "FY" else (f"CY{fiscal_year}{quarter}" if quarter else None)


def parse_peer_set(raw: str | None) -> list[str]:
    """手工固定 peer 清单（docs/28 §5.2：分析师判断常优于机械分类）：逗号分隔、归一、去重保序。"""
    if not raw:
        return []
    seen: dict[str, None] = {}
    for item in str(raw).split(","):
        token = item.strip().upper()
        if token:
            seen.setdefault(token, None)
    return list(seen)


def frames_cross_section(payload: Mapping[str, Any]) -> dict[str, float]:
    """EDGAR frames 响应 → {entity_id: val}。结构变化显式失败，禁止静默拉空。"""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list):
        raise ValueError("FRAMES 响应结构变化（缺 data 列表）")
    out: dict[str, float] = {}
    for row in data:
        if not isinstance(row, Mapping):
            continue
        cik, val = row.get("cik"), row.get("val")
        if isinstance(cik, int) and isinstance(val, (int, float)):
            out[f"US:CIK{cik:010d}"] = float(val)
    return out


def percentile_rank(value: float, values: Sequence[float]) -> float:
    """截面分位 0~100（含本体）：小于本体的样本 + 并列折半（平均法，可复算）。"""
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + equal / 2) / len(values) * 100


def _quantile(ordered: Sequence[float], p: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def aggregate(values: Mapping[str, float], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """行业聚合：中位数 / 四分位 / 样本数；（给收入权重时）收入加权综合值。"""
    ordered = sorted(values.values())
    out: dict[str, Any] = {
        "count": len(ordered),
        "median": _quantile(ordered, 0.5) if ordered else None,
        "p25": _quantile(ordered, 0.25) if ordered else None,
        "p75": _quantile(ordered, 0.75) if ordered else None,
    }
    if weights:
        pairs = [(values[eid], weights[eid]) for eid in values if weights.get(eid)]
        total_w = sum(w for _v, w in pairs)
        if total_w > 0:
            out["revenue_weighted"] = sum(v * w for v, w in pairs) / total_w
    return out


def peer_view(
    cross_section: Mapping[str, float],
    *,
    entity_id: str,
    peer_ids: Sequence[str],
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """本体 + peer 截面视图。样本 < 8 → `percentile=None` + `insufficient` 标注（禁出结论）。"""
    if entity_id not in cross_section:
        raise ValueError(f"frames 截面里没有本体 {entity_id}（该期无披露或口径不一致）")
    if peer_ids:
        # 手工清单里有、但截面缺席的 peer 如实报告——不许悄悄缩样本还当没问题
        missing = [p for p in peer_ids if p != entity_id and p not in cross_section]
        sample = {entity_id: cross_section[entity_id]}
        sample.update({p: cross_section[p] for p in peer_ids if p != entity_id and p in cross_section})
    else:
        missing = []
        sample = dict(cross_section)  # 未指定 peer 清单 → 全市场截面（frames 一次请求的本意）

    count = len(sample)
    insufficient = count < PEER_MIN_SAMPLE
    return {
        "entity_id": entity_id,
        "value": cross_section[entity_id],
        "sample_size": count,
        "insufficient": insufficient,
        "percentile": None if insufficient else percentile_rank(cross_section[entity_id], list(sample.values())),
        "missing_peers": missing,
        "aggregates": aggregate(sample, weights),
        # FIN-09 性能/体验补齐：同业明细行（升序），散点图的数据支撑；本体在前端高亮
        "peer_rows": [{"entity_id": eid, "value": val} for eid, val in sorted(sample.items(), key=lambda kv: kv[1])],
    }
