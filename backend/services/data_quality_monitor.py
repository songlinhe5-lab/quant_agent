"""
数据质量监控服务 (SVC-04)
========================

实时行情数据质量校验引擎：
  1. 字段完整性检查（OHLCV 必填字段非空）
  2. 价格异常检测（零价/跳变/负值）
  3. 时间戳新鲜度检测（数据延迟超阈值告警）
  4. Prometheus 指标暴露（脏数据率/延迟/异常计数）
  5. 告警触发（超阈值自动推送飞书）

设计文档: docs/TODO.md SVC-04
对标: LEAN / Norgate 数据质量底线
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from backend.core.logger import logger


class QualityLevel(str, Enum):
    """数据质量等级"""

    GOOD = "good"          # 完全正常
    DEGRADED = "degraded"  # 轻微异常（个别字段缺失）
    POOR = "poor"          # 严重异常（价格错误/大幅延迟）
    UNUSABLE = "unusable"  # 不可用（完全无数据/全部字段缺失）


class AnomalyType(str, Enum):
    """异常类型"""

    MISSING_FIELD = "missing_field"          # 必填字段缺失
    ZERO_PRICE = "zero_price"                # 零价
    NEGATIVE_PRICE = "negative_price"        # 负价
    PRICE_JUMP = "price_jump"                # 价格跳变（>阈值）
    NEGATIVE_VOLUME = "negative_volume"      # 负成交量
    STALE_TIMESTAMP = "stale_timestamp"      # 时间戳过期
    OHLC_INCONSISTENCY = "ohlc_inconsistency"  # OHLC 逻辑错误 (high < low)
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"  # 重复时间戳


@dataclass
class QualityMetrics:
    """数据质量指标（按数据源维度聚合）"""

    source: str                                # 数据源名称 (futu/yfinance/finnhub)
    total_records: int = 0                     # 总记录数
    valid_records: int = 0                     # 有效记录数
    anomaly_count: int = 0                     # 异常记录数
    missing_field_count: int = 0               # 字段缺失次数
    price_anomaly_count: int = 0               # 价格异常次数
    stale_count: int = 0                       # 过期数据次数
    avg_latency_ms: float = 0.0                # 平均数据延迟 (ms)
    max_latency_ms: float = 0.0                # 最大数据延迟 (ms)
    last_check_at: float = 0.0                 # 最后检查时间戳
    quality_level: QualityLevel = QualityLevel.GOOD
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def dirty_rate(self) -> float:
        """脏数据率"""
        if self.total_records == 0:
            return 0.0
        return self.anomaly_count / self.total_records

    @property
    def completeness_rate(self) -> float:
        """字段完整率"""
        if self.total_records == 0:
            return 0.0
        return self.valid_records / self.total_records


# ─────────────────────────────────────────
#  配置常量
# ─────────────────────────────────────────
REQUIRED_FIELDS = ["open", "high", "low", "close", "volume"]
MAX_PRICE_JUMP_PCT = 0.5       # 单次价格跳变阈值 50%
STALE_THRESHOLD_SECONDS = 60   # 数据过期阈值 60 秒
ALERT_DIRTY_RATE_THRESHOLD = 0.05  # 脏数据率告警阈值 5%
ALERT_STALE_COUNT_THRESHOLD = 10   # 连续过期数据告警阈值


class DataQualityMonitor:
    """
    数据质量监控器。

    用法:
        monitor = DataQualityMonitor("futu")
        result = monitor.validate_quote({"ticker": "AAPL", "price": 150.0, ...})
        metrics = monitor.get_metrics()
    """

    def __init__(self, source: str):
        self.source = source
        self._metrics = QualityMetrics(source=source)
        self._last_prices: Dict[str, float] = {}  # ticker → last_price (跳变检测)
        self._consecutive_stale = 0
        self._alert_callback = None

    def set_alert_callback(self, callback):
        """设置告警回调函数（接飞书/Telegram 推送）"""
        self._alert_callback = callback

    def validate_quote(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        """
        校验单条行情数据质量。

        Args:
            quote: 行情数据字典，必须包含 ticker 字段

        Returns:
            校验结果 {"valid": bool, "anomalies": [...], "quality": QualityLevel}
        """
        self._metrics.total_records += 1
        anomalies = []
        ticker = quote.get("ticker", "UNKNOWN")

        # 1. 字段完整性检查
        missing = [f for f in REQUIRED_FIELDS if f not in quote or quote[f] is None]
        if missing:
            anomalies.append({
                "type": AnomalyType.MISSING_FIELD.value,
                "ticker": ticker,
                "fields": missing,
                "severity": "warning",
            })
            self._metrics.missing_field_count += len(missing)

        # 2. 价格异常检测
        for price_field in ["open", "high", "low", "close"]:
            price = quote.get(price_field)
            if price is None:
                continue
            if price <= 0:
                anomaly_type = AnomalyType.ZERO_PRICE if price == 0 else AnomalyType.NEGATIVE_PRICE
                anomalies.append({
                    "type": anomaly_type.value,
                    "ticker": ticker,
                    "field": price_field,
                    "value": price,
                    "severity": "critical",
                })
                self._metrics.price_anomaly_count += 1
            elif ticker in self._last_prices and self._last_prices[ticker] > 0:
                # 价格跳变检测
                jump_pct = abs(price - self._last_prices[ticker]) / self._last_prices[ticker]
                if jump_pct > MAX_PRICE_JUMP_PCT:
                    anomalies.append({
                        "type": AnomalyType.PRICE_JUMP.value,
                        "ticker": ticker,
                        "field": price_field,
                        "value": price,
                        "prev_value": self._last_prices[ticker],
                        "jump_pct": round(jump_pct * 100, 2),
                        "severity": "warning",
                    })
                    self._metrics.price_anomaly_count += 1

        # 更新最后价格（用收盘价）
        close = quote.get("close")
        if close and close > 0:
            self._last_prices[ticker] = close

        # 3. 成交量检查
        volume = quote.get("volume")
        if volume is not None and volume < 0:
            anomalies.append({
                "type": AnomalyType.NEGATIVE_VOLUME.value,
                "ticker": ticker,
                "value": volume,
                "severity": "critical",
            })
            self._metrics.price_anomaly_count += 1

        # 4. OHLC 一致性检查
        ohlc = {f: quote.get(f) for f in ["open", "high", "low", "close"]}
        if all(v is not None and v > 0 for v in ohlc.values()):
            if ohlc["high"] < ohlc["low"]:
                anomalies.append({
                    "type": AnomalyType.OHLC_INCONSISTENCY.value,
                    "ticker": ticker,
                    "detail": f"high({ohlc['high']}) < low({ohlc['low']})",
                    "severity": "critical",
                })
                self._metrics.price_anomaly_count += 1

        # 5. 时间戳新鲜度检查
        ts = quote.get("timestamp") or quote.get("ts")
        if ts:
            try:
                data_time = float(ts)
                latency_ms = (time.time() - data_time) * 1000
                self._metrics.avg_latency_ms = (
                    (self._metrics.avg_latency_ms * (self._metrics.total_records - 1) + latency_ms)
                    / self._metrics.total_records
                )
                self._metrics.max_latency_ms = max(self._metrics.max_latency_ms, latency_ms)

                if latency_ms > STALE_THRESHOLD_SECONDS * 1000:
                    anomalies.append({
                        "type": AnomalyType.STALE_TIMESTAMP.value,
                        "ticker": ticker,
                        "latency_ms": round(latency_ms, 1),
                        "threshold_ms": STALE_THRESHOLD_SECONDS * 1000,
                        "severity": "warning",
                    })
                    self._metrics.stale_count += 1
                    self._consecutive_stale += 1
                else:
                    self._consecutive_stale = 0
            except (ValueError, TypeError):
                pass

        # 更新指标
        is_valid = len(anomalies) == 0
        if is_valid:
            self._metrics.valid_records += 1
        self._metrics.anomaly_count += len(anomalies)
        self._metrics.last_check_at = time.time()
        self._metrics.anomalies.extend(anomalies[-100:])  # 保留最近 100 条异常

        # 更新质量等级
        self._update_quality_level()

        # 检查是否需要告警
        self._check_alert_thresholds()

        # DQ-04：同步 Prometheus（按 source 维度）
        self.export_to_prometheus(valid=is_valid)

        return {
            "valid": is_valid,
            "anomalies": anomalies,
            "quality": self._metrics.quality_level.value,
        }

    def _update_quality_level(self):
        """根据当前指标更新质量等级"""
        dirty = self._metrics.dirty_rate
        if dirty > 0.2 or self._metrics.stale_count > ALERT_STALE_COUNT_THRESHOLD * 2:
            self._metrics.quality_level = QualityLevel.UNUSABLE
        elif dirty > 0.1:
            self._metrics.quality_level = QualityLevel.POOR
        elif dirty > ALERT_DIRTY_RATE_THRESHOLD:
            self._metrics.quality_level = QualityLevel.DEGRADED
        else:
            self._metrics.quality_level = QualityLevel.GOOD

    def _check_alert_thresholds(self):
        """检查是否触发告警"""
        if self._alert_callback is None:
            return

        should_alert = False
        reasons = []

        if self._metrics.dirty_rate > ALERT_DIRTY_RATE_THRESHOLD:
            should_alert = True
            reasons.append(f"脏数据率 {self._metrics.dirty_rate:.1%} 超阈值 {ALERT_DIRTY_RATE_THRESHOLD:.0%}")

        if self._consecutive_stale >= ALERT_STALE_COUNT_THRESHOLD:
            should_alert = True
            reasons.append(f"连续 {self._consecutive_stale} 条数据过期")

        if should_alert:
            alert_msg = (
                f"[数据质量告警] 源={self.source} "
                f"质量等级={self._metrics.quality_level.value} | "
                + " | ".join(reasons)
            )
            logger.warning(alert_msg)
            try:
                self._alert_callback(alert_msg)
            except Exception as e:
                logger.error(f"告警回调失败: {e}")

    def get_metrics(self) -> QualityMetrics:
        """获取当前质量指标快照"""
        return self._metrics

    def get_prometheus_labels(self) -> Dict[str, float]:
        """返回 Prometheus 指标字典（兼容旧测试；正式埋点见 export_to_prometheus）。"""
        m = self._metrics
        return {
            f"data_quality_total_records_{self.source}": m.total_records,
            f"data_quality_valid_records_{self.source}": m.valid_records,
            f"data_quality_anomaly_count_{self.source}": m.anomaly_count,
            f"data_quality_dirty_rate_{self.source}": round(m.dirty_rate, 4),
            f"data_quality_completeness_{self.source}": round(m.completeness_rate, 4),
            f"data_quality_avg_latency_ms_{self.source}": round(m.avg_latency_ms, 2),
            f"data_quality_max_latency_ms_{self.source}": round(m.max_latency_ms, 2),
            f"data_quality_stale_count_{self.source}": m.stale_count,
            f"data_quality_price_anomaly_{self.source}": m.price_anomaly_count,
        }

    def export_to_prometheus(self, *, valid: bool = True) -> None:
        """将当前指标写入 prometheus_client Gauge/Counter（DQ-04 Grafana 数据源）。"""
        try:
            from backend.core.metrics import (
                DATA_QUALITY_ANOMALY_COUNT,
                DATA_QUALITY_CHECKS,
                DATA_QUALITY_COMPLETENESS,
                DATA_QUALITY_DIRTY_RATE,
                DATA_QUALITY_LATENCY_MS,
                DATA_QUALITY_LEVEL,
                DATA_QUALITY_MISSING_FIELDS,
                DATA_QUALITY_PRICE_ANOMALY,
                DATA_QUALITY_STALE_COUNT,
                DATA_QUALITY_TOTAL_RECORDS,
            )

            m = self._metrics
            src = self.source
            DATA_QUALITY_DIRTY_RATE.labels(source=src).set(m.dirty_rate)
            DATA_QUALITY_COMPLETENESS.labels(source=src).set(m.completeness_rate)
            DATA_QUALITY_TOTAL_RECORDS.labels(source=src).set(m.total_records)
            DATA_QUALITY_ANOMALY_COUNT.labels(source=src).set(m.anomaly_count)
            DATA_QUALITY_MISSING_FIELDS.labels(source=src).set(m.missing_field_count)
            DATA_QUALITY_PRICE_ANOMALY.labels(source=src).set(m.price_anomaly_count)
            DATA_QUALITY_STALE_COUNT.labels(source=src).set(m.stale_count)
            DATA_QUALITY_LATENCY_MS.labels(source=src).set(m.avg_latency_ms)
            level_map = {
                QualityLevel.GOOD: 0,
                QualityLevel.DEGRADED: 1,
                QualityLevel.POOR: 2,
                QualityLevel.UNUSABLE: 3,
            }
            DATA_QUALITY_LEVEL.labels(source=src).set(level_map.get(m.quality_level, 0))
            DATA_QUALITY_CHECKS.labels(source=src, result="ok" if valid else "anomaly").inc()
        except Exception as e:
            logger.debug(f"prometheus_export_skipped: {e}")

    def to_public_dict(self) -> Dict[str, Any]:
        """API / 看板摘要。"""
        m = self._metrics
        return {
            "source": self.source,
            "dirty_rate": round(m.dirty_rate, 4),
            "completeness_rate": round(m.completeness_rate, 4),
            "total_records": m.total_records,
            "valid_records": m.valid_records,
            "anomaly_count": m.anomaly_count,
            "missing_field_count": m.missing_field_count,
            "price_anomaly_count": m.price_anomaly_count,
            "stale_count": m.stale_count,
            "avg_latency_ms": round(m.avg_latency_ms, 2),
            "max_latency_ms": round(m.max_latency_ms, 2),
            "quality_level": m.quality_level.value,
            "last_check_at": m.last_check_at,
            "recent_anomalies": m.anomalies[-10:],
        }

    def reset(self):
        """重置指标（用于定期清零）"""
        self._metrics = QualityMetrics(source=self.source)
        self._last_prices.clear()
        self._consecutive_stale = 0
        self.export_to_prometheus(valid=True)


# ─────────────────────────────────────────
#  全局注册表（按数据源分维度 · DQ-04）
# ─────────────────────────────────────────

_MONITORS: Dict[str, DataQualityMonitor] = {}


def get_quality_monitor(source: str) -> DataQualityMonitor:
    """获取或创建指定数据源的质量监控器。"""
    key = (source or "unknown").lower()
    if key not in _MONITORS:
        _MONITORS[key] = DataQualityMonitor(key)
    return _MONITORS[key]


def list_quality_monitors() -> List[DataQualityMonitor]:
    return list(_MONITORS.values())


def quality_overview() -> Dict[str, Any]:
    """汇总所有数据源质量指标（供 API / 自检）。"""
    monitors = list_quality_monitors()
    return {
        "sources": [m.to_public_dict() for m in monitors],
        "source_count": len(monitors),
        "worst_dirty_rate": max((m.get_metrics().dirty_rate for m in monitors), default=0.0),
        "alert_dirty_rate_threshold": ALERT_DIRTY_RATE_THRESHOLD,
    }
