"""
回测引擎测试共享 fixtures
"""

import pytest

# 💡 注意：环境变量已在 backend/tests/conftest.py 中设置，此处无需重复
# 如果需要在 test_backtest 子目录中使用不同的环境变量，取消下面的注释：
# os.environ["DATABASE_URL"] = "sqlite:///./test_backtest.db"


# 🚀 优化：提前导入 vectorbt，避免每个测试重复初始化（约 2s）
@pytest.fixture(scope="session", autouse=True)
def _preload_vectorbt():
    """Session 级别 fixture：提前初始化 vectorbt，加速后续测试"""
    import vectorbt as vbt  # noqa: F401

    yield


def _make_ohlc_data(num_days=50, start_price=100.0):
    """生成模拟的 OHLCV 数据"""
    import numpy as np
    import pandas as pd

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
    import pandas as pd

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
