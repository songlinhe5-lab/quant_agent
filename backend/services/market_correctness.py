"""
BE-16: 行情数据正确性处理引擎（量化命门）

职责：
1. K线复权处理（前复权 QFQ / 后复权 HFQ / 不复权 NONE 切换）
2. 停牌 / 退市标的检测与标记
3. UTC 时区统一与各市场交易时段对齐
4. 价格异常值检测（0 价 / 跳变 / 负值防御）

核心原则：
- 所有内部存储与计算统一使用 UTC 时间戳
- 复权因子必须可追溯，禁止静默修改原始数据
- 停牌/退市标的必须显式标记，严禁污染下游分析
"""

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from backend.core.metrics import MARKET_DATA_CORRECTION_TOTAL

logger = structlog.get_logger(__name__)


# ==========================================
#  复权类型枚举
# ==========================================


class AdjustType(str, Enum):
    """K线复权类型"""

    NONE = "none"  # 不复权（原始价格）
    QFQ = "qfq"  # 前复权（Forward Adjusted）- 技术分析默认
    HFQ = "hfq"  # 后复权（Backward Adjusted）- 回测/收益计算默认


# ==========================================
#  市场交易时段定义
# ==========================================


class MarketSession:
    """市场交易时段定义（UTC 时间）"""

    # 各市场交易时段（UTC 时间，小时:分钟）
    SESSIONS = {
        # 美股 (NYSE/NASDAQ)
        "US": {
            "pre_market": (
                "04:00",
                "09:30",
            ),  # 盘前 04:00-09:30 ET = 08:00-13:30 UTC  # noqa: E501
            "regular": (
                "09:30",
                "16:00",
            ),  # 常规 09:30-16:00 ET = 13:30-20:00 UTC  # noqa: E501
            "after_hours": (
                "16:00",
                "20:00",
            ),  # 盘后 16:00-20:00 ET = 20:00-00:00 UTC  # noqa: E501
            "timezone_offset": -5,  # EST (UTC-5)，夏令时 EDT (UTC-4)
        },
        # 港股 (HKEX)
        "HK": {
            "pre_market": ("09:00", "09:30"),  # 盘前
            "regular_am": ("09:30", "12:00"),  # 上午盘
            "regular_pm": ("13:00", "16:00"),  # 下午盘
            "after_hours": ("16:00", "16:10"),  # 收市竞价
            "timezone_offset": 8,  # HKT (UTC+8)
        },
        # A股 (SSE/SZSE)
        "CN": {
            "regular_am": ("09:30", "11:30"),  # 上午盘
            "regular_pm": ("13:00", "15:00"),  # 下午盘
            "timezone_offset": 8,  # CST (UTC+8)
        },
    }

    @classmethod
    def get_market(cls, symbol: str) -> str:
        """根据 symbol 前缀判断市场"""
        if symbol.startswith("US.") or symbol.startswith("US_"):
            return "US"
        elif symbol.startswith("HK.") or symbol.startswith("HK_"):
            return "HK"
        elif symbol.startswith("SH.") or symbol.startswith("SZ.") or symbol.startswith("CN."):  # noqa: E501
            return "CN"
        else:
            return "US"  # 默认美股

    @classmethod
    def is_trading_hours(cls, symbol: str, dt: Optional[datetime] = None) -> bool:
        """判断指定时间是否在交易时段内"""
        market = cls.get_market(symbol)
        session = cls.SESSIONS.get(market)
        if not session:
            return False

        if dt is None:
            dt = datetime.now(timezone.utc)

        # 转换为市场本地时间
        offset = session["timezone_offset"]
        local_hour = (dt.hour + offset) % 24
        local_min = dt.minute

        # 简单判断：工作日 + 交易时段
        local_weekday = (dt.weekday() + (1 if offset < 0 and dt.hour + offset < 0 else 0)) % 7  # noqa: E501
        if local_weekday >= 5:  # 周六日
            return False

        time_val = local_hour * 100 + local_min

        if market == "US":
            return 930 <= time_val <= 1600
        elif market == "HK":
            return (930 <= time_val <= 1200) or (1300 <= time_val <= 1600)
        elif market == "CN":
            return (930 <= time_val <= 1130) or (1300 <= time_val <= 1500)

        return True


