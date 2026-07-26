"""BRD-01: 早报刊物数据模型

早报产物是「可直接渲染的 Markdown 字符串」(而非市场复盘那样的结构化对象)，
因为前端要做 Markdown 预览 + 一键复制 + 分享 URL。
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class BriefingResult(BaseModel):
    """一份盘前早报"""

    id: str = Field(..., description="分享用的唯一短码 ID")
    date: str = Field(..., description="早报日期 YYYY-MM-DD")
    market: str = Field("全球", description="市场范围 (A股/港股/美股/全球)")
    markdown: str = Field(..., description="渲染好的早报 Markdown")
    source_tools: List[str] = Field(default_factory=list, description="数据来源工具清单")
    created_at: datetime = Field(default_factory=datetime.now)
