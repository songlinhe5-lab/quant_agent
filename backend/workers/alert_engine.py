"""
告警引擎 Worker (ALERT-01)
===========================

常驻后台进程，订阅 Redis 行情流，评估用户定义的告警规则，
触发时写入告警事件并通过多通道推送。

核心流程:
  1. 启动时从 Redis Hash 加载所有活跃告警规则
  2. 订阅 Redis 行情流 (quant:quotes:stream)
  3. 每条行情到达时，匹配对应 ticker 的规则
  4. 规则触发 → 冷却期去重 → 生成 AlertEvent → 多通道推送
  5. 定期持久化规则状态（trigger_count, last_triggered_at）

设计文档: docs/01 §十 告警中心
任务编号: ALERT-01
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import redis.asyncio as aioredis

from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
    evaluate_price_rule,
    evaluate_indicator_rule,
)
from backend.core.logger import logger
from backend.services.alert_dispatcher import AlertDispatcher
from backend.services.indicator_evaluator import IndicatorEvaluator, extract_indicators_from_tech_data, INDICATOR_RULE_TYPES

# ─────────────────────────────────────────
#  Redis 键空间
# ─────────────────────────────────────────
RULES_KEY = "quant:alerts:rules"           # Hash: {rule_id: AlertRule JSON}
EVENTS_KEY = "quant:alerts:events"         # List: AlertEvent JSON (最近 1000 条)
LAST_PRICES_KEY = "quant:alerts:prices"    # Hash: {ticker: last_price}


class AlertEngine:
    """
    告警引擎核心。

    用法:
        engine = AlertEngine(redis_client)
        await engine.start()
        # ... 引擎在后台运行 ...
        await engine.stop()
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        dispatcher: Optional[AlertDispatcher] = None,
        indicator_evaluator: Optional[IndicatorEvaluator] = None,
        market_data_service: Optional[Any] = None,
    ):
        self._redis = redis_client
        self._rules: Dict[str, AlertRule] = {}
        self._last_prices: Dict[str, float] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._push_callbacks: Dict[AlertChannel, Callable] = {}
        self._eval_count = 0
        self._trigger_count = 0
        self._dispatcher = dispatcher  # ALERT-03: 统一调度器
        self._indicator_evaluator = indicator_evaluator or IndicatorEvaluator()
        self._market_data = market_data_service  # 用于获取技术指标

    # ─────────────────────────────────
    #  规则管理
    # ─────────────────────────────────

    async def load_rules(self) -> int:
        """从 Redis 加载所有活跃规则"""
        raw_rules = await self._redis.hgetall(RULES_KEY)
        self._rules.clear()
        for rule_id, rule_json in raw_rules.items():
            try:
                rule = AlertRule.model_validate_json(rule_json)
                if rule.enabled:
                    self._rules[rule_id] = rule
            except Exception as e:
                logger.warning(f"[AlertEngine] 规则 {rule_id} 解析失败: {e}")
        logger.info(f"[AlertEngine] 加载 {len(self._rules)} 条活跃规则")
        return len(self._rules)

    async def add_rule(self, rule: AlertRule) -> None:
        """添加规则到引擎和 Redis"""
        self._rules[rule.rule_id] = rule
        await self._redis.hset(RULES_KEY, rule.rule_id, rule.model_dump_json())
        logger.info(f"[AlertEngine] 新增规则: {rule.rule_id} ({rule.name})")

    async def remove_rule(self, rule_id: str) -> bool:
        """移除规则"""
        self._rules.pop(rule_id, None)
        removed = await self._redis.hdel(RULES_KEY, rule_id)
        return removed > 0

    async def update_rule(self, rule: AlertRule) -> None:
        """更新规则"""
        rule.updated_at = time.time()
        self._rules[rule.rule_id] = rule
        await self._redis.hset(RULES_KEY, rule.rule_id, rule.model_dump_json())

    def get_rules(self) -> List[AlertRule]:
        """获取所有规则"""
        return list(self._rules.values())

    # ─────────────────────────────────
    #  推送通道注册
    # ─────────────────────────────────

    def register_push(self, channel: AlertChannel, callback: Callable) -> None:
        """注册推送通道回调"""
        self._push_callbacks[channel] = callback

    # ─────────────────────────────────
    #  行情评估
    # ─────────────────────────────────

    async def evaluate_quote(self, ticker: str, price: float, volume: Optional[float] = None) -> List[AlertEvent]:
        """
        评估一条行情数据是否触发告警。

        Args:
            ticker: 标的代码
            price: 当前价格
            volume: 当前成交量（可选）

        Returns:
            触发的告警事件列表
        """
        self._eval_count += 1
        triggered_events = []

        # 获取匹配该 ticker 的规则
        matching_rules = [r for r in self._rules.values() if r.ticker == ticker and r.enabled]
        if not matching_rules:
            return triggered_events

        # 分离价格类规则和指标类规则
        price_rules = [r for r in matching_rules if r.rule_type not in INDICATOR_RULE_TYPES]
        indicator_rules = [r for r in matching_rules if r.rule_type in INDICATOR_RULE_TYPES]

        # 获取上一次价格
        prev_price = self._last_prices.get(ticker)
        self._last_prices[ticker] = price

        now = time.time()

        # ── 价格类规则评估 ──
        for rule in price_rules:
            # 冷却期检查
            if rule.last_triggered_at and (now - rule.last_triggered_at) < rule.cooldown_seconds:
                continue

            # 注入成交量到 metadata（volume_surge 需要）
            if rule.rule_type == AlertRuleType.VOLUME_SURGE and volume is not None:
                rule.metadata["current_volume"] = volume

            # 评估规则
            if evaluate_price_rule(rule, price, prev_price):
                event = self._create_event(rule, price, now)
                triggered_events.append(event)

                # 更新规则状态
                rule.last_triggered_at = now
                rule.trigger_count += 1
                self._trigger_count += 1

                # 持久化规则状态
                await self._redis.hset(RULES_KEY, rule.rule_id, rule.model_dump_json())

                # 写入事件列表
                await self._redis.lpush(EVENTS_KEY, event.model_dump_json())
                await self._redis.ltrim(EVENTS_KEY, 0, 999)  # 保留最近 1000 条

                # 多通道推送
                await self._dispatch_event(event, rule.channels)

                logger.info(
                    f"[AlertEngine] 告警触发: {rule.name} | "
                    f"{ticker}={price} (阈值={rule.threshold}) | "
                    f"通道={[c.value for c in rule.channels]}"
                )

        # ── 指标类规则评估 (ALERT-05) ──
        if indicator_rules:
            indicator_events = await self._evaluate_indicator_rules(
                ticker, indicator_rules, now
            )
            triggered_events.extend(indicator_events)

        return triggered_events

    async def _evaluate_indicator_rules(
        self, ticker: str, rules: List[AlertRule], now: float
    ) -> List[AlertEvent]:
        """
        评估指标类规则（ALERT-05）。

        流程:
          1. 检查节流（盘中每 N 分钟评估一次）
          2. 获取技术指标
          3. 评估规则
          4. 触发 → 创建事件 + 推送
        """
        triggered_events = []

        # 节流检查
        if not self._indicator_evaluator.should_evaluate(ticker):
            return triggered_events

        # 获取技术指标
        indicators = await self._fetch_indicators(ticker)
        if not indicators:
            logger.debug(f"[AlertEngine] 指标获取失败，跳过 {ticker} 指标评估")
            return triggered_events

        # 评估规则
        results = self._indicator_evaluator.evaluate_rules(ticker, rules, indicators)
        self._indicator_evaluator.mark_evaluated(ticker)

        for rule, triggered in results:
            if not triggered:
                continue

            # 冷却期检查
            if rule.last_triggered_at and (now - rule.last_triggered_at) < rule.cooldown_seconds:
                continue

            event = self._create_indicator_event(rule, ticker, indicators, now)
            triggered_events.append(event)

            # 更新规则状态
            rule.last_triggered_at = now
            rule.trigger_count += 1
            self._trigger_count += 1

            # 持久化 + 推送
            await self._redis.hset(RULES_KEY, rule.rule_id, rule.model_dump_json())
            await self._redis.lpush(EVENTS_KEY, event.model_dump_json())
            await self._redis.ltrim(EVENTS_KEY, 0, 999)
            await self._dispatch_event(event, rule.channels)

            logger.info(
                f"[AlertEngine] 指标告警触发: {rule.name} | {ticker} | "
                f"type={rule.rule_type.value} | 通道={[c.value for c in rule.channels]}"
            )

        return triggered_events

    async def _fetch_indicators(self, ticker: str) -> Optional[Dict[str, Any]]:
        """获取技术指标"""
        if self._market_data is None:
            logger.debug("[AlertEngine] 无 market_data 服务，跳过指标获取")
            return None

        try:
            tech_data = await self._market_data.get_tech_indicators(
                ticker=ticker, lookback_days=1
            )
            if tech_data.get("status") == "success":
                return extract_indicators_from_tech_data(tech_data)
            logger.debug(f"[AlertEngine] 指标获取失败: {tech_data.get('message')}")
            return None
        except Exception as e:
            logger.warning(f"[AlertEngine] 指标获取异常: {e}")
            return None

    def _create_event(self, rule: AlertRule, price: float, ts: float) -> AlertEvent:
        """创建告警事件"""
        direction = ""
        if rule.rule_type == AlertRuleType.PRICE_ABOVE:
            direction = "突破上限"
        elif rule.rule_type == AlertRuleType.PRICE_BELOW:
            direction = "跌破下限"
        elif rule.rule_type == AlertRuleType.PRICE_CROSS:
            prev = self._last_prices.get(rule.ticker, price)
            direction = "上穿" if price > prev else "下穿"
        elif rule.rule_type == AlertRuleType.PCT_CHANGE:
            direction = "涨跌幅"
        elif rule.rule_type == AlertRuleType.VOLUME_SURGE:
            direction = "成交量突增"

        message = f"⚡ {rule.name}: {rule.ticker} {direction} {price:.2f} (阈值: {rule.threshold})"

        return AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id=rule.rule_id,
            ticker=rule.ticker,
            rule_type=rule.rule_type,
            severity=rule.severity,
            message=message,
            trigger_value=price,
            threshold=rule.threshold,
            channels=rule.channels,
            triggered_at=ts,
        )

    def _create_indicator_event(
        self, rule: AlertRule, ticker: str, indicators: Dict[str, Any], ts: float
    ) -> AlertEvent:
        """创建指标类告警事件 (ALERT-05)"""
        if rule.rule_type == AlertRuleType.RSI_THRESHOLD:
            rsi = indicators.get("rsi", 0)
            direction = "超买" if rule.threshold > 50 else "超卖"
            message = f"📊 {rule.name}: {ticker} RSI={rsi:.1f} {direction} (阈值: {rule.threshold})"
            trigger_value = rsi

        elif rule.rule_type == AlertRuleType.MACD_CROSS:
            macd = indicators.get("macd_line", 0)
            signal = indicators.get("signal_line", 0)
            direction = rule.metadata.get("direction", "golden")
            direction_cn = "金叉" if direction == "golden" else "死叉"
            message = f"📊 {rule.name}: {ticker} MACD {direction_cn} (MACD={macd:.4f}, Signal={signal:.4f})"
            trigger_value = macd

        elif rule.rule_type == AlertRuleType.MA_CROSS:
            short_p = rule.metadata.get("short_period", 10)
            long_p = rule.metadata.get("long_period", 20)
            short_ma = indicators.get(f"ma_{short_p}", 0)
            long_ma = indicators.get(f"ma_{long_p}", 0)
            direction = rule.metadata.get("direction", "golden")
            direction_cn = "上穿" if direction == "golden" else "下穿"
            message = f"📊 {rule.name}: {ticker} MA{short_p}/MA{long_p} {direction_cn} ({short_ma:.2f}/{long_ma:.2f})"
            trigger_value = short_ma

        else:
            message = f"📊 {rule.name}: {ticker} 指标告警触发"
            trigger_value = None

        return AlertEvent(
            event_id=str(uuid.uuid4()),
            rule_id=rule.rule_id,
            ticker=ticker,
            rule_type=rule.rule_type,
            severity=rule.severity,
            message=message,
            trigger_value=trigger_value,
            threshold=rule.threshold,
            channels=rule.channels,
            triggered_at=ts,
            source="indicator",
        )

    async def _dispatch_event(self, event: AlertEvent, channels: List[AlertChannel]) -> None:
        """通过 AlertDispatcher 推送告警（ALERT-03），降级为旧回调"""
        if self._dispatcher:
            # ALERT-03: 走统一调度器
            try:
                rule = self._rules.get(event.rule_id)
                await self._dispatcher.dispatch(event, rule=rule)
            except Exception as e:
                logger.error(f"[AlertEngine] Dispatcher 调用失败: {e}")
        else:
            # 降级：旧回调模式
            for channel in channels:
                callback = self._push_callbacks.get(channel)
                if callback:
                    try:
                        await callback(event) if asyncio.iscoroutinefunction(callback) else callback(event)
                    except Exception as e:
                        logger.error(f"[AlertEngine] 推送失败 (channel={channel.value}): {e}")

    # ─────────────────────────────────
    #  行情流订阅
    # ─────────────────────────────────

    async def _subscribe_loop(self) -> None:
        """订阅 Redis 行情流，持续评估"""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("quant:quotes:stream")
        logger.info("[AlertEngine] 已订阅行情流 quant:quotes:stream")

        try:
            async for message in pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "message":
                    continue

                try:
                    data = message["data"]
                    if isinstance(data, bytes):
                        # Protobuf 格式，需要解析
                        # 简化处理：尝试 JSON 解析
                        data = data.decode("utf-8", errors="ignore")
                    if isinstance(data, str):
                        quote = json.loads(data)
                        ticker = quote.get("ticker", "")
                        price = quote.get("close") or quote.get("price") or quote.get("last")
                        volume = quote.get("volume")
                        if ticker and price:
                            await self.evaluate_quote(ticker, float(price), volume)
                except Exception as e:
                    logger.debug(f"[AlertEngine] 行情解析跳过: {e}")
        finally:
            await pubsub.unsubscribe("quant:quotes:stream")
            await pubsub.aclose()

    # ─────────────────────────────────
    #  生命周期
    # ─────────────────────────────────

    async def start(self) -> None:
        """启动告警引擎"""
        self._running = True
        await self.load_rules()
        self._task = asyncio.create_task(self._subscribe_loop())
        logger.info("[AlertEngine] ✅ 告警引擎已启动")

    async def stop(self) -> None:
        """停止告警引擎"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info(f"[AlertEngine] 告警引擎已停止 (评估={self._eval_count}, 触发={self._trigger_count})")

    @property
    def stats(self) -> Dict[str, Any]:
        """引擎统计"""
        return {
            "running": self._running,
            "active_rules": len(self._rules),
            "eval_count": self._eval_count,
            "trigger_count": self._trigger_count,
            "tracked_tickers": len(self._last_prices),
            "push_channels": list(self._push_callbacks.keys()),
        }
