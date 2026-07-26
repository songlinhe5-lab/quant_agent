"""AI-01 异动解说员数据模型"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class NarrativeRequest(BaseModel):
    """前端异动触发时上报的请求体"""

    symbol: str
    change_pct: float
    direction: Literal["up", "down"] = "up"
    threshold: float = 2.0


class NarrativeResult(BaseModel):
    """数据驱动的一句话解说结果"""

    symbol: str
    direction: str
    change_pct: float
    threshold: float
    summary: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0, description="解说置信度 0~1")
    triggered_by: str = "price_anomaly"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
