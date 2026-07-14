"""
DQ-02: 财务数据 Point-in-Time (PIT)
=====================================

核心问题：
  前视偏差 (Look-Ahead Bias)：如果回测中使用了在回测时点尚未公布的财务数据，
  会导致策略收益系统性偏乐观。例如：
  - 2024-01-15 做回测决策，但使用了 2024-02-28 才公布的 Q4 财报
  - 这相当于"预知未来"，回测结果毫无参考价值

解决方案：
  1. 每条财务数据附带两个时间戳：
     - period_end_date: 财报告期截止日 (如 2024-12-31 for Q4)
     - announce_date: 实际公布日期 (如 2025-02-15)
  2. 回测引擎只允许读取 announce_date <= 回测日期 的财务数据
  3. 数据查询接口强制传入 as_of_date 参数

设计文档: docs/TODO.md DQ-02
任务编号: DQ-02
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────
#  数据模型
# ─────────────────────────────────────────


class FinancialDataType(str, Enum):
    """财务数据类型"""

    INCOME_STATEMENT = "income_statement"  # 利润表
    BALANCE_SHEET = "balance_sheet"  # 资产负债表
    CASH_FLOW = "cash_flow"  # 现金流量表
    KEY_METRICS = "key_metrics"  # 关键指标 (PE/PB/ROE 等)
    EARNINGS = "earnings"  # 每股收益
    REVENUE = "revenue"  # 营收
    GUIDANCE = "guidance"  # 业绩指引


class FiscalPeriod(str, Enum):
    """财年周期"""

    Q1 = "Q1"  # 第一季度
    Q2 = "Q2"  # 第二季度
    Q3 = "Q3"  # 第三季度
    Q4 = "Q4"  # 第四季度 (年报)
    FY = "FY"  # 全年
    TTM = "TTM"  # 滚动 12 个月


@dataclass
class FinancialDataPoint:
    """
    单条财务数据点（Point-in-Time 语义）。

    核心字段：
    - period_end_date: 财报告期截止日
    - announce_date: 实际公布日期（必须 >= period_end_date）
    - as_of_date: 数据获取视角（查询时使用）

    不变量：
    - announce_date >= period_end_date
    - 回测时只能读取 announce_date <= backtest_date 的数据
    """

    symbol: str
    data_type: FinancialDataType
    fiscal_year: int  # 财年
    fiscal_period: FiscalPeriod  # 季度
    period_end_date: date  # 报告期截止日
    announce_date: date  # 实际公布日期
    values: Dict[str, Any] = field(default_factory=dict)  # 具体财务指标
    source: str = "unknown"  # 数据来源
    restated: bool = False  # 是否为重述数据
    restated_from: Optional[str] = None  # 重述来源 ID
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """验证不变量"""
        if self.announce_date < self.period_end_date:
            raise ValueError(f"announce_date ({self.announce_date}) 不能早于 period_end_date ({self.period_end_date})")

    def is_available_on(self, check_date: date) -> bool:
        """判断该数据在指定日期是否已公布"""
        return check_date >= self.announce_date

    @property
    def data_id(self) -> str:
        """唯一标识"""
        return f"{self.symbol}:{self.data_type.value}:{self.fiscal_year}{self.fiscal_period.value}"


@dataclass
class PITQuery:
    """Point-in-Time 查询参数"""

    symbol: str
    as_of_date: date  # 回测日期
    data_type: Optional[FinancialDataType] = None  # 限定类型
    fiscal_year: Optional[int] = None  # 限定财年
    fiscal_period: Optional[FiscalPeriod] = None  # 限定季度
    include_restatements: bool = False  # 是否包含重述数据


# ─────────────────────────────────────────
#  Point-in-Time 数据库
# ─────────────────────────────────────────


class PointInTimeStore:
    """
    Point-in-Time 财务数据存储。

    核心能力：
    1. 存储带 announce_date 的财务数据
    2. 按 as_of_date 查询"当时已公布"的数据
    3. 检测前视偏差尝试

    用法:
        store = PointInTimeStore()
        store.add(data_point)
        result = store.query_as_of(PITQuery(symbol="AAPL", as_of_date=date(2024, 1, 15)))
    """

    def __init__(self):
        # 按 symbol 分组存储，内部按 announce_date 排序
        self._data: Dict[str, List[FinancialDataPoint]] = {}
        self._query_count = 0
        self._blocked_count = 0  # 被 PIT 过滤拦截的次数

    @property
    def total_records(self) -> int:
        return sum(len(points) for points in self._data.values())

    @property
    def symbols(self) -> List[str]:
        return list(self._data.keys())

    # ─────────────────────────────────
    #  数据写入
    # ─────────────────────────────────

    def add(self, data_point: FinancialDataPoint) -> None:
        """添加财务数据点"""
        symbol = data_point.symbol
        if symbol not in self._data:
            self._data[symbol] = []

        data_point.created_at = datetime.utcnow()
        self._data[symbol].append(data_point)
        # 按 announce_date 排序，方便后续二分查找
        self._data[symbol].sort(key=lambda dp: dp.announce_date)

    def add_batch(self, data_points: List[FinancialDataPoint]) -> int:
        """批量添加"""
        for dp in data_points:
            self.add(dp)
        return len(data_points)

    # ─────────────────────────────────
    #  Point-in-Time 查询
    # ─────────────────────────────────

    def query_as_of(self, query: PITQuery) -> List[FinancialDataPoint]:
        """
        核心方法：查询在 as_of_date 已公布的财务数据。

        这是回测引擎应该使用的唯一查询接口。
        只返回 announce_date <= query.as_of_date 的数据。
        """
        self._query_count += 1
        points = self._data.get(query.symbol, [])
        if not points:
            return []

        result = []
        for dp in points:
            # 核心过滤：只返回已公布的数据
            if dp.announce_date > query.as_of_date:
                self._blocked_count += 1
                continue

            # 可选过滤
            if query.data_type and dp.data_type != query.data_type:
                continue
            if query.fiscal_year and dp.fiscal_year != query.fiscal_year:
                continue
            if query.fiscal_period and dp.fiscal_period != query.fiscal_period:
                continue
            if not query.include_restatements and dp.restated:
                continue

            result.append(dp)

        return result

    def get_latest_as_of(
        self,
        symbol: str,
        data_type: FinancialDataType,
        as_of_date: date,
    ) -> Optional[FinancialDataPoint]:
        """
        获取在 as_of_date 已公布的最新一期财务数据。

        典型用法：回测引擎获取"当时最新"的财报。
        """
        points = self.query_as_of(
            PITQuery(
                symbol=symbol,
                as_of_date=as_of_date,
                data_type=data_type,
            )
        )
        if not points:
            return None
        # 返回 announce_date 最晚的（即最新的）
        return max(points, key=lambda dp: dp.announce_date)

    def get_field_as_of(
        self,
        symbol: str,
        field_name: str,
        as_of_date: date,
        data_type: FinancialDataType = FinancialDataType.KEY_METRICS,
    ) -> Optional[Any]:
        """
        获取特定财务指标在 as_of_date 的值。

        便捷方法：直接返回某个指标的数值。
        """
        latest = self.get_latest_as_of(symbol, data_type, as_of_date)
        if latest is None:
            return None
        return latest.values.get(field_name)

    # ─────────────────────────────────
    #  前视偏差检测
    # ─────────────────────────────────

    def detect_look_ahead_risk(
        self,
        symbol: str,
        decision_date: date,
        data_type: Optional[FinancialDataType] = None,
    ) -> Dict[str, Any]:
        """
        检测在 decision_date 做决策时的前视偏差风险。

        返回：
        - available: 当时已公布的数据
        - not_yet_available: 当时未公布但之后公布的数据（如果使用就是前视偏差）
        - days_until_next: 距离下一个数据公布还有多少天
        """
        all_points = self._data.get(symbol, [])
        available = []
        not_yet_available = []

        for dp in all_points:
            if data_type and dp.data_type != data_type:
                continue
            if dp.announce_date <= decision_date:
                available.append(dp)
            else:
                not_yet_available.append(dp)

        # 计算距离下一个公布日的天数
        future_points = [dp for dp in not_yet_available if dp.announce_date > decision_date]
        days_until_next = None
        if future_points:
            next_announce = min(dp.announce_date for dp in future_points)
            days_until_next = (next_announce - decision_date).days

        return {
            "symbol": symbol,
            "decision_date": decision_date.isoformat(),
            "available_count": len(available),
            "not_yet_available_count": len(not_yet_available),
            "days_until_next_announce": days_until_next,
            "risk_level": "safe" if not not_yet_available else "warning",
        }

    # ─────────────────────────────────
    #  统计信息
    # ─────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取 PIT 存储统计"""
        total = self.total_records
        symbols_count = len(self._data)

        return {
            "total_records": total,
            "symbols_count": symbols_count,
            "query_count": self._query_count,
            "blocked_count": self._blocked_count,
            "block_rate": self._blocked_count / max(1, self._query_count * 10),
        }

    def get_announce_timeline(self, symbol: str) -> List[Dict[str, Any]]:
        """获取标的的财务数据公布时间线"""
        points = self._data.get(symbol, [])
        return [
            {
                "data_id": dp.data_id,
                "data_type": dp.data_type.value,
                "fiscal_period": f"{dp.fiscal_year}{dp.fiscal_period.value}",
                "period_end_date": dp.period_end_date.isoformat(),
                "announce_date": dp.announce_date.isoformat(),
                "lag_days": (dp.announce_date - dp.period_end_date).days,
                "restated": dp.restated,
            }
            for dp in points
        ]


