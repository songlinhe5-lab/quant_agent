"""
FIN-05 · 分析引擎（纯函数，无 IO）
==================================

docs/28 §5.1：common-size / TTM / DuPont / 现金流质量 / Piotroski F · Altman Z · Beneish M。

铁律在此落地（AGENTS §5 数字可溯源 + FIN 红线）：
  - 每个分数必须给**分项明细与阈值**，只给总分等于让用户信黑箱
  - 缺失科目一律 `None` 并列进 `missing`，**禁止补 0**——补出来的 Z-Score 会杀人
  - 推导值（TTM / 拆季）必须标 `derived=True`，前端标浅色角标
  - 输入是普通 dict / dataclass，本模块不 import ORM，回测与路由共用同一套实现

入参契约：
  - `Point(label, fiscal_year, fiscal_period, value)`：一个科目在某期间的值，
    `label` 与宽表列名一致（`period_label` 产物，如 "FY2025 Q1"）
  - 期间快照 `Mapping[label, Mapping[concept, value]]`：跨表取数由调用方装配
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# 单季槽位：TTM 只认真正的单季（H2 是两个季度合计，不能混进滚动和）
_QUARTER_SLOT = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

CAGR_MIN_YEARS = 1.0


@dataclass(frozen=True, slots=True)
class Point:
    """单科目单期间的值。流量/存量口径由调用方保证一致（本模块不判 start/end）。"""

    label: str
    fiscal_year: int
    fiscal_period: str
    value: float
    derived: bool = False


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """安全除法：任一侧缺失或分母为 0 → None（缺失不补零，除零不猜）。"""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _avg(current: float | None, previous: float | None) -> tuple[float | None, str]:
    """资产负债表均值：有上期用均值，没有就退期末值并明示基数口径。"""
    if current is None:
        return None, "ending"
    if previous is not None:
        return (current + previous) / 2, "average"
    return current, "ending"


# ─────────────────────────────────────────
#  1. 期间推导：单季展开 → TTM 滚动
# ─────────────────────────────────────────


def quarterly_values(points: Sequence[Point]) -> list[Point]:
    """把一个科目**同一财年**的 YTD / 单季值展开成单季序列。

    - Q2 = H1 − Q1、Q3 = 9M − H1、Q4 = FY − 9M（与 FIN-02 `derive_quarters` 同一套算术，
      但那边要真实起止日期，本模块的 Point 不携带日期 → 本地重算，口径保持一致）
    - 只有 H1+FY 时只能得 H2（两季合计），TTM 用不了 → 不产出（宁缺毋假）
    - 已是单季的（Q1..Q4）原样保留；重复槽位以先出现者为准（调用方应已按 filed 仲裁过版本）
    """
    if not points:
        return []
    fiscal_year = _single_fy(points)

    cumulative: dict[str, float] = {}
    direct: dict[int, Point] = {}
    for p in points:
        if p.fiscal_period in {"Q1", "H1", "9M", "FY"}:
            cumulative.setdefault(p.fiscal_period, p.value)
        if p.fiscal_period in _QUARTER_SLOT:
            direct.setdefault(_QUARTER_SLOT[p.fiscal_period], p)
        # H2 与未知标签：无法可靠定位单季槽位，不参与

    def _pt(label: str, slot: int, value: float, derived: bool) -> Point:
        return Point(
            label=f"FY{fiscal_year} {label}",
            fiscal_year=fiscal_year,
            fiscal_period=label,
            value=value,
            derived=derived,
        )

    out: dict[int, Point] = {}
    q1, h1, nine, fy = (cumulative.get(k) for k in ("Q1", "H1", "9M", "FY"))
    if q1 is not None:
        out.setdefault(1, _pt("Q1", 1, q1, False))
    if q1 is not None and h1 is not None:
        out.setdefault(2, _pt("Q2", 2, h1 - q1, True))
    if h1 is not None and nine is not None:
        out.setdefault(3, _pt("Q3", 3, nine - h1, True))
    if nine is not None and fy is not None:
        out.setdefault(4, _pt("Q4", 4, fy - nine, True))
    for slot, p in direct.items():
        out.setdefault(slot, p)
    return [out[slot] for slot in sorted(out)]


def _single_fy(points: Sequence[Point]) -> int:
    fys = {p.fiscal_year for p in points}
    if len(fys) != 1:
        raise ValueError(f"拆季必须限定单一财年，收到: {sorted(fys)}")
    return fys.pop()


def ttm_series(quarters: Sequence[Point]) -> list[Point]:
    """四季滚动和：按 (财年, 季度槽) 连续 4 季才有 TTM，缺口即不出（不猜）。

    财年错位公司的同比必须用 TTM（docs/28 §5.1）——拿 FY2026 Q1 的 YTD 直接比
    FY2025 FY 会把口径差一个季度。
    """
    slots: list[tuple[int, int, Point]] = []
    for p in quarters:
        slot = _QUARTER_SLOT.get(p.fiscal_period)
        if slot is not None:
            slots.append((p.fiscal_year, slot, p))
    slots.sort(key=lambda item: (item[0], item[1]))

    out: list[Point] = []
    window: list[tuple[int, int, Point]] = []
    for item in slots:
        window.append(item)
        if len(window) > 4:
            window.pop(0)
        if len(window) == 4 and _consecutive([(k, s) for k, s, _p in window]):
            _fy, _slot, end = window[-1]
            out.append(
                Point(
                    label=f"{end.label} TTM",
                    fiscal_year=end.fiscal_year,
                    fiscal_period=end.fiscal_period,
                    value=sum(p.value for _k, _s, p in window),
                    derived=True,
                )
            )
    return out


def _consecutive(keys: Sequence[tuple[int, int]]) -> bool:
    """4 个 (财年, 槽) 是否首尾相接：Q4(2024) → Q1(2025) 步长也是 1。"""
    return all((keys[i + 1][0] - keys[i][0]) * 4 + (keys[i + 1][1] - keys[i][1]) == 1 for i in range(len(keys) - 1))


def cagr(begin: float | None, end: float | None, years: float | None) -> float | None:
    """复合增长率：起点 ≤0 或年数非法 → None（负基数开方无经济含义，不猜）。"""
    if begin is None or end is None or years is None or years < CAGR_MIN_YEARS or begin <= 0:
        return None
    return (end / begin) ** (1 / years) - 1


def common_size_series(values: Mapping[str, float | None], base: Mapping[str, float | None]) -> dict[str, float | None]:
    """占基线百分比（利润/现金流以收入为基、资产负债以总资产为基，基线由调用方选）。"""
    return {
        label: None if not base.get(label) or value is None else value / abs(base[label]) * 100
        for label, value in values.items()
    }


# ─────────────────────────────────────────
#  2. DuPont（仅 FY 期间出数：季度口径须年化，容易误导）
# ─────────────────────────────────────────


def dupont_series(snapshots: Mapping[str, Mapping[str, float | None]]) -> list[dict[str, Any]]:
    """逐财年 DuPont 分解。

    snapshots：{FY 期间标签: {concept: value}}，须同时含利润表与资产负债表科目。
    3 因子：净利率 × 资产周转率 × 权益乘数；5 因子再加税负 × 利息负担 × 营业利润率。
    资产默认均值口径（缺上一年报退期末值，`asset_base` 明示）；权益固定用**期末值**——
    乘数分母必须与直算 ROE 分母同基数，链式乘积才严格回到 ROE（均值权益会引入半期错位）。
    乘积与直算 ROE 相对差 >1% 标 `check_failed`，只标注不改数。
    """
    out: list[dict[str, Any]] = []
    labels = sorted(k for k in snapshots if _prev_fy(k))
    for label in labels:
        snap = snapshots[label]
        prior = snapshots.get(_prev_fy(label) or "", {})
        assets, asset_base = _avg(snap.get("total_assets"), prior.get("total_assets"))
        equity = snap.get("stockholders_equity")

        net_margin = _ratio(snap.get("net_income"), snap.get("revenue"))
        asset_turnover = _ratio(snap.get("revenue"), assets)
        equity_multiplier = _ratio(assets, equity)
        roe_direct = _ratio(snap.get("net_income"), equity)

        tax_burden = _ratio(snap.get("net_income"), snap.get("pretax_income"))
        interest_burden = _ratio(snap.get("pretax_income"), snap.get("operating_income"))
        operating_margin = _ratio(snap.get("operating_income"), snap.get("revenue"))

        factors = {"net_margin": net_margin, "asset_turnover": asset_turnover, "equity_multiplier": equity_multiplier}
        roe_product = _product(net_margin, asset_turnover, equity_multiplier)
        factors5 = {
            "tax_burden": tax_burden,
            "interest_burden": interest_burden,
            "operating_margin": operating_margin,
            **factors,
        }
        roe_product5 = _product(tax_burden, interest_burden, operating_margin, asset_turnover, equity_multiplier)

        out.append(
            {
                "period": label,
                "roe": roe_direct,
                "factors": factors,
                "roe_product": roe_product,
                "factors_5": factors5,
                "roe_product_5": roe_product5,
                "check_failed": _identity_broken(roe_direct, roe_product, roe_product5),
                "asset_base": asset_base,
                "equity_base": "ending",
                "missing": _missing(snap, "net_income", "revenue", "total_assets", "stockholders_equity"),
            }
        )
    return out


def _prev_fy(label: str) -> str | None:
    """'FY2025' → 'FY2024'；非 FY 标签（含 'FY2025 Q1'）→ None。"""
    if not label.startswith("FY") or " " in label:
        return None
    try:
        return f"FY{int(label[2:]) - 1}"
    except ValueError:
        return None


def _product(*values: float | None) -> float | None:
    if any(v is None for v in values):
        return None
    result = 1.0
    for v in values:
        result *= v
    return result


def _identity_broken(roe_direct: float | None, *products: float | None) -> bool:
    """乘积路径与直算路径相对差 >1% 视为勾稽失败（浮点容差内不算）。"""
    if roe_direct is None:
        return False
    return any(
        product is not None and abs(product - roe_direct) > 0.01 * max(abs(roe_direct), 1e-12) for product in products
    )


def _missing(snapshot: Mapping[str, float | None], *concepts: str) -> list[str]:
    return [c for c in concepts if snapshot.get(c) is None]


def _missing_both(
    current: Mapping[str, float | None], previous: Mapping[str, float | None], *concepts: str
) -> list[str]:
    """双快照函数用：任一侧缺失即算缺（merged dict 会掩盖单侧缺失，导致 missing 漏报）。"""
    return [c for c in concepts if current.get(c) is None or previous.get(c) is None]


# ─────────────────────────────────────────
#  3. 现金流质量（同跨度期间可比；FY 最稳）
# ─────────────────────────────────────────


def cash_flow_quality(snapshot: Mapping[str, float | None], prior_assets: float | None = None) -> dict[str, Any]:
    """利润含金量：CFO/净利润、应计比率、FCF 转化率、资本开支强度。

    capex 已在归一化层归为**正数**（PaymentsToAcquire… 原值为正），故 FCF = CFO − capex。
    """
    assets, asset_base = _avg(snapshot.get("total_assets"), prior_assets)
    net_income, cfo = snapshot.get("net_income"), snapshot.get("cfo")
    capex, revenue = snapshot.get("capex"), snapshot.get("revenue")

    accruals = None if net_income is None or cfo is None else net_income - cfo
    fcf = None if cfo is None or capex is None else cfo - capex
    return {
        "cfo_to_net_income": _ratio(cfo, net_income),
        "accruals_ratio": _ratio(accruals, assets),
        "fcf": fcf,
        "fcf_to_net_income": _ratio(fcf, net_income),
        "fcf_margin": _ratio(fcf, revenue),
        "capex_intensity": _ratio(capex, revenue),
        "asset_base": asset_base,
        "missing": _missing(snapshot, "net_income", "cfo", "capex", "revenue", "total_assets"),
    }


# ─────────────────────────────────────────
#  4. 质量三分（全部给分项与阈值，禁黑箱）
# ─────────────────────────────────────────


def piotroski_f(current: Mapping[str, float | None], previous: Mapping[str, float | None]) -> dict[str, Any]:
    """Piotroski F-Score（0~9）。9 项逐条给 passed；无法判定的项 passed=None 且不计分。

    入参：当年与上一年**年报**期间快照。比例基数用期末值，保证可复算（不引入均值口径争议）。
    """
    cur_assets = current.get("total_assets")
    prev_assets = previous.get("total_assets")
    cur_roa = _ratio(current.get("net_income"), cur_assets)
    prev_roa = _ratio(previous.get("net_income"), prev_assets)
    cur_shares = current.get("shares_diluted")
    prev_shares = previous.get("shares_diluted")

    def _gt(a: float | None, b: float | None) -> bool | None:
        return None if a is None or b is None else a > b

    def _lt(a: float | None, b: float | None) -> bool | None:
        return None if a is None or b is None else a < b

    def _positive(v: float | None) -> bool | None:
        return None if v is None else v > 0

    items = [
        ("roa_positive", "ROA > 0", _positive(cur_roa)),
        ("cfo_positive", "经营现金流 > 0", _positive(current.get("cfo"))),
        ("roa_improved", "ΔROA > 0", _gt(cur_roa, prev_roa)),
        ("accruals_quality", "CFO > 净利润（应计质量）", _gt(current.get("cfo"), current.get("net_income"))),
        (
            "leverage_down",
            "长期杠杆下降",
            _lt(
                _ratio(current.get("long_term_debt"), cur_assets),
                _ratio(previous.get("long_term_debt"), prev_assets),
            ),
        ),
        (
            "current_ratio_up",
            "流动比率上升",
            _gt(
                _ratio(current.get("total_current_assets"), current.get("total_current_liabilities")),
                _ratio(previous.get("total_current_assets"), previous.get("total_current_liabilities")),
            ),
        ),
        ("no_dilution", "股本未增加", None if cur_shares is None or prev_shares is None else cur_shares <= prev_shares),
        (
            "gross_margin_up",
            "毛利率上升",
            _gt(
                _ratio(current.get("gross_profit"), current.get("revenue")),
                _ratio(previous.get("gross_profit"), previous.get("revenue")),
            ),
        ),
        (
            "turnover_up",
            "资产周转率上升",
            _gt(_ratio(current.get("revenue"), cur_assets), _ratio(previous.get("revenue"), prev_assets)),
        ),
    ]
    return {
        "score": sum(1 for _, _, p in items if p),
        "max_score": 9,
        "unknown": [key for key, _n, p in items if p is None],
        "items": [{"key": key, "name": name, "passed": passed} for key, name, passed in items],
        "missing": _missing_both(
            current,
            previous,
            "net_income",
            "cfo",
            "total_assets",
            "revenue",
            "gross_profit",
            "total_current_assets",
            "total_current_liabilities",
            "shares_diluted",
        ),
    }


ALTMAN_ZONES = ((2.99, "safe"), (1.81, "grey"), (float("-inf"), "distress"))


def altman_z(snapshot: Mapping[str, float | None], market_cap: float | None = None) -> dict[str, Any]:
    """Altman Z-Score（上市公司制造业公式）。market_cap 由调用方从行情侧传入，**禁止在此估算**。

    Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
    Z ≥ 2.99 安全 / 1.81~2.99 灰色 / < 1.81 危险。任一分项缺失 → z=None 只给分项。
    """
    ta, tl = snapshot.get("total_assets"), snapshot.get("total_liabilities")
    working_capital = (
        None
        if snapshot.get("total_current_assets") is None or snapshot.get("total_current_liabilities") is None
        else snapshot["total_current_assets"] - snapshot["total_current_liabilities"]
    )
    components = {
        "x1_working_capital": _ratio(working_capital, ta),
        "x2_retained_earnings": _ratio(snapshot.get("retained_earnings"), ta),
        "x3_ebit": _ratio(snapshot.get("operating_income"), ta),
        "x4_market_cap": _ratio(market_cap, tl),
        "x5_revenue": _ratio(snapshot.get("revenue"), ta),
    }
    weights = {
        "x1_working_capital": 1.2,
        "x2_retained_earnings": 1.4,
        "x3_ebit": 3.3,
        "x4_market_cap": 0.6,
        "x5_revenue": 1.0,
    }
    if any(v is None for v in components.values()):
        z, zone = None, None
    else:
        z = sum(weights[key] * value for key, value in components.items())
        zone = next(name for threshold, name in ALTMAN_ZONES if z >= threshold)
    missing = _missing(
        snapshot,
        "total_assets",
        "total_liabilities",
        "total_current_assets",
        "total_current_liabilities",
        "retained_earnings",
        "operating_income",
        "revenue",
    )
    if market_cap is None:
        missing.append("market_cap")
    return {
        "z": z,
        "zone": zone,
        "thresholds": {"safe": 2.99, "grey": 1.81},
        "components": components,
        "weights": weights,
        "missing": missing,
    }


_BENEISH_COEFFS = {
    "dsri": 0.920,
    "gmi": 0.528,
    "aqi": 0.404,
    "sgi": 0.892,
    "depi": 0.115,
    "sgai": -0.172,
    "lvgi": -0.327,
    "tata": 4.679,
}
BENEISH_INTERCEPT = -4.84
BENEISH_FLAG_THRESHOLD = -1.78  # M > −1.78 → 疑似盈余操纵（Beneish 1999）


def beneish_m(current: Mapping[str, float | None], previous: Mapping[str, float | None]) -> dict[str, Any]:
    """Beneish M-Score（8 指数）。任一指数算不出 → m=None，但已算出的指数照常透出。

    DSRI 应收/收入恶化 · GMI 毛利率恶化 · AQI 资产质量恶化 · SGI 收入激增 ·
    DEPI 折旧率下降 · SGAI 销管费率 · LVGI 杠杆 · TATA 应计/总资产。
    """
    ta_cur, ta_prev = current.get("total_assets"), previous.get("total_assets")
    rev_cur, rev_prev = current.get("revenue"), previous.get("revenue")

    dsri = _ratio(
        _ratio(current.get("accounts_receivable"), rev_cur),
        _ratio(previous.get("accounts_receivable"), rev_prev),
    )
    gmi = _ratio(
        _ratio(previous.get("gross_profit"), rev_prev),
        _ratio(current.get("gross_profit"), rev_cur),
    )
    aqi = _ratio(
        _ratio(_soft_assets(current, ta_cur), ta_cur),
        _ratio(_soft_assets(previous, ta_prev), ta_prev),
    )
    sgi = _ratio(rev_cur, rev_prev)
    depi = _ratio(_dep_rate(previous), _dep_rate(current))
    sgai = _ratio(
        _ratio(current.get("selling_general_admin"), rev_cur),
        _ratio(previous.get("selling_general_admin"), rev_prev),
    )
    lvgi = _ratio(
        _ratio(current.get("total_liabilities"), ta_cur),
        _ratio(previous.get("total_liabilities"), ta_prev),
    )
    tata = _ratio(
        None
        if current.get("net_income") is None or current.get("cfo") is None
        else current["net_income"] - current["cfo"],
        ta_cur,
    )

    indices = {
        "dsri": dsri,
        "gmi": gmi,
        "aqi": aqi,
        "sgi": sgi,
        "depi": depi,
        "sgai": sgai,
        "lvgi": lvgi,
        "tata": tata,
    }
    if any(v is None for v in indices.values()):
        m, flagged = None, None
    else:
        m = BENEISH_INTERCEPT + sum(_BENEISH_COEFFS[key] * value for key, value in indices.items())
        flagged = m > BENEISH_FLAG_THRESHOLD
    return {
        "m": m,
        "flagged": flagged,
        "threshold": BENEISH_FLAG_THRESHOLD,
        "coefficients": _BENEISH_COEFFS,
        "intercept": BENEISH_INTERCEPT,
        "indices": indices,
        "missing": _missing_both(
            current,
            previous,
            "total_assets",
            "total_liabilities",
            "revenue",
            "accounts_receivable",
            "gross_profit",
            "selling_general_admin",
            "depreciation_amortization",
            "ppe_net",
            "total_current_assets",
            "net_income",
            "cfo",
        ),
    }


def _soft_assets(snapshot: Mapping[str, float | None], ta: float | None) -> float | None:
    """软资产 = 总资产 − (流动资产 + 固定资产净额)。任一缺失 → None。"""
    if any(snapshot.get(k) is None for k in ("total_current_assets", "ppe_net")) or ta is None:
        return None
    return ta - (snapshot["total_current_assets"] + snapshot["ppe_net"])


def _dep_rate(snapshot: Mapping[str, float | None]) -> float | None:
    """折旧率 = DA / (DA + PPE 净额)。"""
    da, ppe = snapshot.get("depreciation_amortization"), snapshot.get("ppe_net")
    if da is None or ppe is None:
        return None
    return _ratio(da, da + ppe)
