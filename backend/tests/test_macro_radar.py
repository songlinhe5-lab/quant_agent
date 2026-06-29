"""
宏观雷达聚合服务单元测试
覆盖: backend/services/macro_radar.py
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


from backend.services.macro_radar import MacroRadarEngine, macro_radar_engine


class TestMacroRadarEngine:
    """MacroRadarEngine 单元测试"""

    @pytest.fixture
    def engine(self):
        return MacroRadarEngine()

    def test_calculate_adaptive_score_insufficient_data_returns_neutral(self, engine):
        """数据不足时应返回中性分 50"""
        assert engine.calculate_adaptive_score(1.0, None) == 50.0
        assert engine.calculate_adaptive_score(1.0, pd.Series(dtype=float)) == 50.0
        short = pd.Series([1.0])
        assert engine.calculate_adaptive_score(1.0, short) == 50.0

    def test_calculate_adaptive_score_normal_returns_value_in_range(self, engine):
        """正常输入应映射到 (0, 100)"""
        history = pd.Series(np.linspace(100, 110, 30))
        score = engine.calculate_adaptive_score(2.0, history)
        assert 0 < score < 100
        assert isinstance(score, float)

    def test_calculate_adaptive_score_inverse_flips_score(self, engine):
        """逆向指标：相同变动方向应产生相反的分数方向"""
        history = pd.Series(np.linspace(100, 110, 30))
        positive = engine.calculate_adaptive_score(2.0, history, inverse=False)
        inverse = engine.calculate_adaptive_score(2.0, history, inverse=True)
        assert positive > 50
        assert inverse < 50
        assert abs((positive - 50) - (50 - inverse)) < 5.0

    def test_calculate_adaptive_score_zero_volatility_floor(self, engine):
        """死水资产波动率为 0 时应使用 0.5 的兜底波动率"""
        constant = pd.Series([100.0] * 20)
        score = engine.calculate_adaptive_score(0.0, constant)
        # 0 变动 + 兜底波动率 → Z=0 → Sigmoid=0.5 → 50
        assert score == 50.0

    def test_calculate_spread_score_insufficient_data_returns_neutral(self, engine):
        """利差数据不足应返回中性分"""
        assert engine.calculate_spread_score(0.5, None) == 50.0
        assert engine.calculate_spread_score(0.5, pd.Series(dtype=float)) == 50.0

    def test_calculate_spread_score_normal_calculates(self, engine):
        """利差正常计算应映射到 (0, 100)"""
        history = pd.Series(np.linspace(1.0, 2.0, 30))
        score = engine.calculate_spread_score(0.02, history)
        assert 0 < score <= 100
        assert isinstance(score, float)

    def test_calculate_spread_score_inverse(self, engine):
        """利差逆向指标应反向"""
        history = pd.Series(np.linspace(1.0, 2.0, 30))
        normal = engine.calculate_spread_score(0.02, history, inverse=False)
        inverse = engine.calculate_spread_score(0.02, history, inverse=True)
        assert normal > 50
        assert inverse < 50

    async def test_fetch_historical_data_success(self, engine):
        """yfinance 返回正常 DataFrame 时应提取 Close 列"""
        mock_data = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0], "Open": [99.0, 100.0, 101.0]}
        )
        with patch("backend.services.macro_radar.yf.download", return_value=mock_data):
            result = await engine.fetch_historical_data("AAPL", period="5d")
        assert isinstance(result, pd.Series)
        assert len(result) == 3
        assert list(result) == [100.0, 101.0, 102.0]

    async def test_fetch_historical_data_multiindex(self, engine):
        """yfinance 返回 MultiIndex 列时应正确解包"""
        arrays = [("Close", "AAPL"), ("Open", "AAPL")]
        mock_data = pd.DataFrame(
            {arrays[0]: [100.0, 101.0], arrays[1]: [99.0, 100.0]}
        )
        with patch("backend.services.macro_radar.yf.download", return_value=mock_data):
            result = await engine.fetch_historical_data("AAPL")
        assert len(result) == 2
        assert list(result) == [100.0, 101.0]

    async def test_fetch_historical_data_exception_returns_empty(self, engine):
        """yfinance 抛异常时应返回空 Series"""
        with patch("backend.services.macro_radar.yf.download", side_effect=RuntimeError("network")):
            result = await engine.fetch_historical_data("BAD")
        assert isinstance(result, pd.Series)
        assert result.empty

    async def test_fetch_fred_data_success(self, engine):
        """FRED 服务返回成功时应解析为时间序列"""
        # FRED 默认 DESC（最新在前），传 [1.6, 1.5]，翻转后应为 [1.5, 1.6]
        fred_response = {
            "status": "success",
            "data": [
                {"date": "2024-01-02", "value": "1.6"},
                {"date": "2024-01-01", "value": "1.5"},
            ],
        }
        with patch("backend.services.macro_radar.fred_service.get_series_observations", new=AsyncMock(return_value=fred_response)):
            result = await engine.fetch_fred_data("DGS10", limit=10)
        assert len(result) == 2
        # 翻转为正序，最早的应在前面
        assert float(result.iloc[0]) == 1.5
        assert float(result.iloc[1]) == 1.6

    async def test_fetch_fred_data_failure_returns_empty(self, engine):
        """FRED 服务失败或异常时应返回空 Series"""
        with patch("backend.services.macro_radar.fred_service.get_series_observations", new=AsyncMock(return_value={"status": "error"})):
            result = await engine.fetch_fred_data("DGS10")
        assert result.empty

        with patch("backend.services.macro_radar.fred_service.get_series_observations", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await engine.fetch_fred_data("DGS10")
        assert result.empty

    async def test_fetch_fred_data_skip_none_values(self, engine):
        """FRED 返回值中 None 应被跳过"""
        # DESC（最新在前）：[None, 2.0] → 翻转后 [2.0, None] → 过滤后只剩 [2.0]
        fred_response = {
            "status": "success",
            "data": [
                {"date": "2024-01-02", "value": None},
                {"date": "2024-01-01", "value": "2.0"},
            ],
        }
        with patch("backend.services.macro_radar.fred_service.get_series_observations", new=AsyncMock(return_value=fred_response)):
            result = await engine.fetch_fred_data("DGS10")
        assert len(result) == 1
        assert float(result.iloc[0]) == 2.0

    async def test_generate_radar_data_returns_six_axes(self, engine):
        """生成雷达数据应返回 6 个象限的标准结构"""
        async def fake_fetch_yf(ticker, period="60d"):
            return pd.Series(np.linspace(100, 110, 30))

        async def fake_fetch_fred(series_id, limit=60):
            return pd.Series(np.linspace(1.0, 2.0, 30))

        with (
            patch.object(engine, "fetch_historical_data", side_effect=fake_fetch_yf),
            patch.object(engine, "fetch_fred_data", side_effect=fake_fetch_fred),
        ):
            result = await engine.generate_radar_data()

        assert isinstance(result, list)
        assert len(result) == 6
        axes = [item["axis"] for item in result]
        assert axes == ["流动性", "波动率", "权益", "商品", "债券", "汇率"]
        for item in result:
            assert "current" in item
            assert "benchmark" in item
            assert 0 <= item["current"] <= 100

    async def test_generate_radar_data_handles_exceptions(self, engine):
        """所有数据源异常时应使用兜底 0.0 变化量生成中性分数"""
        async def failing(*args, **kwargs):
            raise RuntimeError("network down")

        with (
            patch.object(engine, "fetch_historical_data", side_effect=failing),
            patch.object(engine, "fetch_fred_data", side_effect=failing),
        ):
            result = await engine.generate_radar_data()

        assert len(result) == 6
        # 异常时变化量兜底为 0，分数应接近 50
        for item in result:
            assert 40 <= item["current"] <= 60

    def test_global_singleton_exists(self):
        """全局单例 macro_radar_engine 应可正常导入并具备 TICKERS 映射"""
        assert hasattr(macro_radar_engine, "TICKERS")
        assert "VIX" in macro_radar_engine.TICKERS
        assert macro_radar_engine.TICKERS["VIX"] == "^VIX"
