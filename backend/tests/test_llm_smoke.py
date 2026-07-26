"""AI-01 / AI-03 真实 LLM 端到端冒烟测试（非 mock）。

保护 CI：默认跳过。仅在显式提供真实凭据时运行：

    LLM_SMOKE_API_KEY=sk-xxx LLM_SMOKE_BASE_URL=https://api.deepseek.com \
    LLM_SMOKE_MODEL=deepseek-chat uv run pytest backend/tests/test_llm_smoke.py -q

覆盖：
- LLMService.generate() 真实返回非空文本（AI-01 异动解说员 / 早报走的通路）
- AI-03 interpret_walk_forward 真实 LLM 路径产出 source="llm" 解读
- AI-03 interpret（回测指标）真实 LLM 路径产出 source="llm" 摘要
"""

import asyncio
import os

import pytest

from backend.services.backtest_interpreter.models import (
    InterpretRequest,
    WalkForwardInterpretRequest,
)
from backend.services.backtest_interpreter.service import BacktestInterpreterService
from backend.services.llm_service import LLMService, ModelTier

_REAL_KEY = os.getenv("LLM_SMOKE_API_KEY")
_REAL_URL = os.getenv("LLM_SMOKE_BASE_URL", "https://api.deepseek.com")
_REAL_MODEL = os.getenv("LLM_SMOKE_MODEL", "deepseek-chat")

pytestmark = pytest.mark.skipif(
    not _REAL_KEY,
    reason="真实 LLM 冒烟测试需要 LLM_SMOKE_API_KEY（默认跳过，保护 CI）",
)


def _real_service() -> LLMService:
    # LLMService.__init__ 在构造时读 env，因此先注入真实凭据再构造。
    os.environ["LLM_API_KEY"] = _REAL_KEY
    os.environ["LLM_BASE_URL"] = _REAL_URL
    os.environ["LLM_MODEL"] = _REAL_MODEL
    os.environ["LLM_PRO_MODEL"] = _REAL_MODEL
    return LLMService()


def test_generate_returns_real_text():
    svc = _real_service()
    out = asyncio.run(
        svc.generate(
            user_prompt="用一句话说明量化策略过拟合的危害",
            system_prompt="你是华尔街量化主脑",
            tier=ModelTier.FLAGSHIP,
        )
    )
    assert out and len(out) > 0, "真实 LLM 应返回非空文本"


def test_ai03_interpret_real_llm():
    svc = BacktestInterpreterService(llm=_real_service())
    res = asyncio.run(
        svc.interpret(InterpretRequest(symbol="AAPL", annual_return=0.23, sharpe=1.4, mdd=0.18, leverage=1.0))
    )
    assert res.source == "llm", f"AI-03 interpret 应走真实 LLM，实际: {res.source}"
    assert len(res.summary) <= 80, "AI-03 摘要应 ≤80 字"


def test_ai03_walk_forward_real_llm():
    svc = BacktestInterpreterService(llm=_real_service())
    report = {
        "summary": {
            "is_oos_sharpe_gap": 0.9,
            "oos_positive_fold_ratio": 0.2,
            "oos_sharpe_mean": 0.8,
            "is_sharpe_mean": 1.7,
        },
        "drift_detected": True,
        "drift_reasons": ["OOS 夏普逐折恶化 slope=-0.20"],
    }
    res = asyncio.run(svc.interpret_walk_forward(WalkForwardInterpretRequest(report=report, use_llm=True)))
    assert res.source == "llm", f"AI-03 walk-forward 应走真实 LLM，实际: {res.source}"
    assert res.overfit_risk is True
