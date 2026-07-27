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
    WalkForwardInterpretRequest,
    WalkForwardInterpretResult,
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
    prompt = _PROMPT_TMPL.format(
        symbol=req.symbol or "未指定",
        annual_return_pct=f"{req.annual_return * 100:.1f}%",
        sharpe=req.sharpe,
        mdd_pct=f"{abs(req.mdd) * 100:.1f}%",
        leverage=req.leverage,
    )
    wf = req.walk_forward
    if isinstance(wf, dict):
        prompt += (
            "\n\n【Walk-Forward 联合信号】该策略滚动验证结论："
            f"IS/OOS 夏普缺口={wf.get('is_oos_gap')}、"
            f"OOS 盈利折占比={wf.get('robustness_ratio')}、"
            f"过拟合风险={wf.get('overfit_risk')}、Alpha 衰减={wf.get('alpha_decay')}。"
            "请在前述杠杆/Alpha 判别基础上叠加此漂移信号，给出统一联合研判；"
            "若样本外已崩塌，须直指“样本内光鲜、外推必死”。"
        )
    return prompt


def _interpret_fallback(req: InterpretRequest) -> str:
    """LLM 失联时的确定性裸研判（零幻觉）：基于已提供的真实指标做杠杆/Alpha 判别。

    与 SYSTEM_PROMPT 口径一致：杠杆显著>1 且夏普偏低 → 收益靠杠杆堆；
    杠杆≈1 且夏普可观 → Alpha 驱动；其余中性。若携带 walk_forward 结论，
    则融合其过拟合/Alpha 衰减信号做联合研判。绝不编造任何未提供的数字，
    也不得谎称“数据不足”——指标已握在手里。
    """
    lev = req.leverage
    sh = req.sharpe
    ann = req.annual_return * 100
    if lev > 1.3 and sh < 1.0:
        verdict = f"杠杆{lev:.1f}x 堆出{ann:.0f}%年化但夏普仅{sh}，Alpha 稀薄，纯靠借钱放大"
    elif lev <= 1.3 and sh >= 1.0:
        verdict = f"杠杆{lev:.1f}x、夏普{sh}、年化{ann:.0f}%——Alpha 驱动，非杠杆注水"
    else:
        verdict = f"杠杆{lev:.1f}x、夏普{sh}、年化{ann:.0f}%——指标中性"
    wf = req.walk_forward
    if isinstance(wf, dict):
        if wf.get("overfit_risk") or wf.get("alpha_decay"):
            verdict += "；叠加 Walk-Forward 报过拟合/Alpha 衰减，双重确认该策略外推存疑"
        else:
            verdict += "；Walk-Forward 亦稳健，内外部结论一致"
    return f"{verdict}（LLM 失联，以下为确定性裸研判）"


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


_WF_SYSTEM_PROMPT = (
    "你是 Quant Agent 主脑麾下的回测报告解读员，毒舌、硬核、满嘴华尔街黑话。"
    "用户给你的是 Walk-Forward 滚动验证的真实统计：IS/OOS 夏普缺口、样本外盈利折占比、"
    "是否检测到性能漂移。你只做一句话解读（≤80字），必须明确给出'Alpha 衰减'还是'稳健可外推'"
    "的硬核结论。严禁编造任何未提供的数字。"
)

_WF_PROMPT_TMPL = """请基于以下 Walk-Forward 真实统计给出一句话解读（≤80字，须含 Alpha 衰减/稳健结论）。

IS/OOS 夏普缺口: {is_oos_gap}
样本内夏普均值: {is_sharpe_mean}
样本外夏普均值: {oos_sharpe_mean}
样本外盈利折占比: {robustness_ratio}
检测到性能漂移: {drift_detected}
漂移原因: {drift_reasons}
"""


