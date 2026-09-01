"""
FIN-05: 分析引擎（domain/financials/analytics.py）— 手算对照测试
================================================================

全部 golden 数值用**手算**得出（docs/28 §5.1 要求手算对照，禁"实现对着实现写"）。
红线：缺失科目必须 None + missing 清单，任何情况下不得补 0。
"""

import pytest

from backend.domain.financials.analytics import (
    Point,
    altman_z,
    beneish_m,
    cagr,
    cash_flow_quality,
    common_size_series,
    dupont_series,
    piotroski_f,
    quarterly_values,
    ttm_series,
)


def q(fy: int, fp: str, value: float) -> Point:
    return Point(label=f"FY{fy} {fp}", fiscal_year=fy, fiscal_period=fp, value=value)


# ─────────────────────────────────────────
#  1. 拆季与 TTM
# ─────────────────────────────────────────


def test_quarterly_values_derive_q2_q3_q4_from_ytd():
    """手算：Q1=100, H1=210, 9M=330, FY=460 → Q2=110, Q3=120, Q4=130。"""
    points = [
        q(2025, "Q1", 100),
        q(2025, "H1", 210),
        q(2025, "9M", 330),
        q(2025, "FY", 460),
    ]
    out = quarterly_values(points)
    assert [(p.fiscal_period, p.value, p.derived) for p in out] == [
        ("Q1", 100.0, False),
        ("Q2", 110.0, True),
        ("Q3", 120.0, True),
        ("Q4", 130.0, True),
    ]


def test_quarterly_values_without_9m_never_fakes_q3_q4():
    """只有 H1+FY 时只能得 H2（两个季度合计），禁止把 H2 当 Q3/Q4。"""
    out = quarterly_values([q(2025, "H1", 210), q(2025, "FY", 460)])
    assert out == []  # H2 不是单季，TTM 不能用 → 整段不出


def test_quarterly_values_keeps_direct_quarter_and_rejects_multi_fy():
    out = quarterly_values([q(2025, "Q2", 110)])
    assert [(p.fiscal_period, p.derived) for p in out] == [("Q2", False)]

    with pytest.raises(ValueError, match="单一财年"):
        quarterly_values([q(2025, "Q1", 1), q(2024, "FY", 2)])


def test_ttm_series_rolling_four_quarters():
    """手算：2024 四季 100/110/120/130 → FY2024 Q4 TTM=460；2025 Q1=140 → TTM=500。"""
    quarters = [q(2024, fp, v) for fp, v in [("Q1", 100), ("Q2", 110), ("Q3", 120), ("Q4", 130)]]
    quarters.append(q(2025, "Q1", 140))
    out = ttm_series(quarters)

    assert [(p.label, p.value) for p in out] == [("FY2024 Q4 TTM", 460.0), ("FY2025 Q1 TTM", 500.0)]
    assert all(p.derived for p in out)


def test_ttm_series_stops_at_gap_and_ignores_h2():
    """缺口之后不出 TTM；H2 混进来也不能污染滚动和。"""
    quarters = [q(2024, fp, v) for fp, v in [("Q1", 100), ("Q2", 110), ("Q3", 120), ("Q4", 130)]]
    quarters.append(q(2025, "H2", 999))  # 非 Q 标签
    out = ttm_series(quarters)
    assert [p.label for p in out] == ["FY2024 Q4 TTM"]  # 缺 FY2025 Q1 → 不外推

    broken = [q(2024, fp, v) for fp, v in [("Q1", 100), ("Q2", 110), ("Q4", 130)]]
    assert ttm_series(broken) == []  # Q3 缺失 → 连续性断


def test_cagr_hand_calculated_and_guards():
    assert cagr(1000, 1200, 2) == pytest.approx((1200 / 1000) ** 0.5 - 1)
    assert cagr(None, 1200, 2) is None  # 缺起点
    assert cagr(0, 1200, 2) is None  # 负基数开方无经济含义
    assert cagr(-100, 200, 2) is None
    assert cagr(1000, 1200, 0.5) is None  # 年数不足


