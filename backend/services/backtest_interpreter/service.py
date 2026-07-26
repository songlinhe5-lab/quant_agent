"""AI-03: 回测工坊·报告解读员

- interpret(): 吃真实回测指标 → LLM(FLAGSHIP) 生成 ≤80 字摘要，必须显式判别
  "收益是否来自杠杆而非 Alpha"。
- check_overfit(): 纯计算，扫描参数敏感性，差异 > 阈值触发过拟合预警。

设计红线（AGENTS.md 零幻觉）：
- 绝不编造未提供的数字；LLM 失败或返回异常时降级为原始指标摘要。
- 过拟合检测为确定性计算，不依赖任何外部模型。
"""

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.services.backtest_interpreter.models import (
    InterpretRequest,
    InterpretResult,
    OverfitCheckResult,
    ParamSweep,
)
from backend.services.llm_service import LLMService, ModelTier

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是 Quant Agent 主脑麾下的回测报告解读员，毒舌、硬核、满嘴华尔街黑话。"
    "你只能基于用户提供的【回测真实指标】(年化收益 / 夏普 / 最大回撤 / 杠杆倍数)"
    "做一句话解读，字数严格 ≤80。你必须明确判别：该收益是否主要来源于杠杆放大而非策略"
    "Alpha——若杠杆倍数显著大于 1 且夏普偏低，应直指'收益靠杠杆堆出来，Alpha 稀薄'；"
    "若杠杆≈1 且夏普可观，应肯定'Alpha 驱动'。严禁编造任何未提供的数字或指标。"
    "若指标缺失或异常，直接说'数据不足以下结论'。"
)

_PROMPT_TMPL = """请基于以下【回测真实指标】给出一句话解读（≤80字，须含杠杆/Alpha 判别）。

标的: {symbol}
年化收益: {annual_return_pct}
夏普比率: {sharpe}
最大回撤: {mdd_pct}
杠杆倍数: {leverage}x
"""


class _LlmInterpret(BaseModel):
    """LLM 结构化输出契约。"""

    summary: str = Field(description="≤80字中文回测解读，须含杠杆/Alpha判别")
    confidence: float = Field(description="解读置信度 0-1", ge=0.0, le=1.0)


def _format_prompt(req: InterpretRequest) -> str:
    return _PROMPT_TMPL.format(
        symbol=req.symbol or "未指定",
        annual_return_pct=f"{req.annual_return * 100:.1f}%",
        sharpe=req.sharpe,
        mdd_pct=f"{abs(req.mdd) * 100:.1f}%",
        leverage=req.leverage,
    )


def check_overfit(param_sweep: List[ParamSweep], threshold: float = 0.40) -> OverfitCheckResult:
    """纯计算：参数敏感性 = (max - min) / max，超阈值即判过拟合。

    例: sharpe=[1.6,0.9,1.5] -> 敏感性 (1.6-0.9)/1.6 = 0.4375 -> 0.44 > 0.40 -> 过拟合。
    """
    max_sens = 0.0
    for ps in param_sweep:
        vals = ps.sharpe
        if len(vals) >= 2:
            mx, mn = max(vals), min(vals)
            sens = (mx - mn) / mx if mx > 0 else 0.0
            max_sens = max(max_sens, sens)
    max_sens = round(max_sens, 2)
    return OverfitCheckResult(
        overfit=max_sens > threshold,
        max_sensitivity=max_sens,
        threshold=threshold,
    )


def param_sweep_from_grid_results(results: List[dict], target_metric: str = "sharpe") -> List[ParamSweep]:
    """从真实网格搜索 results 派生每参数的边际敏感性序列。

    对每个参数，取其各取值下的最优指标（max，跨其余维度边际化），
    得到一条 1D 敏感性序列供 check_overfit 使用。

    兼容两种结果形态：
    - 后端 grid_search: {params:{...}, sharpe: 1.2}
    - 前端 custom-indicator: {params:{...}, metrics:{sharpe: 1.2}}
    """
    norm: list = []
    for r in results:
        if not isinstance(r, dict):
            continue
        params = r.get("params") or {}
        if not isinstance(params, dict):
            continue
        val = r.get(target_metric)
        if val is None:
            m = r.get("metrics") or {}
            val = m.get(target_metric) if isinstance(m, dict) else None
        if val is None:
            continue
        try:
            norm.append((params, float(val)))
        except (TypeError, ValueError):
            continue
    if not norm:
        return []

    param_keys = list(norm[0][0].keys())
    sweeps: List[ParamSweep] = []
    for k in param_keys:
        best: dict = {}
        for p, v in norm:
            pk = p.get(k)
            if pk is None:
                continue
            if pk not in best or v > best[pk]:
                best[pk] = v
        if len(best) < 2:
            continue
        sweeps.append(ParamSweep(param=str(k), sharpe=list(best.values())))
    return sweeps


class BacktestInterpreterService:
    def __init__(self, llm: Optional[LLMService] = None):
        self.llm = llm or LLMService()

    async def interpret(self, req: InterpretRequest) -> InterpretResult:
        prompt = _format_prompt(req)
        try:
            out = await self.llm.generate_pydantic(
                prompt,
                response_model=_LlmInterpret,
                system_prompt=SYSTEM_PROMPT,
                tier=ModelTier.FLAGSHIP,
            )
            if out is None:
                raise RuntimeError("LLM 返回空")
            summary = (out.summary or "").strip()
            if len(summary) < 5:
                raise ValueError("LLM 返回过短")
            return InterpretResult(
                summary=summary,
                source="llm",
                confidence=min(1.0, max(0.0, float(out.confidence))),
            )
        except Exception as e:
            logger.error(f"[BacktestInterpreter] LLM 解读失败，降级: {e}")
            return InterpretResult(
                summary=(
                    f"年化{req.annual_return * 100:.0f}%、夏普{req.sharpe}、"
                    f"杠杆{req.leverage}x——数据不足以下结论，拒绝在真空里解读"
                ),
                source="fallback",
                confidence=0.3,
            )