# ==========================================
#  停牌 / 退市标记
# ==========================================


class SuspensionStatus(str, Enum):
    """标的交易状态"""

    NORMAL = "normal"  # 正常交易
    SUSPENDED = "suspended"  # 停牌
    DELISTED = "delisted"  # 退市
    PRE_MARKET = "pre_market"  # 盘前
    AFTER_HOURS = "after_hours"  # 盘后


def detect_suspension(kline_df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    """
    检测停牌 / 数据缺失

    策略：
    1. 检查最近 N 个交易日是否有数据缺口
    2. 成交量为 0 的异常日
    3. 价格连续不变（可能是停牌前最后交易日）

    Returns:
        {
            "status": "normal" | "suspended" | "delisted",
            "suspension_days": [...],  # 疑似停牌日期列表
            "last_trade_date": "...",
            "confidence": 0.0 ~ 1.0,
        }
    """
    if kline_df is None or kline_df.empty:
        return {
            "status": "delisted",
            "suspension_days": [],
            "last_trade_date": None,
            "confidence": 0.9,
        }  # noqa: E501

    # 确保时间列已解析
    df = kline_df.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time")

    if len(df) < 5:
        return {
            "status": "normal",
            "suspension_days": [],
            "last_trade_date": None,
            "confidence": 0.5,
        }  # noqa: E501

    # 1. 检测成交量为 0 的异常日
    zero_volume_days = df[df["volume"] == 0]["time"].tolist()

    # 2. 检测价格连续不变（停牌前兆）
    price_unchanged = 0
    for i in range(1, min(6, len(df))):
        if abs(df.iloc[i]["close"] - df.iloc[i - 1]["close"]) < 0.001:
            price_unchanged += 1

    # 3. 检测最近交易日距今的天数
    last_date = df["time"].max()
    days_since_last = (datetime.now() - last_date).days if pd.notna(last_date) else 999

    # 综合判断
    status = SuspensionStatus.NORMAL
    confidence = 0.5

    if days_since_last > 30:
        status = SuspensionStatus.DELISTED
        confidence = 0.9
    elif days_since_last > 5 or len(zero_volume_days) > 3 or price_unchanged >= 4:
        status = SuspensionStatus.SUSPENDED
        confidence = 0.7

    return {
        "status": status.value,
        "suspension_days": [d.strftime("%Y-%m-%d") for d in zero_volume_days[:10]],
        "last_trade_date": last_date.strftime("%Y-%m-%d") if pd.notna(last_date) else None,  # noqa: E501
        "confidence": confidence,
    }


# ==========================================
#  复权因子处理
# ==========================================


def apply_adjustment(
    kline_df: pd.DataFrame,
    adjust_type: AdjustType = AdjustType.QFQ,
    adjust_factor_col: str = "adjust_factor",
) -> pd.DataFrame:
    """
    对 K线数据应用复权处理

    Args:
        kline_df: 原始 K线 DataFrame（必须包含 time, open, high, low, close, volume）
        adjust_type: 复权类型
        adjust_factor_col: 复权因子列名（如果存在）

    Returns:
        复权后的 DataFrame（新增 adj_close 列）
    """
    if kline_df is None or kline_df.empty:
        return kline_df

    df = kline_df.copy()

    if adjust_type == AdjustType.NONE:
        # 不复权：直接使用原始价格
        df["adj_close"] = df["close"]
        df["adj_open"] = df["open"]
        df["adj_high"] = df["high"]
        df["adj_low"] = df["low"]
        return df

    # 检查是否有复权因子列
    has_factor = adjust_factor_col in df.columns

    if adjust_type == AdjustType.QFQ:
        # 前复权：以最新价格为基准，向前调整历史价格
        if has_factor:
            # 有复权因子：直接应用
            factor = df[adjust_factor_col].fillna(1.0)
            df["adj_close"] = df["close"] * factor
            df["adj_open"] = df["open"] * factor
            df["adj_high"] = df["high"] * factor
            df["adj_low"] = df["low"] * factor
        else:
            # 无复权因子：使用累计复权算法（需要外部数据源提供）
            # 这里假设数据源已经是前复权数据（Futu 默认行为）
            df["adj_close"] = df["close"]
            df["adj_open"] = df["open"]
            df["adj_high"] = df["high"]
            df["adj_low"] = df["low"]

    elif adjust_type == AdjustType.HFQ:
        # 后复权：以最早价格为基准，向后调整
        if has_factor:
            factor = df[adjust_factor_col].fillna(1.0)
            # 后复权因子 = 复权因子 / 最新复权因子
            latest_factor = factor.iloc[-1] if len(factor) > 0 else 1.0
            hfq_factor = factor / latest_factor
            df["adj_close"] = df["close"] * hfq_factor
            df["adj_open"] = df["open"] * hfq_factor
            df["adj_high"] = df["high"] * hfq_factor
            df["adj_low"] = df["low"] * hfq_factor
        else:
            # 无复权因子时，后复权需要额外数据，这里降级为不复权
            logger.warning("[K线复权] 后复权需要复权因子数据，当前降级为不复权")
            df["adj_close"] = df["close"]
            df["adj_open"] = df["open"]
            df["adj_high"] = df["high"]
            df["adj_low"] = df["low"]

    return df


# ==========================================
#  价格异常值检测
# ==========================================


def detect_price_anomalies(
    kline_df: pd.DataFrame,
    symbol: str,
    max_change_pct: float = 0.5,  # 单日最大涨跌幅 50%
) -> List[Dict[str, Any]]:
    """
    检测 K线数据中的价格异常值

    检测规则：
    1. 价格 <= 0（无效数据）
    2. 单日涨跌幅超过阈值（可能是数据错误或极端行情）
    3. 成交量为负数
    4. OHLC 逻辑错误（如 high < low）

    Returns:
        异常记录列表
    """
    anomalies = []

    if kline_df is None or kline_df.empty:
        return anomalies

    df = kline_df.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])

    for idx, row in df.iterrows():
        date_str = row.get("time", idx)
        if hasattr(date_str, "strftime"):
            date_str = date_str.strftime("%Y-%m-%d")

        # 1. 价格 <= 0
        for col in ["open", "high", "low", "close"]:
            if col in row and row[col] <= 0:
                anomalies.append(
                    {
                        "date": str(date_str),
                        "symbol": symbol,
                        "type": "invalid_price",
                        "field": col,
                        "value": row[col],
                        "severity": "critical",
                    }
                )

        # 2. OHLC 逻辑错误
        if all(c in row for c in ["high", "low"]):
            if row["high"] < row["low"]:
                anomalies.append(
                    {
                        "date": str(date_str),
                        "symbol": symbol,
                        "type": "ohlc_inconsistency",
                        "detail": f"high({row['high']}) < low({row['low']})",
                        "severity": "critical",
                    }
                )

        # 3. 成交量为负
        if "volume" in row and row["volume"] < 0:
            anomalies.append(
                {
                    "date": str(date_str),
                    "symbol": symbol,
                    "type": "negative_volume",
                    "value": row["volume"],
                    "severity": "warning",
                }
            )

    # 4. 单日涨跌幅异常
    if "close" in df.columns and len(df) > 1:
        df["pct_change"] = df["close"].pct_change().abs()
        extreme_days = df[df["pct_change"] > max_change_pct]
        for idx, row in extreme_days.iterrows():
            date_str = row.get("time", idx)
            if hasattr(date_str, "strftime"):
                date_str = date_str.strftime("%Y-%m-%d")
            anomalies.append(
                {
                    "date": str(date_str),
                    "symbol": symbol,
                    "type": "extreme_change",
                    "value": f"{row['pct_change']:.2%}",
                    "severity": "warning",
                }
            )

    return anomalies


