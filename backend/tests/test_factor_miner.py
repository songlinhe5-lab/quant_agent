"""
阶段 4 · AI 驱动因子挖掘测试

mock LLM, 测试 grid search 集成
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.services.factor_miner import (
    FactorMiner,
    FactorSearchResult,
    FactorSuggestion,
    factor_miner,
)


@pytest.fixture
def sample_kline():
    """生成模拟 K 线数据"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.2,
            "high": close + abs(np.random.randn(n) * 0.5),
            "low": close - abs(np.random.randn(n) * 0.5),
            "close": close,
            "volume": np.random.randint(1000, 10000, n).astype(float),
        },
        index=dates,
    )


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

    with patch("backend.services.factor_miner.llm_service") as mock_llm:
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
    with patch("backend.services.factor_miner.llm_service") as mock_llm:
        mock_llm.generate_pydantic = AsyncMock(side_effect=Exception("LLM error"))
        miner = FactorMiner()
        suggestions = await miner.suggest_factors("AAPL")

    assert len(suggestions) == 1
    assert suggestions[0].name == "sma_cross"
    assert "经典" in suggestions[0].rationale


# ===== grid_search_factors =====


@pytest.mark.asyncio
async def test_grid_search_factors_success_uses_real_backtest():
    """可回测(均线类)因子: 调用真实 run_grid_search 并提取 best(零幻觉, 非 mock 数字)"""
    factors = [
        FactorSuggestion(
            name="sma_cross",
            expression="SMA(period) 穿越",
            param_range={"period": [10, 20, 50]},
            rationale="均线穿越",
        ),
    ]
    fake_resp = {
        "status": "success",
        "data": {
            "best": {"params": {"period": 20}, "sharpe": 1.8, "total_return": 0.25, "ok": True},
            "results": [
                {"params": {"period": 10}, "sharpe": 1.2, "total_return": 0.18, "ok": True},
                {"params": {"period": 20}, "sharpe": 1.8, "total_return": 0.25, "ok": True},
                {"params": {"period": 50}, "sharpe": 1.0, "total_return": 0.12, "ok": True},
            ],
            "n_combos": 3,
        },
    }
    with patch("backend.app.grid_search_app.run_grid_search", new=AsyncMock(return_value=fake_resp)):
        miner = FactorMiner()
        results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].best_sharpe == 1.8
    assert results[0].best_return == 0.25
    assert results[0].best_params == {"period": 20}
    assert results[0].total_combos == 3
    assert len(results[0].top_results) == 3


@pytest.mark.asyncio
async def test_grid_search_non_backtestable_factor_skipped():
    """不可回测因子(非均线类/无参数)诚实标记 skipped, 不捏造数字"""
    factors = [
        FactorSuggestion(
            name="rsi_reversal",
            expression="RSI(14) < 30",
            param_range={"period": [6, 14, 21]},
            rationale="RSI 超卖反转",
        ),
        FactorSuggestion(
            name="empty_factor",
            expression="const",
            param_range={},
            rationale="无参数因子",
        ),
    ]

    miner = FactorMiner()
    results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 2
    assert all(r.status == "skipped" for r in results)
    assert results[0].best_sharpe is None
    assert results[0].best_return is None
    assert "策略" in (results[0].skipped_reason or "")


@pytest.mark.asyncio
async def test_grid_search_backtest_failure_skipped():
    """回测执行失败(数据源不可用)时诚实降级为 skipped, 不抛异常"""
    factors = [
        FactorSuggestion(
            name="sma_cross",
            expression="SMA(period) 穿越",
            param_range={"period": [10, 20]},
            rationale="均线穿越",
        ),
    ]
    with patch(
        "backend.app.grid_search_app.run_grid_search",
        new=AsyncMock(side_effect=Exception("no data source")),
    ):
        miner = FactorMiner()
        results = await miner.grid_search_factors("AAPL", factors)

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "回测执行失败" in (results[0].skipped_reason or "")


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
