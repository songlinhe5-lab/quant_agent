"""AI-03 (回测工坊·报告解读员) 数据契约。

吃真实回测指标，产出一句话解读；并提供纯计算的过拟合检测。
全部字段严格对应 docs/AI_01_09_PLAN.md 的接口契约，零幻觉。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class InterpretRequest(BaseModel):
    """吃回测结果，生成一句话解读。"""

    symbol: Optional[str] = None
    annual_return: float = Field(..., description="年化收益率，如 0.23 表示 23%")
    sharpe: float = Field(..., description="夏普比率")
    mdd: float = Field(..., description="最大回撤(绝对值展示，如 0.18)，允许负值输入")
    leverage: float = Field(1.0, description="杠杆倍数；>1 表示存在杠杆放大")


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
