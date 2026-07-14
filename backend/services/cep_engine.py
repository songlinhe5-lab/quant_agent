"""
QUANT-04: 盘中实时 CEP (Complex Event Processing) 异动筛选引擎

基于 Redis pub/sub 行情流，实时计算技术指标并评估用户定义的规则。
复用 QUANT-03 cross_sectional 的指标计算与表达式解析器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Set

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from backend.services.cross_sectional import compute_indicators, evaluate_expression

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────


class CEPRule(BaseModel):
    """CEP 规则定义"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = Field(description="规则名称")
    expression: str = Field(description="指标表达式，复用 QUANT-03 语法")
    watchlist: List[str] = Field(default_factory=list, description="监控标的列表")
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)


class CEPMatch(BaseModel):
    """CEP 匹配事件"""
    rule_id: str
    rule_name: str
    symbol: str
    expression: str
    indicators: Dict[str, Any]
    matched_at: float = Field(default_factory=time.time)


# ─────────────────────────────────────────────
# CEP 引擎核心
# ─────────────────────────────────────────────


class CEPEngine:
    """
    实时 CEP 引擎

    - 维护每只标的的 K 线滑动窗口 (最近 N 根)
    - 收到新 tick 时追加到窗口，重新计算指标
    - 评估所有已启用规则，触发冷却机制防重复推送
    """

    # K 线窗口大小 (需足够计算 RSI(14) 等)
    WINDOW_SIZE = 60

    # 触发冷却 (秒): 同一规则同一标的在此时间内不重复推送
    COOLDOWN_SECONDS = 300

    def __init__(self) -> None:
        self._rules: Dict[str, CEPRule] = {}
        # {ticker: deque of recent bar dicts}
        self._bar_buffers: Dict[str, Deque[Dict[str, float]]] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_SIZE)
        )
        # {(rule_id, symbol): last_trigger_timestamp}
        self._cooldown_map: Dict[tuple, float] = {}
        # 最近匹配事件列表 (供 SSE 推送)
        self._match_queue: Deque[CEPMatch] = deque(maxlen=200)
        # Redis pub/sub 任务引用
        self._pubsub_task: Optional[asyncio.Task] = None

    # ── 规则 CRUD ──

    def add_rule(self, name: str, expression: str, watchlist: List[str]) -> CEPRule:
        """创建并注册一条新规则"""
        rule = CEPRule(name=name, expression=expression, watchlist=watchlist)
        self._rules[rule.id] = rule
        logger.info(f"[CEP] 新增规则 {rule.id}: {name} ({expression}) 监控 {len(watchlist)} 只标的")
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """删除规则"""
        if rule_id in self._rules:
            del self._rules[rule_id]
            # 清理相关冷却记录
            keys_to_remove = [k for k in self._cooldown_map if k[0] == rule_id]
            for k in keys_to_remove:
                del self._cooldown_map[k]
            return True
        return False

    def list_rules(self) -> List[CEPRule]:
        """列出所有规则"""
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> Optional[CEPRule]:
        return self._rules.get(rule_id)

    # ── 行情数据摄入 ──

    def on_bar(self, ticker: str, open_price: float, high: float, low: float,
               close: float, volume: float, timestamp: Optional[float] = None) -> List[CEPMatch]:
        """
        接收一根 K 线 (或 tick 近似为 bar)，更新缓冲区并评估规则。

        Returns:
            触发的匹配事件列表
        """
        ts = timestamp or time.time()
        bar = {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "timestamp": ts,
        }
        self._bar_buffers[ticker].append(bar)

        # 数据不足时跳过
        if len(self._bar_buffers[ticker]) < 30:
            return []

        return self._evaluate_all_rules(ticker, ts)

    def on_quote(self, ticker: str, price: float, volume: float,
                 timestamp: Optional[float] = None) -> List[CEPMatch]:
        """
        接收实时报价 (tick)，简化为 bar 追加。
        高频场景下，同一根 bar 周期内只保留最新价 (OHLC 聚合)。
        """
        ts = timestamp or time.time()
        buf = self._bar_buffers[ticker]

        # 简化处理: 每次 quote 直接作为一根 bar 追加
        # (对于日内 tick 级数据，可在此实现 bar 聚合逻辑)
        return self.on_bar(ticker, price, price, price, price, volume, ts)

    # ── 规则评估 ──

    def _evaluate_all_rules(self, ticker: str, ts: float) -> List[CEPMatch]:
        """评估所有涉及该 ticker 的已启用规则"""
        matches = []
        buf = self._bar_buffers[ticker]
        if len(buf) < 30:
            return matches

        # 构建 DataFrame
        df = pd.DataFrame(list(buf))

        try:
            enriched = compute_indicators(df)
        except Exception as e:
            logger.warning(f"[CEP] {ticker} 指标计算失败: {e}")
            return matches

        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if ticker not in rule.watchlist:
                continue

            # 冷却检查
            cooldown_key = (rule.id, ticker)
            last_trigger = self._cooldown_map.get(cooldown_key, 0)
            if ts - last_trigger < self.COOLDOWN_SECONDS:
                continue

            try:
                mask = evaluate_expression(enriched, rule.expression)
                if mask.iloc[-1]:
                    # 提取最新指标快照
                    latest = enriched.iloc[-1]
                    indicator_snapshot = {
                        "rsi": round(float(latest.get("rsi", 0) or 0), 2),
                        "kdj_k": round(float(latest.get("kdj_k", 0) or 0), 2),
                        "macd_dif": round(float(latest.get("macd_dif", 0) or 0), 4),
                        "macd_histogram": round(float(latest.get("macd_histogram", 0) or 0), 4),
                        "close": round(float(latest.get("close", 0) or 0), 2),
                    }
                    match = CEPMatch(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        symbol=ticker,
                        expression=rule.expression,
                        indicators=indicator_snapshot,
                        matched_at=ts,
                    )
                    matches.append(match)
                    self._cooldown_map[cooldown_key] = ts
                    self._match_queue.append(match)
                    logger.info(f"[CEP] 规则 '{rule.name}' 触发: {ticker} @ {indicator_snapshot}")
            except Exception as e:
                logger.warning(f"[CEP] 规则 {rule.id} 评估失败: {e}")

        return matches

    # ── 匹配事件队列 ──

    def get_recent_matches(self, since: Optional[float] = None) -> List[CEPMatch]:
        """获取最近的匹配事件"""
        if since is None:
            return list(self._match_queue)
        return [m for m in self._match_queue if m.matched_at >= since]

    def clear_matches(self) -> None:
        self._match_queue.clear()

    # ── Redis 订阅 (生产模式) ──

    async def subscribe_redis_stream(self) -> None:
        """
        订阅 Redis pub/sub 行情流，实时处理每笔报价。
        生产环境由 worker.py 启动。
        """
        try:
            from backend.core.redis_client import redis_client
            from backend.core.proto.market_pb2 import QuoteData  # type: ignore

            pubsub = redis_client.pubsub()
            await pubsub.subscribe("quant:quotes:stream")
            logger.info("[CEP] 已订阅 quant:quotes:stream 行情频道")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    quote = QuoteData()
                    quote.ParseFromString(message["data"])
                    ticker = quote.ticker
                    price = quote.last_price
                    volume = float(quote.volume_str.replace(",", "").replace("万", "0000").replace("亿", "00000000").split()[0]) if quote.volume_str else 0

                    if price > 0:
                        self.on_quote(ticker, price, volume)
                except Exception as e:
                    logger.debug(f"[CEP] 解析行情消息失败: {e}")
        except Exception as e:
            logger.error(f"[CEP] Redis 订阅失败: {e}")

    def start_background(self) -> asyncio.Task:
        """启动后台 Redis 订阅任务"""
        if self._pubsub_task is None or self._pubsub_task.done():
            self._pubsub_task = asyncio.create_task(self.subscribe_redis_stream())
        return self._pubsub_task

    def stop(self) -> None:
        """停止后台任务"""
        if self._pubsub_task and not self._pubsub_task.done():
            self._pubsub_task.cancel()


# ─────────────────────────────────────────────
# 全局单例
# ─────────────────────────────────────────────

cep_engine = CEPEngine()
