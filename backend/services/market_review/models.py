"""
MRKT-01: 宏观市场复盘数据模型

核心实体:
- MarketDailyReview: 每日市场复盘报告（按市场维度）
- IndexSnapshot: 大盘指数快照
- SectorPerformance: 板块表现
- MarketEvent: 关联事件
- CapitalFlow: 资金面数据
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    """支持的市场类型"""

    A_SHARE = "A股"
    HK = "港股"
    US = "美股"


class MarketStyle(str, Enum):
    """市场风格定性"""

    LARGE_VALUE = "大盘价值"
    LARGE_GROWTH = "大盘成长"
    SMALL_VALUE = "小盘价值"
    SMALL_GROWTH = "小盘成长"
    BALANCED = "均衡轮动"
    DEFENSIVE = "防御避险"
    SPECULATIVE = "投机炒作"


class SentimentLevel(str, Enum):
    """情绪面等级"""

    EXTREME_FEAR = "极度恐惧"
    FEAR = "恐惧"
    NEUTRAL = "中性"
    GREED = "贪婪"
    EXTREME_GREED = "极度贪婪"


class IndexSnapshot(BaseModel):
    """大盘指数快照"""

    name: str = Field(description="指数名称，如上证指数、恒生指数、道琼斯")
    code: str = Field(description="指数代码，如 000001.SH、HSI、DJI")
    close: float = Field(description="收盘价")
    change_pct: float = Field(description="涨跌幅(%)")
    volume: Optional[float] = Field(default=None, description="成交额(亿)")
    amplitude: Optional[float] = Field(default=None, description="振幅(%)")


class SectorPerformance(BaseModel):
    """板块表现"""

    name: str = Field(description="板块名称")
    change_pct: float = Field(description="涨跌幅(%)")
    net_inflow: Optional[float] = Field(default=None, description="主力净流入(亿)")
    leading_stock: Optional[str] = Field(default=None, description="领涨/领跌股")
    direction: str = Field(default="涨", description="方向: 涨/跌")


class CapitalFlow(BaseModel):
    """资金面数据"""

    main_net_inflow: Optional[float] = Field(default=None, description="主力净流入(亿)")
    northbound_net: Optional[float] = Field(default=None, description="北向资金净流入(亿)，仅A股")
    sector_inflow_top: list[str] = Field(default_factory=list, description="资金流入前5板块")
    sector_outflow_top: list[str] = Field(default_factory=list, description="资金流出前5板块")
    conclusion: str = Field(default="", description="资金面结论，如'外资主导买入科技'")


class MarketEvent(BaseModel):
    """关联事件"""

    title: str = Field(description="事件标题")
    category: str = Field(default="宏观", description="分类: 宏观/政策/数据/地缘/行业")
    impact: str = Field(default="中性", description="影响判断: 利好/利空/中性")
    affected_sectors: list[str] = Field(default_factory=list, description="受影响板块")
    source: Optional[str] = Field(default=None, description="来源")


class MarketDailyReview(BaseModel):
    """每日市场复盘报告（核心实体）"""

    # ── 元数据 ──
    date: str = Field(description="复盘日期 YYYY-MM-DD")
    market: MarketType = Field(description="市场类型")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")

    # ── 大盘概况 ──
    indices: list[IndexSnapshot] = Field(default_factory=list, description="主要指数快照")

    # ── 市场风格 ──
    style: Optional[MarketStyle] = Field(default=None, description="市场风格定性")
    style_reasoning: str = Field(default="", description="风格判定依据")

    # ── 资金面 ──
    capital_flow: Optional[CapitalFlow] = Field(default=None, description="资金面数据")

    # ── 板块表现 ──
    sectors_top: list[SectorPerformance] = Field(default_factory=list, description="涨幅前5板块")
    sectors_bottom: list[SectorPerformance] = Field(default_factory=list, description="跌幅前5板块")

    # ── 关联事件 ──
    key_events: list[MarketEvent] = Field(default_factory=list, description="当日重大事件")
    event_impact_summary: str = Field(default="", description="事件对市场综合影响")

    # ── 情绪面 ──
    sentiment_score: Optional[int] = Field(default=None, ge=0, le=100, description="情绪评分 0(恐惧)~100(贪婪)")
    sentiment_level: Optional[SentimentLevel] = Field(default=None, description="情绪等级")
    breadth: Optional[str] = Field(default=None, description="涨跌比，如 '3200:1500'")
    limit_up_count: Optional[int] = Field(default=None, description="涨停数(A股)")
    limit_down_count: Optional[int] = Field(default=None, description="跌停数(A股)")

    # ── AI 总结 ──
    summary: str = Field(default="", description="3-5句话概括当日市场")
    outlook: str = Field(default="", description="次日/短期展望")

    # ── 判因标签（供下游引用） ──
    risk_tags: list[str] = Field(default_factory=list, description="风险标签，如['系统性回调','板块轮动']")

    def redis_key(self) -> str:
        """Redis 存储键: quant:market_review:{market}:{date}"""
        return f"quant:market_review:{self.market.value}:{self.date}"
