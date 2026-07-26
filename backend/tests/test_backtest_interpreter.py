"""AI-03 回测报告解读员单元测试

mock LLMService.generate_pydantic，验证：
- 正常：返回 summary + source=llm + confidence
- LLM 抛异常：降级 source=fallback
- LLM 返回 None：降级 source=fallback
- overfit：[1.6,0.9,1.5] -> max_sensitivity 0.44, overfit true
- overfit 低于阈值：overfit false
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.backtest_interpreter.models import (
    InterpretRequest,
    OverfitCheckRequest,
    ParamSweep,
)
from backend.services.backtest_interpreter.service import (
    BacktestInterpreterService,
    check_overfit,
)

FAKE_SUMMARY = "年化23%但Sharpe仅0.9，收益主要来自2.1x杠杆而非Alpha，Alpha稀薄。"


@pytest.mark.asyncio
async def test_interpret_normal():
    llm = MagicMock()
    llm.generate_pydantic = AsyncMock(return_value=MagicMock(summary=FAKE_SUMMARY, confidence=0.82))
    svc = BacktestInterpreterService(llm=llm)
    res = await svc.interpret(
        InterpretRequest(
            symbol="AAPL",
            annual_return=0.23,
            sharpe=0.9,
            mdd=0.18,
            leverage=2.1,
        )
    )
    assert res.summary == FAKE_SUMMARY
    assert res.source == "llm"
    assert res.confidence == 0.82


@pytest.mark.asyncio
async def test_interpret_llm_raises_fallback():
    llm = MagicMock()
    llm.generate_pydantic = AsyncMock(side_effect=RuntimeError("LLM dead"))
    svc = BacktestInterpreterService(llm=llm)
    res = await svc.interpret(InterpretRequest(annual_return=0.23, sharpe=0.9, mdd=0.18, leverage=1.0))
    assert res.source == "fallback"
    assert res.confidence < 0.7


@pytest.mark.asyncio
async def test_interpret_llm_returns_none_fallback():
    llm = MagicMock()
    llm.generate_pydantic = AsyncMock(return_value=None)
    svc = BacktestInterpreterService(llm=llm)
    res = await svc.interpret(InterpretRequest(annual_return=0.23, sharpe=0.9, mdd=0.18, leverage=1.0))
    assert res.source == "fallback"


def test_overfit_check_triggered():
    res = check_overfit([ParamSweep(param="lookback", sharpe=[1.6, 0.9, 1.5])], threshold=0.40)
    assert res.overfit is True
    assert res.max_sensitivity == 0.44
    assert res.threshold == 0.40


def test_overfit_check_below_threshold():
    res = check_overfit([ParamSweep(param="lookback", sharpe=[1.1, 1.0, 1.05])], threshold=0.40)
    assert res.overfit is False
    assert res.max_sensitivity <= 0.40


def test_overfit_check_request_uses_default_threshold():
    req = OverfitCheckRequest(param_sweep=[ParamSweep(param="x", sharpe=[1.6, 0.9, 1.5])])
    assert req.threshold == 0.40
