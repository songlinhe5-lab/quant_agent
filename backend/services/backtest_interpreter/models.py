"""AI-03 (回测工坊·报告解读员) 数据契约。

吃真实回测指标，产出一句话解读；并提供纯计算的过拟合检测。
全部字段严格对应 docs/AI_01_09_PLAN.md 的接口契约，零幻觉。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InterpretRequest(BaseModel):
    """吃回测结果，生成一句话解读。"""

    symbol: Optional[str] = None
    annual_return: float = Field(..., description="年化收益率，如 0.23 表示 23%")
    sharpe: float = Field(..., description="夏普比率")
    mdd: float = Field(..., description="最大回撤(绝对值展示，如 0.18)，允许负值输入")
    leverage: float = Field(1.0, description="杠杆倍数；>1 表示存在杠杆放大")
    walk_forward: Optional[Dict[str, Any]] = Field(
        None,
        description="可选 Walk-Forward 结论摘要(is_oos_gap/robustness_ratio/overfit_risk/alpha_decay)，"
        "携带则把过拟合/Alpha 衰减信号织入主解读，做单一联合研判",
    )


class InterpretResult(BaseModel):
    summary: str
    source: str = "llm"
    confidence: float = Field(..., ge=0.0, le=1.0)


class ParamSweep(BaseModel):
    """单个参数的敏感性扫描：不同取值下的夏普序列。"""

    param: str
    sharpe: List[float] = Field(..., description="该参数不同取值对应的夏普比率序列")


class OverfitCheckRequest(BaseModel):
    param_sweep: List[ParamSweep]
    threshold: float = Field(0.40, gt=0.0, le=1.0, description="敏感性预警阈值(默认 40%)")


class OverfitCheckResult(BaseModel):
    overfit: bool
    max_sensitivity: float
    threshold: float


class OverfitGridRequest(BaseModel):
    """直接吃网格搜索真实 results，派生参数敏感性后过拟合检测。

    results 每项为 dict，含 params(dict) 与指标：
    - 后端 grid_search: {params:{...}, sharpe: 1.2}
    - 前端 custom-indicator: {params:{...}, metrics:{sharpe: 1.2}}
    """

    results: List[Dict[str, Any]]
    target_metric: str = "sharpe"
    threshold: float = Field(0.40, gt=0.0, le=1.0, description="敏感性预警阈值(默认 40%)")


class WalkForwardInterpretRequest(BaseModel):
    """吃 Walk-Forward 滚动验证报告（即 /walk-forward 返回的 data 负载），

    自动判过拟合（IS/OOS 性能崩塌）+ Alpha 衰减（逐折 OOS 夏普恶化），
    并可选经 LLM 生成 ≤80 字解读。
    """

    report: Dict[str, Any]
    use_llm: bool = True


class WalkForwardInterpretResult(BaseModel):
    is_oos_gap: float = Field(..., description="IS 与 OOS 夏普均值缺口（Alpha 衰减核心指标）")
    alpha_decay: bool = Field(..., description="Alpha 衰减：IS/OOS 缺口过大或已报漂移")
    overfit_risk: bool = Field(..., description="过拟合风险：样本外崩塌且稳健性差")
    robustness_ratio: float = Field(..., description="OOS 盈利折占比（0-1，越高越稳）")
    oos_sharpe_mean: float = Field(..., description="样本外夏普均值")
    is_sharpe_mean: float = Field(..., description="样本内夏普均值")
    drift_reasons: List[str] = Field(default_factory=list)
    summary: str
    source: str = "fallback"
    model: Optional[str] = None