def test_common_size_series_uses_abs_base_and_never_zero_fills():
    out = common_size_series({"a": 50, "b": None, "c": -30}, {"a": 200, "b": 100, "c": 0})
    assert out == {"a": 25.0, "b": None, "c": None}  # 基线为 0 → None，不补零


# ─────────────────────────────────────────
#  2. DuPont（手算 golden）
# ─────────────────────────────────────────


def _dupont_snapshots():
    return {
        "FY2024": {
            "revenue": 1000.0,
            "net_income": 100.0,
            "pretax_income": 120.0,
            "operating_income": 150.0,
            "total_assets": 800.0,
            "stockholders_equity": 400.0,
        },
        "FY2025": {
            "revenue": 1200.0,
            "net_income": 132.0,
            "pretax_income": 150.0,
            "operating_income": 180.0,
            "total_assets": 1000.0,
            "stockholders_equity": 500.0,
        },
    }


def test_dupont_three_and_five_factor_hand_calculated():
    out = dupont_series(_dupont_snapshots())
    fy2025 = out[-1]

    # 均值资产 = (1000+800)/2 = 900；ROE = 132/500 = 0.264
    assert fy2025["asset_base"] == "average"
    assert fy2025["factors"]["net_margin"] == pytest.approx(0.11)
    assert fy2025["factors"]["asset_turnover"] == pytest.approx(1200 / 900)
    assert fy2025["factors"]["equity_multiplier"] == pytest.approx(900 / 500)
    assert fy2025["roe"] == pytest.approx(0.264)
    assert fy2025["roe_product"] == pytest.approx(0.11 * (1200 / 900) * (900 / 500))
    assert fy2025["check_failed"] is False  # 乘积路径与直算路径吻合

    # 5 因子：税负 × 利息负担 × 营业利润率 × 周转 × 乘数（链式相乘仍 = ROE）
    f5 = fy2025["factors_5"]
    assert f5["tax_burden"] == pytest.approx(132 / 150)
    assert f5["interest_burden"] == pytest.approx(150 / 180)
    assert f5["operating_margin"] == pytest.approx(180 / 1200)
    assert fy2025["roe_product_5"] == pytest.approx(0.264)


def test_dupont_falls_back_to_ending_balance_and_marks_base():
    out = dupont_series({"FY2025": _dupont_snapshots()["FY2025"]})  # 无上年报
    fy2025 = out[0]
    assert fy2025["asset_base"] == "ending" and fy2025["equity_base"] == "ending"
    assert fy2025["factors"]["asset_turnover"] == pytest.approx(1200 / 1000)


def test_dupont_missing_inputs_yield_none_not_zero():
    snapshots = {"FY2025": {"revenue": 1200.0, "total_assets": 1000.0}}  # 缺净利/权益
    out = dupont_series(snapshots)
    assert out[0]["roe"] is None and out[0]["roe_product"] is None
    assert set(out[0]["missing"]) == {"net_income", "stockholders_equity"}
    assert out[0]["check_failed"] is False  # 直算缺失时不判勾稽失败


def test_identity_broken_helper_flags_real_mismatch():
    from backend.domain.financials.analytics import _identity_broken

    assert _identity_broken(0.25, 0.20) is True  # 相对差 20%
    assert _identity_broken(0.25, 0.251) is False  # 浮点噪声内
    assert _identity_broken(None, 0.2) is False  # 直算缺失不判


# ─────────────────────────────────────────
#  3. 现金流质量（手算 golden）
# ─────────────────────────────────────────


def test_cash_flow_quality_hand_calculated():
    snap = {
        "net_income": 200.0,
        "cfo": 300.0,
        "capex": 80.0,
        "revenue": 1200.0,
        "total_assets": 1000.0,
    }
    out = cash_flow_quality(snap, prior_assets=800.0)

    assert out["asset_base"] == "average"  # (1000+800)/2 = 900
    assert out["cfo_to_net_income"] == pytest.approx(1.5)
    assert out["accruals_ratio"] == pytest.approx((200 - 300) / 900)
    assert out["fcf"] == pytest.approx(220.0)  # capex 归一为正数 → CFO − capex
    assert out["fcf_to_net_income"] == pytest.approx(1.1)
    assert out["fcf_margin"] == pytest.approx(220 / 1200)
    assert out["capex_intensity"] == pytest.approx(80 / 1200)
    assert out["missing"] == []


