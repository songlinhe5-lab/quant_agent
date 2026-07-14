"""
阶段 4 · Alpha158 因子库测试

纯 pandas 因子计算正确性
"""

import numpy as np
import pandas as pd
import pytest

from backend.services.alpha158 import (
    FACTOR_REGISTRY,
    Alpha158,
    compute_all_factors,
    compute_factor,
    list_factors,
)


@pytest.fixture
def sample_ohlcv():
    """生成标准 OHLCV 测试数据 (100 根 K 线)"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + abs(np.random.randn(n) * 0.5)
    low = close - abs(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    }, index=dates)


# ===== 动量类 =====


def test_roc_calculation(sample_ohlcv):
    """测试 ROC 计算正确性"""
    result = Alpha158.roc(sample_ohlcv, period=10)
    assert len(result) == len(sample_ohlcv)
    # 前 10 个应该是 NaN
    assert result.iloc[:10].isna().all()
    # 第 11 个应该有值
    assert not np.isnan(result.iloc[10])
    # ROC = (close[t] - close[t-10]) / close[t-10]
    expected = (sample_ohlcv["close"].iloc[10] - sample_ohlcv["close"].iloc[0]) / sample_ohlcv["close"].iloc[0]
    assert abs(result.iloc[10] - expected) < 1e-10


def test_rsi_range(sample_ohlcv):
    """测试 RSI 值域 [0, 100]"""
    result = Alpha158.rsi(sample_ohlcv, period=14)
    valid = result.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_rsi_oversold_overbought():
    """测试 RSI 超卖超买信号"""
    # 构造持续下跌数据 (需要足够长以满足 min_periods)
    n = 100
    falling_close = pd.Series(200 - np.arange(n) * 1.0)
    df = pd.DataFrame({"close": falling_close, "high": falling_close + 1, "low": falling_close - 1, "volume": np.ones(n) * 1000})
    rsi = Alpha158.rsi(df, period=14)
    # 持续下跌后 RSI 应该很低
    assert rsi.dropna().iloc[-1] < 30

    # 构造持续上涨数据
    rising_close = pd.Series(100 + np.arange(n) * 1.0)
    df2 = pd.DataFrame({"close": rising_close, "high": rising_close + 1, "low": rising_close - 1, "volume": np.ones(n) * 1000})
    rsi2 = Alpha158.rsi(df2, period=14)
    # 持续上涨后 RSI 应该很高
    assert rsi2.dropna().iloc[-1] > 70


def test_kdj_kd_range(sample_ohlcv):
    """测试 KDJ K/D 值合理性"""
    k = Alpha158.kdj_k(sample_ohlcv)
    d = Alpha158.kdj_d(sample_ohlcv)
    valid_k = k.dropna()
    valid_d = d.dropna()
    # K/D 值通常在 0-100 范围
    assert (valid_k >= -10).all() and (valid_k <= 110).all()
    assert (valid_d >= -10).all() and (valid_d <= 110).all()


# ===== 波动率类 =====


def test_std_positive(sample_ohlcv):
    """测试标准差为正值"""
    result = Alpha158.std(sample_ohlcv, period=20)
    valid = result.dropna()
    assert (valid >= 0).all()


def test_atr_positive(sample_ohlcv):
    """测试 ATR 为正值"""
    result = Alpha158.atr(sample_ohlcv, period=14)
    valid = result.dropna()
    assert (valid > 0).all()


def test_boll_width_positive(sample_ohlcv):
    """测试布林带宽度为正值"""
    result = Alpha158.boll_width(sample_ohlcv)
    valid = result.dropna()
    assert (valid >= 0).all()


# ===== 量价类 =====


def test_obv_direction(sample_ohlcv):
    """测试 OBV 方向性"""
    result = Alpha158.obv(sample_ohlcv)
    assert len(result) == len(sample_ohlcv)
    # OBV 第一个值为 NaN (diff 产生)，其余应该有值
    valid = result.dropna()
    assert len(valid) >= len(sample_ohlcv) - 1


def test_volume_ratio(sample_ohlcv):
    """测试量比计算"""
    result = Alpha158.volume_ratio(sample_ohlcv, period=5)
    valid = result.dropna()
    # 量比应该 > 0
    assert (valid > 0).all()
    # 均值应该接近 1.0
    assert abs(valid.mean() - 1.0) < 0.5


# ===== 均线类 =====


def test_sma_calculation(sample_ohlcv):
    """测试 SMA 计算正确性"""
    result = Alpha158.sma(sample_ohlcv, period=5)
    # 手动计算第 5 个值的 SMA
    expected = sample_ohlcv["close"].iloc[:5].mean()
    assert abs(result.iloc[4] - expected) < 1e-10


def test_ema_calculation(sample_ohlcv):
    """测试 EMA 计算"""
    result = Alpha158.ema(sample_ohlcv, period=20)
    valid = result.dropna()
    assert len(valid) > 0
    # EMA 应该比 SMA 对近期价格更敏感
    sma = Alpha158.sma(sample_ohlcv, period=20)
    # 在趋势数据中，EMA 和 SMA 应该有差异
    diff = (result - sma).dropna()
    assert len(diff) > 0


def test_macd_components(sample_ohlcv):
    """测试 MACD 组件"""
    dif = Alpha158.macd_dif(sample_ohlcv)
    dea = Alpha158.macd_dea(sample_ohlcv)
    hist = Alpha158.macd_hist(sample_ohlcv)

    # MACD histogram = 2 * (DIF - DEA)
    valid_idx = dif.dropna().index.intersection(dea.dropna().index)
    for idx in valid_idx[-5:]:
        expected_hist = 2 * (dif.loc[idx] - dea.loc[idx])
        assert abs(hist.loc[idx] - expected_hist) < 1e-10


# ===== 统计类 =====


def test_skewness(sample_ohlcv):
    """测试偏度计算"""
    result = Alpha158.skewness(sample_ohlcv, period=20)
    valid = result.dropna()
    assert len(valid) > 0
    # 偏度通常在 -3 到 +3 之间
    assert (valid.abs() < 10).all()


def test_kurtosis(sample_ohlcv):
    """测试峰度计算"""
    result = Alpha158.kurtosis(sample_ohlcv, period=20)
    valid = result.dropna()
    assert len(valid) > 0


# ===== 因子注册表 =====


def test_factor_registry_completeness():
    """测试因子注册表完整性"""
    assert len(FACTOR_REGISTRY) >= 35  # 至少 35 个因子
    # 每个因子都有 (func, params, category) 格式
    for name, (func, params, cat) in FACTOR_REGISTRY.items():
        assert callable(func), f"{name} func not callable"
        assert isinstance(params, dict), f"{name} params not dict"
        assert isinstance(cat, str), f"{name} category not str"


def test_factor_categories():
    """测试因子分类覆盖"""
    categories = {cat for _, (_, _, cat) in FACTOR_REGISTRY.items()}
    assert "momentum" in categories
    assert "volatility" in categories
    assert "volume_price" in categories
    assert "moving_avg" in categories
    assert "statistics" in categories


# ===== compute_factor / compute_all_factors / list_factors =====


def test_compute_factor_valid(sample_ohlcv):
    """测试 compute_factor 有效因子名"""
    result = compute_factor(sample_ohlcv, "rsi_14")
    assert result is not None
    assert len(result) == len(sample_ohlcv)


def test_compute_factor_invalid(sample_ohlcv):
    """测试 compute_factor 无效因子名"""
    result = compute_factor(sample_ohlcv, "nonexistent_factor")
    assert result is None


def test_compute_all_factors(sample_ohlcv):
    """测试全量因子计算"""
    result = compute_all_factors(sample_ohlcv)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == len(sample_ohlcv)
    assert len(result.columns) >= 35  # 至少 35 列


def test_list_factors():
    """测试列出因子"""
    factors = list_factors()
    assert len(factors) >= 35
    assert all("name" in f for f in factors)
    assert all("category" in f for f in factors)


# ===== 边界情况 =====


def test_missing_columns():
    """测试缺失列时的安全处理"""
    df = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
    # 没有 high/low/volume 列，应该不崩溃
    result = Alpha158.sma(df, period=3)
    assert len(result) == 5
    assert not result.iloc[2:].isna().any()


def test_empty_dataframe():
    """测试空 DataFrame"""
    df = pd.DataFrame({"close": [], "high": [], "low": [], "volume": []})
    result = Alpha158.sma(df, period=5)
    assert len(result) == 0
