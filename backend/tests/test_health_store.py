"""AI-03: 回测健康度持久化层单测

mock Redis 降级为内存兜底，验证 save/get/get_all 行为正确，
并确认内存单例与 Redis 读取两条路径都可返回结构化结论。
"""

from unittest.mock import patch

import pytest

from backend.services.backtest_interpreter.health_store import (
    BacktestHealthEntry,
    get_all_backtest_health,
    get_backtest_health,
    save_backtest_health,
)
from backend.services.backtest_interpreter.models import WalkForwardInterpretResult


@pytest.fixture
def _no_redis():
    """屏蔽 Redis，强制走内存兜底；并隔离模块级内存单例。"""
    import backend.services.backtest_interpreter.health_store as hs

    hs._MEMORY.clear()
    # create=True: get_redis_client 为包内 lazy import，patch 时属性尚未绑定，需允许创建
    with patch("backend.core.database.get_redis_client", side_effect=RuntimeError("no redis"), create=True):
        yield
    hs._MEMORY.clear()


def _fake_result(ticker="NVDA", overfit=True, alpha_decay=True) -> WalkForwardInterpretResult:
    return WalkForwardInterpretResult(
        is_oos_gap=0.9,
        alpha_decay=alpha_decay,
        overfit_risk=overfit,
        robustness_ratio=0.2,
        oos_sharpe_mean=0.1,
        is_sharpe_mean=1.0,
        drift_reasons=["样本外崩塌"],
        summary="样本内光鲜外推必死",
        source="llm",
        model="gpt-x",
    )


@pytest.mark.asyncio
async def test_save_and_get(_no_redis):
    await save_backtest_health("NVDA", _fake_result())
    got = await get_backtest_health("NVDA")
    assert isinstance(got, BacktestHealthEntry)
    assert got.ticker == "NVDA"
    assert got.overfit_risk is True
    assert got.alpha_decay is True
    assert got.summary == "样本内光鲜外推必死"


@pytest.mark.asyncio
async def test_get_all_returns_all_tickers(_no_redis):
    await save_backtest_health("AAA", _fake_result("AAA", overfit=False, alpha_decay=False))
    await save_backtest_health("BBB", _fake_result("BBB", overfit=True))
    all_ = await get_all_backtest_health()
    assert {e.ticker for e in all_} == {"AAA", "BBB"}


@pytest.mark.asyncio
async def test_get_missing_returns_none(_no_redis):
    assert await get_backtest_health("ZZZ") is None


@pytest.mark.asyncio
async def test_empty_ticker_is_noop(_no_redis):
    await save_backtest_health("", _fake_result())
    assert await get_all_backtest_health() == []
