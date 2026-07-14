"""
告警规则与告警事件模型 (ALERT-01/02)
=====================================

定义用户可配置的价格/指标/策略告警规则 Schema，
以及触发后的告警事件记录。

规则类型:
  - price_cross: 价格穿越（上穿/下穿阈值）
  - price_above: 价格高于阈值
  - price_below: 价格低于阈值
  - pct_change: 涨跌幅超阈值
  - volume_surge: 成交量突增

设计文档: docs/01 §十 告警中心
任务编号: ALERT-01
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AlertRuleType(str, Enum):
    """告警规则类型"""

    PRICE_CROSS = "price_cross"      # 价格穿越
    PRICE_ABOVE = "price_above"      # 价格高于
    PRICE_BELOW = "price_below"      # 价格低于
    PCT_CHANGE = "pct_change"        # 涨跌幅
    VOLUME_SURGE = "volume_surge"    # 成交量突增
    # ALERT-05: 技术指标告警
    RSI_THRESHOLD = "rsi_threshold"  # RSI 超买/超卖 (threshold=30 表示 RSI<30 触发, threshold=70 表示 RSI>70 触发)
    MACD_CROSS = "macd_cross"        # MACD 金叉/死叉 (threshold>0 金叉, threshold<0 死叉, 用 metadata.direction 区分)
    MA_CROSS = "ma_cross"            # 均线穿越 (metadata.short_period/metadata.long_period, threshold 无用)
    # PT-02a: 纸面组合漂移告警
    PAPER_DRIFT = "paper_drift"      # 纸面 vs 回测偏离超阈值 (threshold=TE年化阈值, 默认 0.15)


class AlertSeverity(str, Enum):
    """告警严重程度"""

    INFO = "info"          # 信息
    WARNING = "warning"    # 警告
    CRITICAL = "critical"  # 紧急


class AlertStatus(str, Enum):
    """告警状态"""

    ACTIVE = "active"        # 活跃（规则已启用）
    PAUSED = "paused"        # 暂停
    TRIGGERED = "triggered"  # 已触发（冷却中）
    EXPIRED = "expired"      # 已过期


class NotificationPriority(str, Enum):
    """通知优先级（ALERT-03 路由矩阵）"""

    P0 = "p0"   # 紧急：止损/熔断/IP封禁
    P1 = "p1"   # 高：策略信号/配额耗尽/CRITICAL 用户规则
    P2 = "p2"   # 中：委托成交/WARNING 用户规则/限流飙升
    P3 = "p3"   # 低：AI 完成/INFO/选股匹配


class AlertChannel(str, Enum):
    """告警推送通道"""

    IN_APP = "in_app"        # 应用内（WebSocket 推送）
    FEISHU = "feishu"        # 飞书 Webhook
    TELEGRAM = "telegram"    # Telegram Bot


class AlertRule(BaseModel):
    """
    告警规则定义。

    用户通过 API 创建规则，告警引擎根据规则匹配行情数据。
    """

    rule_id: str = Field(..., description="规则唯一 ID")
    user_id: str = Field(default="default", description="用户 ID")
    name: str = Field(..., description="规则名称 (如 'AAPL 突破 200')")
    ticker: str = Field(..., description="标的代码 (如 'AAPL' / 'HK.00700')")
    rule_type: AlertRuleType = Field(..., description="规则类型")
    threshold: float = Field(..., description="阈值")
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING, description="严重程度")
    channels: List[AlertChannel] = Field(
        default_factory=lambda: [AlertChannel.IN_APP],
        description="推送通道列表",
    )
    cooldown_seconds: int = Field(default=300, ge=60, description="触发冷却期 (秒)")
    enabled: bool = Field(default=True, description="是否启用")

    # 辅助字段
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_triggered_at: Optional[float] = Field(default=None)
    trigger_count: int = Field(default=0)

    # 额外条件
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AlertEvent(BaseModel):
    """
    告警触发事件记录。

    每次规则触发生成一条事件，写入 PostgreSQL 供前端查询。
    ALERT-03 扩展：source / priority / ui_hint 字段。
    """

    event_id: str = Field(..., description="事件唯一 ID")
    rule_id: str = Field(default="", description="触发的规则 ID")
    ticker: str = Field(default="", description="标的代码")
    rule_type: Optional[AlertRuleType] = Field(default=None, description="规则类型")
    severity: AlertSeverity = Field(default=AlertSeverity.INFO, description="严重程度")
    message: str = Field(default="", description="告警消息（人类可读）")
    trigger_value: Optional[float] = Field(default=None, description="触发时的实际值")
    threshold: Optional[float] = Field(default=None, description="规则阈值")
    channels: List[AlertChannel] = Field(default_factory=list)
    triggered_at: float = Field(default_factory=time.time)
    acknowledged: bool = Field(default=False)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ALERT-03 扩展字段
    source: str = Field(default="user_rule", description="事件来源: user_rule|rate_limit|system|paper_drift|trade_fill|kill_switch|agent")
    priority: Optional[NotificationPriority] = Field(default=None, description="通知优先级（为空时由 PriorityResolver 计算）")
    ui_hint: Dict[str, Any] = Field(default_factory=dict, description="前端行为提示: {mode, flash, sound, duration}")


# ─────────────────────────────────────────
#  规则评估辅助
# ─────────────────────────────────────────


def evaluate_price_rule(rule: AlertRule, current_price: float, prev_price: Optional[float] = None) -> bool:
    """
    评估价格类规则是否触发。

    Args:
        rule: 告警规则
        current_price: 当前价格
        prev_price: 上一次价格（用于穿越检测）

    Returns:
        True 表示规则触发
    """
    if rule.rule_type == AlertRuleType.PRICE_ABOVE:
        return current_price > rule.threshold

    elif rule.rule_type == AlertRuleType.PRICE_BELOW:
        return current_price < rule.threshold

    elif rule.rule_type == AlertRuleType.PRICE_CROSS:
        if prev_price is None:
            return False
        # 上穿: prev <= threshold < current
        # 下穿: prev >= threshold > current
        cross_up = prev_price <= rule.threshold < current_price
        cross_down = prev_price >= rule.threshold > current_price
        return cross_up or cross_down

    elif rule.rule_type == AlertRuleType.PCT_CHANGE:
        if prev_price is None or prev_price == 0:
            return False
        pct = abs(current_price - prev_price) / prev_price
        return pct >= rule.threshold / 100.0  # threshold 以百分比存储

    elif rule.rule_type == AlertRuleType.VOLUME_SURGE:
        # volume_surge 的 threshold 是倍数（如 2.0 = 2 倍均量）
        # 需要外部传入均量，这里通过 metadata 传递
        avg_volume = rule.metadata.get("avg_volume", 0)
        current_volume = rule.metadata.get("current_volume", 0)
        if avg_volume <= 0:
            return False
        return current_volume / avg_volume >= rule.threshold

    return False


# ─────────────────────────────────────────
#  技术指标规则评估 (ALERT-05)
# ─────────────────────────────────────────


def evaluate_indicator_rule(
    rule: AlertRule,
    indicators: Dict[str, Any],
    prev_indicators: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    评估技术指标类规则是否触发。

    Args:
        rule: 告警规则
        indicators: 当前技术指标值 {"rsi": 65.3, "macd_line": 0.5, "signal_line": 0.3, ...}
        prev_indicators: 上一次技术指标值（用于穿越检测）

    Returns:
        True 表示规则触发
    """
    if rule.rule_type == AlertRuleType.RSI_THRESHOLD:
        rsi = indicators.get("rsi")
        if rsi is None:
            return False
        # threshold <= 50 表示超卖告警 (RSI < threshold)
        # threshold > 50 表示超买告警 (RSI > threshold)
        if rule.threshold <= 50:
            return rsi < rule.threshold
        else:
            return rsi > rule.threshold

    elif rule.rule_type == AlertRuleType.MACD_CROSS:
        macd_line = indicators.get("macd_line")
        signal_line = indicators.get("signal_line")
        if macd_line is None or signal_line is None:
            return False

        # direction: "golden" = 金叉 (MACD 上穿 Signal), "death" = 死叉 (MACD 下穿 Signal)
        direction = rule.metadata.get("direction", "golden")

        if prev_indicators is None:
            return False

        prev_macd = prev_indicators.get("macd_line")
        prev_signal = prev_indicators.get("signal_line")
        if prev_macd is None or prev_signal is None:
            return False

        if direction == "golden":
            # 金叉: 前一次 MACD <= Signal, 当前 MACD > Signal
            return prev_macd <= prev_signal and macd_line > signal_line
        else:
            # 死叉: 前一次 MACD >= Signal, 当前 MACD < Signal
            return prev_macd >= prev_signal and macd_line < signal_line

    elif rule.rule_type == AlertRuleType.MA_CROSS:
        short_period = rule.metadata.get("short_period", 10)
        long_period = rule.metadata.get("long_period", 20)
        short_key = f"ma_{short_period}"
        long_key = f"ma_{long_period}"

        short_ma = indicators.get(short_key)
        long_ma = indicators.get(long_key)
        if short_ma is None or long_ma is None:
            return False

        if prev_indicators is None:
            return False

        prev_short = prev_indicators.get(short_key)
        prev_long = prev_indicators.get(long_key)
        if prev_short is None or prev_long is None:
            return False

        # direction: "golden" = 短均上穿长均, "death" = 短均下穿长均
        direction = rule.metadata.get("direction", "golden")

        if direction == "golden":
            return prev_short <= prev_long and short_ma > long_ma
        else:
            return prev_short >= prev_long and short_ma < long_ma

    return False
