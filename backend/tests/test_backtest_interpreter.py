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
    param_sweep_from_grid_results,
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


def test_param_sweep_from_grid_results_backend_shape():
    results = [
        {"params": {"lookback": 10, "fast": 5}, "sharpe": 1.6, "ok": True},
        {"params": {"lookback": 10, "fast": 10}, "sharpe": 0.9, "ok": True},
        {"params": {"lookback": 20, "fast": 5}, "sharpe": 1.5, "ok": True},
        {"params": {"lookback": 20, "fast": 10}, "sharpe": 1.2, "ok": True},
    ]
    sweeps = param_sweep_from_grid_results(results, "sharpe")
    # lookback: 边际最优 {10:1.6, 20:1.5} -> 差异 (1.6-1.5)/1.6=0.0625
    # fast: 边际最优 {5:1.6, 10:1.2} -> 差异 (1.6-1.2)/1.6=0.25
    by_param = {s.param: s.sharpe for s in sweeps}
    assert "lookback" in by_param and "fast" in by_param
    res = check_overfit(sweeps, 0.40)
    assert res.overfit is False  # 最大敏感度 0.25 < 0.40


def test_param_sweep_from_grid_results_custom_indicator_shape():
    # 前端 custom-indicator: metrics.sharpe
    items = [
        {"params": {"n": 3}, "ok": True, "metrics": {"sharpe": 1.6, "totalReturnPct": 20}},
        {"params": {"n": 5}, "ok": True, "metrics": {"sharpe": 0.9, "totalReturnPct": 10}},
        {"params": {"n": 8}, "ok": True, "metrics": {"sharpe": 1.5, "totalReturnPct": 18}},
    ]
    sweeps = param_sweep_from_grid_results(items, "sharpe")
    assert len(sweeps) == 1
    assert sweeps[0].param == "n"
    # n=3 -> 1.6, n=5 -> 0.9, n=8 -> 1.5 : 敏感性 (1.6-0.9)/1.6 = 0.4375 -> 0.44
    res = check_overfit(sweeps, 0.40)
    assert res.overfit is True
    assert res.max_sensitivity == 0.44


def test_param_sweep_from_grid_results_empty():
    assert param_sweep_from_grid_results([], "sharpe") == []
    assert param_sweep_from_grid_results([{"foo": "bar"}], "sharpe") == []
