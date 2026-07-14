"""
TRADE-01 · 期权定价引擎测试

5 tests: BS 定价精度 / Greeks 计算 / IV 反推 / IV Rank / 波动率微笑
"""

import pytest
import math

from backend.services.options_engine import (
    bs_price,
    bs_greeks,
    implied_vol,
    iv_rank,
    iv_percentile,
    vol_smile_analysis,
    compute_option_chain_greeks,
)


class TestBlackScholes:
    """Black-Scholes 定价精度测试"""

    def test_bs_price_call_put_parity(self):
        """测试 Call-Put Parity: C - P = S - K*e^(-rT)"""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20

        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")

        # Call-Put Parity: C - P = S - K*e^(-rT)
        expected = S - K * math.exp(-r * T)
        actual = call - put

        assert abs(actual - expected) < 1e-6, f"Call-Put Parity 违反: {actual} vs {expected}"

    def test_bs_price_itm_otm(self):
        """测试 ITM/OTM 期权价格合理性"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.20

        # ITM Call (S > K)
        itm_call = bs_price(110, 100, T, r, sigma, "call")
        assert itm_call > 10, f"ITM Call 应该 > 10 (intrinsic), got {itm_call}"

        # OTM Call (S < K)
        otm_call = bs_price(90, 100, T, r, sigma, "call")
        assert 0 < otm_call < 10, f"OTM Call 应该在 0-10 之间, got {otm_call}"

    def test_bs_price_boundary(self):
        """测试边界条件"""
        # T = 0 (到期)
        assert bs_price(110, 100, 0, 0.05, 0.2, "call") == 10  # ITM call
        assert bs_price(90, 100, 0, 0.05, 0.2, "call") == 0   # OTM call
        assert bs_price(90, 100, 0, 0.05, 0.2, "put") == 10   # ITM put
        assert bs_price(110, 100, 0, 0.05, 0.2, "put") == 0   # OTM put


class TestGreeks:
    """Greeks 计算测试"""

    def test_greeks_call(self):
        """测试 Call 期权 Greeks"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.20

        greeks = bs_greeks(S, K, T, r, sigma, "call")

        # Delta: Call 在 0~1 之间, ATM 约 0.5
        assert 0.4 < greeks.delta < 0.7, f"Call Delta 应在 0.4-0.7, got {greeks.delta}"

        # Gamma: 正数
        assert greeks.gamma > 0, f"Gamma 应为正, got {greeks.gamma}"

        # Vega: 正数
        assert greeks.vega > 0, f"Vega 应为正, got {greeks.vega}"

        # Theta: Call 通常为负 (时间衰减)
        assert greeks.theta < 0, f"Call Theta 应为负, got {greeks.theta}"

    def test_greeks_put(self):
        """测试 Put 期权 Greeks"""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.20

        greeks = bs_greeks(S, K, T, r, sigma, "put")

        # Delta: Put 在 -1~0 之间
        assert -0.7 < greeks.delta < -0.3, f"Put Delta 应在 -0.7~-0.3, got {greeks.delta}"

        # Gamma: 正数
        assert greeks.gamma > 0

        # Theta: Put 通常为负
        assert greeks.theta < 0


class TestImpliedVol:
    """隐含波动率反推测试"""

    def test_iv_roundtrip(self):
        """测试 IV 反推精度: 用已知 sigma 定价，再反推 IV"""
        S, K, T, r = 100, 105, 0.5, 0.05
        true_sigma = 0.25

        # 用 true_sigma 定价
        price = bs_price(S, K, T, r, true_sigma, "call")

        # 反推 IV
        calc_iv = implied_vol(price, S, K, T, r, "call")

        assert calc_iv is not None, "IV 反推失败"
        assert abs(calc_iv - true_sigma) < 0.001, f"IV 误差过大: {calc_iv} vs {true_sigma}"

    def test_iv_otm_option(self):
        """测试 OTM 期权的 IV 反推"""
        S, K, T, r = 100, 110, 0.25, 0.05
        true_sigma = 0.30

        price = bs_price(S, K, T, r, true_sigma, "call")
        calc_iv = implied_vol(price, S, K, T, r, "call")

        assert calc_iv is not None
        assert abs(calc_iv - true_sigma) < 0.002

    def test_iv_invalid_input(self):
        """测试无效输入的 IV 反推"""
        # 价格为 0
        assert implied_vol(0, 100, 100, 0.5, 0.05, "call") is None

        # T = 0
        assert implied_vol(5, 100, 100, 0, 0.05, "call") is None