def _analyze_walk_forward_core(report: dict) -> dict:
    """纯计算：从 Walk-Forward 报告派生过拟合/Alpha 衰减判定（零幻觉，不依赖 LLM）。

    兼容 run_walk_forward 返回的 data 负载：summary 含 is_oos_sharpe_gap /
    oos_positive_fold_ratio / oos_sharpe_mean / is_sharpe_mean。
    """
    summary = report.get("summary") or {}
    drift_detected = bool(report.get("drift_detected", False))
    drift_reasons = list(report.get("drift_reasons") or [])

    def _f(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    is_oos_gap = _f(summary.get("is_oos_sharpe_gap"))
    oos_sharpe_mean = _f(summary.get("oos_sharpe_mean"))
    is_sharpe_mean = _f(summary.get("is_sharpe_mean"))
    robustness_ratio = _f(summary.get("oos_positive_fold_ratio"))

    # Alpha 衰减：IS/OOS 缺口过大（>0.5）或引擎已报漂移
    alpha_decay = drift_detected or is_oos_gap > 0.5
    # 过拟合风险：IS 赚钱但 OOS 多数亏损 + 缺口大
    overfit_risk = is_oos_gap > 0.5 or (robustness_ratio < 0.5 and is_sharpe_mean > 0)

    return {
        "is_oos_gap": round(is_oos_gap, 4),
        "alpha_decay": bool(alpha_decay),
        "overfit_risk": bool(overfit_risk),
        "robustness_ratio": round(robustness_ratio, 4),
        "oos_sharpe_mean": round(oos_sharpe_mean, 4),
        "is_sharpe_mean": round(is_sharpe_mean, 4),
        "drift_reasons": drift_reasons,
    }


def _wf_fallback(core: dict) -> str:
    if core["overfit_risk"]:
        return (
            f"IS/OOS 夏普缺口{core['is_oos_gap']}、OOS 盈利折仅"
            f"{core['robustness_ratio'] * 100:.0f}%——典型过拟合，Alpha 已被样本内榨干"
        )
    if core["alpha_decay"]:
        return f"IS/OOS 缺口{core['is_oos_gap']} 已现 Alpha 衰减，外推前先想想参数稳健性"
    return f"IS/OOS 缺口{core['is_oos_gap']}、OOS 盈利折{core['robustness_ratio'] * 100:.0f}%——稳健可外推，Alpha 站得住"


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
                summary=_interpret_fallback(req),
                source="fallback",
                confidence=0.3,
            )

    async def interpret_walk_forward(self, req: WalkForwardInterpretRequest) -> WalkForwardInterpretResult:
        """AI-03 增强：吃 Walk-Forward 报告，自动判过拟合 + Alpha 衰减，可经 LLM 一句话解读。"""
        core = _analyze_walk_forward_core(req.report)

        summary_text = ""
        source = "fallback"
        model = None
        if req.use_llm:
            try:
                prompt = _WF_PROMPT_TMPL.format(
                    is_oos_gap=core["is_oos_gap"],
                    is_sharpe_mean=core["is_sharpe_mean"],
                    oos_sharpe_mean=core["oos_sharpe_mean"],
                    robustness_ratio=core["robustness_ratio"],
                    drift_detected=core["drift_reasons"] or "否",
                    drift_reasons="; ".join(core["drift_reasons"]) or "无",
                )
                out = await self.llm.generate(
                    user_prompt=prompt,
                    system_prompt=_WF_SYSTEM_PROMPT,
                    tier=ModelTier.FLAGSHIP,
                    temperature=0.4,
                )
                if out:
                    summary_text = out[:80]
                    source = "llm"
                    model = self.llm.get_model(ModelTier.FLAGSHIP)
            except Exception as e:
                logger.error(f"[BacktestInterpreter] Walk-Forward LLM 解读失败，降级: {e}")

        if not summary_text:
            summary_text = _wf_fallback(core)

        return WalkForwardInterpretResult(
            is_oos_gap=core["is_oos_gap"],
            alpha_decay=core["alpha_decay"],
            overfit_risk=core["overfit_risk"],
            robustness_ratio=core["robustness_ratio"],
            oos_sharpe_mean=core["oos_sharpe_mean"],
            is_sharpe_mean=core["is_sharpe_mean"],
            drift_reasons=core["drift_reasons"],
            summary=summary_text,
            source=source,
            model=model,
        )