def test_cash_flow_quality_missing_capex_keeps_cfo_ratio():
    out = cash_flow_quality({"net_income": 200.0, "cfo": 300.0, "total_assets": 1000.0})
    assert out["cfo_to_net_income"] == pytest.approx(1.5)
    assert out["fcf"] is None and out["fcf_to_net_income"] is None
    assert "capex" in out["missing"] and "revenue" in out["missing"]


# ─────────────────────────────────────────
#  4. Piotroski F（手算 golden：8 项过、周转率降 → 8/9）
# ─────────────────────────────────────────


def _f_current():
    return {
        "net_income": 132.0,
        "cfo": 150.0,
        "total_assets": 1000.0,
        "revenue": 1200.0,
        "gross_profit": 360.0,
        "total_current_assets": 400.0,
        "total_current_liabilities": 200.0,
        "long_term_debt": 300.0,
        "shares_diluted": 1000.0,
    }


def _f_previous():
    return {
        "net_income": 100.0,
        "cfo": 120.0,
        "total_assets": 800.0,
        "revenue": 1000.0,
        "gross_profit": 250.0,
        "total_current_assets": 350.0,
        "total_current_liabilities": 200.0,
        "long_term_debt": 320.0,
        "shares_diluted": 1020.0,
    }


def test_piotroski_nine_items_hand_calculated():
    out = piotroski_f(_f_current(), _f_previous())

    passed = {i["key"]: i["passed"] for i in out["items"]}
    assert passed == {
        "roa_positive": True,  # 132/1000 = 0.132 > 0
        "cfo_positive": True,
        "roa_improved": True,  # 0.132 > 100/800 = 0.125
        "accruals_quality": True,  # 150 > 132
        "leverage_down": True,  # 300/1000 < 320/800
        "current_ratio_up": True,  # 2.0 > 1.75
        "no_dilution": True,  # 1000 ≤ 1020
        "gross_margin_up": True,  # 0.30 > 0.25
        "turnover_up": False,  # 1.20 < 1.25
    }
    assert out["score"] == 8 and out["max_score"] == 9 and out["unknown"] == []


def test_piotroski_unknown_items_are_excluded_not_failed():
    current = {k: v for k, v in _f_current().items() if k != "cfo"}
    out = piotroski_f(current, _f_previous())
    assert set(out["unknown"]) == {"cfo_positive", "accruals_quality"}  # 无法判定 ≠ 不合格
    assert out["score"] == 6 and out["max_score"] == 9


# ─────────────────────────────────────────
#  5. Altman Z（手算 golden）
# ─────────────────────────────────────────


def _z_snapshot():
    return {
        "total_current_assets": 400.0,
        "total_current_liabilities": 200.0,
        "total_assets": 1000.0,
        "total_liabilities": 500.0,
        "retained_earnings": 150.0,
        "operating_income": 180.0,
        "revenue": 1200.0,
    }


def test_altman_z_safe_zone_hand_calculated():
    out = altman_z(_z_snapshot(), market_cap=3000.0)

    # X1=0.2 X2=0.15 X3=0.18 X4=6.0 X5=1.2 → Z = 0.24+0.21+0.594+3.6+1.2 = 5.844
    assert out["components"]["x1_working_capital"] == pytest.approx(0.2)
    assert out["components"]["x4_market_cap"] == pytest.approx(6.0)
    assert out["z"] == pytest.approx(5.844)
    assert out["zone"] == "safe"