class TestIVRank:
    """IV Rank 和 IV Percentile 测试"""

    def test_iv_rank_basic(self):
        """测试 IV Rank 基本计算"""
        history = [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.32, 0.35]

        # 当前 IV 在历史最低
        rank = iv_rank(0.15, history)
        assert rank == 0, f"最低 IV Rank 应为 0, got {rank}"

        # 当前 IV 在历史最高
        rank = iv_rank(0.35, history)
        assert rank == 100, f"最高 IV Rank 应为 100, got {rank}"

        # 当前 IV 在中间
        rank = iv_rank(0.25, history)
        assert 45 < rank < 55, f"中间 IV Rank 应接近 50, got {rank}"

    def test_iv_percentile_basic(self):
        """测试 IV Percentile 基本计算"""
        history = [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.32, 0.35]

        # 当前 IV = 0.25, 低于它的有 4 个 (0.15, 0.18, 0.20, 0.22)
        pctile = iv_percentile(0.25, history)
        expected = (4 / 9) * 100
        assert abs(pctile - expected) < 1, f"IV Percentile 误差: {pctile} vs {expected}"

    def test_iv_rank_empty_history(self):
        """测试空历史"""
        assert iv_rank(0.25, []) == 50.0
        assert iv_percentile(0.25, []) == 50.0


class TestVolSmile:
    """波动率微笑分析测试"""

    def test_vol_smile_analysis(self):
        """测试微笑曲线分析"""
        options_data = [
            {"strike": 90, "option_type": "call", "iv": 0.25, "volume": 100, "open_interest": 500},
            {"strike": 90, "option_type": "put", "iv": 0.28, "volume": 80, "open_interest": 400},
            {"strike": 100, "option_type": "call", "iv": 0.20, "volume": 200, "open_interest": 1000},
            {"strike": 100, "option_type": "put", "iv": 0.22, "volume": 150, "open_interest": 800},
            {"strike": 110, "option_type": "call", "iv": 0.23, "volume": 120, "open_interest": 600},
            {"strike": 110, "option_type": "put", "iv": 0.26, "volume": 90, "open_interest": 450},
        ]

        result = vol_smile_analysis(options_data)

        assert "smile" in result
        assert len(result["smile"]) == 3  # 3 个 strike
        assert result["atm_iv"] > 0
        assert result["skew_25d"] != 0  # 存在 skew

    def test_vol_smile_empty(self):
        """测试空数据"""
        result = vol_smile_analysis([])
        assert result["smile"] == []
        assert result["atm_iv"] == 0


class TestComputeChainGreeks:
    """批量 Greeks 计算测试"""

    def test_compute_chain(self):
        """测试批量计算"""
        options_data = [
            {
                "strike": 100,
                "expiry": "2024-12-20",
                "option_type": "call",
                "bid": 5.0,
                "ask": 5.5,
                "volume": 100,
                "open_interest": 500,
                "days_to_expiry": 30,
            },
            {
                "strike": 105,
                "expiry": "2024-12-20",
                "option_type": "put",
                "bid": 3.0,
                "ask": 3.5,
                "volume": 80,
                "open_interest": 400,
                "days_to_expiry": 30,
            },
        ]

        results = compute_option_chain_greeks(102.0, 0.05, options_data)

        assert len(results) == 2
        assert results[0]["greeks"]["delta"] > 0  # Call delta > 0
        assert results[1]["greeks"]["delta"] < 0  # Put delta < 0
        assert results[0]["iv"] is not None or results[1]["iv"] is not None