# ─────────────────────────────────────────
#  全局单例
# ─────────────────────────────────────────

_pit_store: Optional[PointInTimeStore] = None


def get_pit_store() -> PointInTimeStore:
    """获取全局 PIT 存储单例"""
    global _pit_store
    if _pit_store is None:
        _pit_store = PointInTimeStore()
    return _pit_store


# ─────────────────────────────────────────
#  便捷函数
# ─────────────────────────────────────────


def get_financial_value(
    symbol: str,
    field_name: str,
    as_of_date: date,
    data_type: FinancialDataType = FinancialDataType.KEY_METRICS,
    store: Optional[PointInTimeStore] = None,
) -> Optional[Any]:
    """
    获取财务指标在指定日期的值（PIT 语义）。

    回测引擎应使用此函数替代直接读取财务数据。
    """
    if store is None:
        store = get_pit_store()
    return store.get_field_as_of(symbol, field_name, as_of_date, data_type)


def is_data_available(
    symbol: str,
    data_type: FinancialDataType,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    as_of_date: date,
    store: Optional[PointInTimeStore] = None,
) -> bool:
    """
    检查特定财务数据在 as_of_date 是否已公布。

    用于回测引擎在引用财务数据前做前置检查。
    """
    if store is None:
        store = get_pit_store()

    points = store.query_as_of(
        PITQuery(
            symbol=symbol,
            as_of_date=as_of_date,
            data_type=data_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        )
    )
    return len(points) > 0