def test_altman_z_grey_and_distress_zones():
    assert altman_z(_z_snapshot(), market_cap=60.0)["zone"] == "grey"  # Z ≈ 2.316
    distress = {**_z_snapshot(), "retained_earnings": -300.0, "operating_income": -100.0, "revenue": 100.0}
    # Z = 0.24 − 0.42 − 0.33 + 0.06 + 0.1 = −0.35
    out = altman_z(distress, market_cap=50.0)
    assert out["z"] == pytest.approx(-0.35, abs=1e-9) and out["zone"] == "distress"


def test_altman_z_missing_market_cap_never_estimates():
    out = altman_z(_z_snapshot())
    assert out["z"] is None and out["zone"] is None  # 行情侧没给市值 → 拒绝出总分
    assert out["components"]["x4_market_cap"] is None and "market_cap" in out["missing"]
    assert out["components"]["x1_working_capital"] == pytest.approx(0.2)  # 分项照常透出


# ─────────────────────────────────────────
#  6. Beneish M（手算 golden）
# ─────────────────────────────────────────


def _b_current(ar: float = 120.0):
    return {
        "revenue": 1200.0,
        "accounts_receivable": ar,
        "gross_profit": 360.0,
        "selling_general_admin": 120.0,
        "depreciation_amortization": 60.0,
        "ppe_net": 400.0,
        "total_current_assets": 400.0,
        "total_assets": 1000.0,
        "total_liabilities": 500.0,
        "net_income": 132.0,
        "cfo": 150.0,
    }


def _b_previous():
    return {
        "revenue": 1000.0,
        "accounts_receivable": 100.0,
        "gross_profit": 250.0,
        "selling_general_admin": 100.0,
        "depreciation_amortization": 55.0,
        "ppe_net": 380.0,
        "total_current_assets": 350.0,
        "total_assets": 800.0,
        "total_liabilities": 420.0,
        "net_income": 100.0,
        "cfo": 120.0,
    }


def test_beneish_m_hand_calculated_not_flagged():
    out = beneish_m(_b_current(), _b_previous())

    assert out["indices"]["dsri"] == pytest.approx(1.0)  # (120/1200)/(100/1000)
    assert out["indices"]["gmi"] == pytest.approx(0.25 / 0.30)  # 毛利率恶化 → GMI < 1 时改善
    assert out["indices"]["aqi"] == pytest.approx(0.2 / 0.0875)  # 软资产 200 vs 70
    assert out["indices"]["sgi"] == pytest.approx(1.2)
    assert out["indices"]["depi"] == pytest.approx((55 / 435) / (60 / 460))
    assert out["indices"]["lvgi"] == pytest.approx(0.5 / 0.525)
    assert out["indices"]["tata"] == pytest.approx(-0.018)

    # M = −4.84 + Σ(coef·index) ≈ −1.9423 < −1.78 → 不疑似操纵
    expected = -4.84 + 0.920 * 1.0 + 0.528 * (0.25 / 0.30) + 0.404 * (0.2 / 0.0875) + 0.892 * 1.2
    expected += 0.115 * ((55 / 435) / (60 / 460)) - 0.172 * 1.0 - 0.327 * (0.5 / 0.525) + 4.679 * -0.018
    assert out["m"] == pytest.approx(expected, rel=1e-9)
    assert out["flagged"] is False


def test_beneish_m_flags_when_receivables_spike():
    """应收激增（DSRI=2.0）把 M 推过 −1.78 阈值 → flagged=True。"""
    out = beneish_m(_b_current(ar=240.0), _b_previous())
    assert out["indices"]["dsri"] == pytest.approx(2.0)
    assert out["flagged"] is True and out["m"] > -1.78


def test_beneish_m_missing_index_yields_no_total():
    current = {k: v for k, v in _b_current().items() if k != "selling_general_admin"}
    out = beneish_m(current, _b_previous())
    assert out["m"] is None and out["flagged"] is None  # 八项不齐不出总分，禁黑箱
    assert out["indices"]["dsri"] == pytest.approx(1.0)  # 已算出的分项照常透出
    assert "selling_general_admin" in out["missing"]
