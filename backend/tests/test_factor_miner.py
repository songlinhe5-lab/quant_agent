"""
阶段 4 · AI 驱动因子挖掘测试

mock LLM, 测试 grid search 集成
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.factor_miner import (
    FactorMiner,
    FactorSuggestion,
    FactorSearchResult,
    factor_miner,
)


@pytest.fixture
def sample_kline():
    """生成模拟 K 线数据"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + abs(np.random.randn(n) * 0.5),
        "low": close - abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    }, index=dates)


# ===== suggest_factors =====


@pytest.mark.asyncio
async def test_suggest_factors_success():
    """测试 LLM 因子建议成功路径"""
    mock_response = MagicMock()
    mock_response.factors = [
        {
            "name": "rsi_reversal",
            "expression": "RSI(14) < 30",
            "param_range": {"period": [6, 14, 21]},
            "rationale": "RSI 超卖反转信号",
        },
        {
            "name": "macd_cross",
            "expression": "MACD(12,26,9) golden cross",
            "param_range": {"fast": [8, 12], "slow": [21, 26]},
            "rationale": "MACD 金叉因子",
        },
    ]

    with patch(
        "backend.services.factor_miner.llm_service"
    ) as mock_llm:
        mock_llm.generate_pydantic = AsyncMock(return_value=mock_response)
        miner = FactorMiner()
        suggestions = await miner.suggest_factors("AAPL", "maximize_sharpe")

    assert len(suggestions) == 2
    assert suggestions[0].name == "rsi_reversal"
    assert suggestions[0].param_range == {"period": [6, 14, 21]}
    assert suggestions[1].name == "macd_cross"


@pytest.mark.asyncio
async def test_suggest_factors_llm_failure_fallback():
    """测试 LLM 失败时返回默认因子"""
    with patch(
        "backend.services.factor_miner.llm_service"
    ) as mock_llm:
        mock_llm.generate_pydantic = AsyncMock(side_effect=Exception("LLM error"))
        miner = FactorMiner()
        suggestions = await miner.suggest_factors("AAPL")

    assert len(suggestions) == 1
    assert suggestions[0].name == "sma_cross"
    assert "经典" in suggestions[0].rationale


# ===== grid_search_factors =====


@pytest.mark.asyncio
async def test_grid_search_factors():
    """测试因子参数网格搜索"""
    factors = [
        FactorSuggestion(
            name="sma_cross",
            expression="SMA(fast) > SMA(slow)",
            param_range={"fast": [5, 10, 20], "slow": [20, 50, 60]},
            rationale="均线交叉",
        ),
    ]

    miner = FactorMiner()
    results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 1
    assert results[0].factor_name == "sma_cross"
    assert results[0].total_combos == 9  # 3 * 3
    assert len(results[0].top_results) == 9  # min(9, 10)
    assert results[0].best_sharpe > 0
    assert results[0].best_params["fast"] in [5, 10, 20]


@pytest.mark.asyncio
async def test_grid_search_empty_params():
    """测试空参数范围时返回 None"""
    factors = [
        FactorSuggestion(
            name="empty_factor",
            expression="const",
            param_range={},
            rationale="无参数",
        ),
    ]

    miner = FactorMiner()
    results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 0


@pytest.mark.asyncio
async def test_grid_search_max_combos_limit():
    """测试组合数上限 256"""
    factors = [
        FactorSuggestion(
            name="big_search",
            expression="test",
            param_range={"a": list(range(20)), "b": list(range(20)), "c": list(range(20))},
            rationale="大搜索空间",
        ),
    ]

    miner = FactorMiner()
    results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 1
    assert results[0].total_combos == 256  # 被截断


# ===== FactorSearchResult =====


def test_factor_search_result_dataclass():
    """测试结果数据类"""
    result = FactorSearchResult(
        factor_name="test",
        best_params={"period": 14},
        best_sharpe=1.5,
        best_return=0.12,
        total_combos=10,
        top_results=[{"params": {"period": 14}, "sharpe": 1.5}],
    )
    assert result.factor_name == "test"
    assert result.best_sharpe == 1.5


def test_global_singleton():
    """测试全局单例存在"""
    assert factor_miner is not None
    assert isinstance(factor_miner, FactorMiner)
