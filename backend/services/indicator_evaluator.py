"""
技术指标告警评估器 (ALERT-05)
================================

负责从行情服务获取技术指标，评估指标类告警规则是否触发。
支持 RSI 超买超卖、MACD 金叉死叉、均线穿越三种指标告警。

评估策略:
  - 收盘价触发：每日收盘后评估一次（精确）
  - 盘中节流：盘中每 N 分钟评估一次（N 由 throttle_minutes 配置，默认 15）

设计文档: docs/01 §十 告警中心
任务编号: ALERT-05
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from backend.core.alert_models import (
    AlertRule,
    AlertRuleType,
    evaluate_indicator_rule,
)
from backend.core.logger import logger

# 指标类规则类型集合
INDICATOR_RULE_TYPES = {
    AlertRuleType.RSI_THRESHOLD,
    AlertRuleType.MACD_CROSS,
    AlertRuleType.MA_CROSS,
}


class IndicatorEvaluator:
    """
    技术指标告警评估器。

    职责:
      1. 缓存最近一次指标值（用于穿越检测）
      2. 提供指标评估入口（供 AlertEngine 调用）
      3. 盘中节流控制（避免频繁计算）
    """

    def __init__(self, throttle_minutes: int = 15):
        """
        Args:
            throttle_minutes: 盘中评估节流间隔（分钟），默认 15 分钟
        """
        self._throttle_seconds = throttle_minutes * 60
        self._last_eval_time: Dict[str, float] = {}  # {ticker: timestamp}
        self._prev_indicators: Dict[str, Dict[str, Any]] = {}  # {ticker: indicators}
        self._current_indicators: Dict[str, Dict[str, Any]] = {}  # {ticker: indicators}

    def should_evaluate(self, ticker: str, force: bool = False) -> bool:
        """
        判断是否应该评估该标的的指标规则。

        Args:
            ticker: 标的代码
            force: 强制评估（忽略节流）

        Returns:
            True 表示应该评估
        """
        if force:
            return True

        last_time = self._last_eval_time.get(ticker, 0)
        return (time.time() - last_time) >= self._throttle_seconds

    def mark_evaluated(self, ticker: str) -> None:
        """标记该标的已评估"""
        self._last_eval_time[ticker] = time.time()

    def update_indicators(self, ticker: str, indicators: Dict[str, Any]) -> None:
        """
        更新指标缓存（滑动窗口：current → prev）

        Args:
            ticker: 标的代码
            indicators: 最新指标值
        """
        # 保存前一次指标（用于穿越检测）
        if ticker in self._current_indicators:
            self._prev_indicators[ticker] = self._current_indicators[ticker]
        self._current_indicators[ticker] = indicators

    def get_prev_indicators(self, ticker: str) -> Optional[Dict[str, Any]]:
        """获取前一次指标值"""
        return self._prev_indicators.get(ticker)

    def get_current_indicators(self, ticker: str) -> Optional[Dict[str, Any]]:
        """获取当前指标值"""
        return self._current_indicators.get(ticker)

    def evaluate_rules(
        self,
        ticker: str,
        rules: List[AlertRule],
        indicators: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[AlertRule, bool]]:
        """
        评估一组指标规则是否触发。

        Args:
            ticker: 标的代码
            rules: 待评估的规则列表（应只包含指标类规则）
            indicators: 最新指标值（如为空则使用缓存）

        Returns:
            [(rule, triggered), ...] 列表
        """
        if indicators is not None:
            self.update_indicators(ticker, indicators)

        current = self._current_indicators.get(ticker)
        if current is None:
            return [(r, False) for r in rules]

        prev = self._prev_indicators.get(ticker)
        results = []

        for rule in rules:
            if rule.rule_type not in INDICATOR_RULE_TYPES:
                continue

            triggered = evaluate_indicator_rule(rule, current, prev)
            results.append((rule, triggered))

            if triggered:
                logger.info(
                    f"[IndicatorEvaluator] 指标告警触发: {rule.name} | "
                    f"{ticker} | type={rule.rule_type.value} | "
                    f"current={self._format_indicators(current, rule)} "
                    f"prev={self._format_indicators(prev, rule) if prev else 'N/A'}"
                )

        return results

    def _format_indicators(self, indicators: Dict[str, Any], rule: AlertRule) -> str:
        """格式化指标值用于日志"""
        if rule.rule_type == AlertRuleType.RSI_THRESHOLD:
            return f"RSI={indicators.get('rsi', 'N/A'):.1f}"
        elif rule.rule_type == AlertRuleType.MACD_CROSS:
            return f"MACD={indicators.get('macd_line', 'N/A'):.4f},Signal={indicators.get('signal_line', 'N/A'):.4f}"
        elif rule.rule_type == AlertRuleType.MA_CROSS:
            short_p = rule.metadata.get("short_period", 10)
            long_p = rule.metadata.get("long_period", 20)
            return f"MA{short_p}={indicators.get(f'ma_{short_p}', 'N/A'):.2f},MA{long_p}={indicators.get(f'ma_{long_p}', 'N/A'):.2f}"
        return str(indicators)

    def clear_cache(self, ticker: Optional[str] = None) -> None:
        """清除指标缓存"""
        if ticker:
            self._last_eval_time.pop(ticker, None)
            self._prev_indicators.pop(ticker, None)
            self._current_indicators.pop(ticker, None)
        else:
            self._last_eval_time.clear()
            self._prev_indicators.clear()
            self._current_indicators.clear()


def extract_indicators_from_tech_data(tech_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 yfinance_service.get_tech_indicators 的返回数据中提取指标值。

    Args:
        tech_data: get_tech_indicators 返回的 {"data": {"trend": [...]}} 格式数据

    Returns:
        扁平化的指标字典 {"rsi": 65.3, "macd_line": 0.5, "signal_line": 0.3, "ma_10": 150.2, ...}
    """
    indicators: Dict[str, Any] = {}

    data = tech_data.get("data", {})
    trend_list = data.get("trend", [])
    if not trend_list:
        return indicators

    # 取最新一条（第一条）
    latest = trend_list[0] if isinstance(trend_list, list) else trend_list

    # RSI
    if "RSI_14" in latest:
        indicators["rsi"] = float(latest["RSI_14"])

    # MACD
    if "MACD_12_26_9" in latest:
        indicators["macd_line"] = float(latest["MACD_12_26_9"])
    if "MACDs_12_26_9" in latest:
        indicators["signal_line"] = float(latest["MACDs_12_26_9"])
    if "MACDh_12_26_9" in latest:
        indicators["macd_hist"] = float(latest["MACDh_12_26_9"])

    # MA (提取常见周期)
    for period in [5, 10, 20, 50, 100, 200]:
        key = f"SMA_{period}" if f"SMA_{period}" in latest else f"MA_{period}"
        if key in latest:
            indicators[f"ma_{period}"] = float(latest[key])

    # KDJ
    if "K_9_3_3" in latest:
        indicators["k"] = float(latest["K_9_3_3"])
    if "D_9_3_3" in latest:
        indicators["d"] = float(latest["D_9_3_3"])
    if "J_9_3_3" in latest:
        indicators["j"] = float(latest["J_9_3_3"])

    # ATR
    if "ATR_14" in latest:
        indicators["atr"] = float(latest["ATR_14"])

    return indicators