# ==========================================
#  时区统一工具
# ==========================================


def normalize_to_utc(dt: Any) -> datetime:
    """
    将任意时间格式统一转换为 UTC datetime

    支持输入：
    - datetime 对象（带/不带时区）
    - 时间戳（秒或毫秒）
    - 字符串（ISO 8601 格式）
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # 假设是本地时间，转为 UTC
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if isinstance(dt, (int, float)):
        # 时间戳
        if dt > 1e12:  # 毫秒时间戳
            dt = dt / 1000
        return datetime.fromtimestamp(dt, tz=timezone.utc)

    if isinstance(dt, str):
        # 尝试解析 ISO 格式
        try:
            parsed = pd.to_datetime(dt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            raise ValueError(f"无法解析时间字符串: {dt}")

    raise TypeError(f"不支持的时间类型: {type(dt)}")


def format_market_time(symbol: str, dt: datetime) -> str:
    """
    将 UTC 时间格式化为市场本地时间字符串

    例如：US.AAPL 的 2024-01-15 14:30 UTC → "2024-01-15 09:30 ET"
    """
    market = MarketSession.get_market(symbol)
    session = MarketSession.SESSIONS.get(market, MarketSession.SESSIONS["US"])
    offset = session["timezone_offset"]

    # 转换为本地时间
    from datetime import timedelta

    local_dt = dt + timedelta(hours=offset)

    # 格式化
    tz_abbr = {
        "US": "ET",
        "HK": "HKT",
        "CN": "CST",
    }.get(market, "UTC")

    return f"{local_dt.strftime('%Y-%m-%d %H:%M')} {tz_abbr}"


# ==========================================
#  综合数据质量检查
# ==========================================


class DataQualityChecker:
    """K线数据质量检查器"""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.anomalies: List[Dict[str, Any]] = []

    def check(self, kline_df: pd.DataFrame) -> Dict[str, Any]:
        """
        执行完整的数据质量检查

        Returns:
            {
                "symbol": "...",
                "quality_score": 0.0 ~ 1.0,
                "status": "normal" | "suspended" | "delisted",
                "anomalies": [...],
                "suspension_info": {...},
                "checked_at": "...",
            }
        """
        _t0 = time.perf_counter()

        # 1. 停牌检测
        suspension_info = detect_suspension(kline_df, self.symbol)

        # 2. 价格异常检测
        self.anomalies = detect_price_anomalies(kline_df, self.symbol)

        # 3. 计算质量分数
        total_rows = len(kline_df) if kline_df is not None else 0
        anomaly_count = len(self.anomalies)

        if total_rows == 0:
            quality_score = 0.0
        else:
            # 每个严重异常扣 0.1，每个警告扣 0.05
            critical_count = sum(1 for a in self.anomalies if a.get("severity") == "critical")  # noqa: E501
            warning_count = sum(1 for a in self.anomalies if a.get("severity") == "warning")  # noqa: E501
            penalty = critical_count * 0.1 + warning_count * 0.05
            quality_score = max(0.0, 1.0 - penalty)

        # 4. 记录指标
        MARKET_DATA_CORRECTION_TOTAL.labels(
            symbol=self.symbol,
            check_type="quality_check",
        ).inc()

        latency = time.perf_counter() - _t0
        logger.debug(
            f"[数据质量] {self.symbol} 检查完成: score={quality_score:.2f}, "
            f"anomalies={anomaly_count}, latency={latency:.3f}s"
        )

        return {
            "symbol": self.symbol,
            "quality_score": quality_score,
            "status": suspension_info["status"],
            "anomalies": self.anomalies[:20],  # 最多返回 20 条
            "suspension_info": suspension_info,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


# 便捷函数
def check_data_quality(symbol: str, kline_df: pd.DataFrame) -> Dict[str, Any]:
    """快速检查 K线数据质量"""
    checker = DataQualityChecker(symbol)
    return checker.check(kline_df)
