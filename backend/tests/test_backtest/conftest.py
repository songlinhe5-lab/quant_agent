"""
回测引擎测试共享 fixtures
"""

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")


def _make_ohlc_data(num_days=50, start_price=100.0):
    """生成模拟的 OHLCV 数据"""
    dates = pd.date_range("2024-01-01", periods=num_days, freq="D")
    np.random.seed(42)
    returns = np.random.normal(0.001, 0.02, num_days)
    prices = start_price * np.exp(np.cumsum(returns))

    df = pd.DataFrame(
        {
            "Open": prices * 0.99,
            "High": prices * 1.02,
            "Low": prices * 0.98,
            "Close": prices,
            "Volume": np.random.randint(1000000, 5000000, num_days),
        },
        index=dates,
    )
    return df


@pytest.fixture
def ohlc_data():
    """50 天 OHLCV 数据"""
    return _make_ohlc_data(50)


@pytest.fixture
def ohlc_data_100():
    """100 天 OHLCV 数据"""
    return _make_ohlc_data(100)


@pytest.fixture
def mock_dataframe():
    """20 天确定性 OHLCV 数据（用于事件驱动引擎精确断言）"""
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    prices = [100.0 + i for i in range(19)] + [100.0]
    df = pd.DataFrame(
        {
            "Open": prices,
            "High": [p + 2.0 for p in prices],
            "Low": [p - 2.0 for p in prices],
            "Close": prices,
            "Volume": [1000] * 20,
        },
        index=dates,
    )
    return df
