"""
DQ-01: 幸存者偏差处理 (Survivorship Bias)
==========================================

核心问题：
  如果用当前存续的股票列表回测历史策略，会系统性高估收益率——
  因为已经退市/摘牌的标的（通常表现较差）被排除在外。

解决方案：
  1. 维护全量标的存续记录（含上市日/退市日）
  2. 按"回测时点"动态生成标的池（只包含当日实际存续的标的）
  3. 禁止用当前存续列表回测历史

数据来源：
  - Futu get_stock_basicinfo（含退市标志）
  - YFinance（补充美股退市标的）
  - 手动维护的退市标的 CSV

设计文档: docs/TODO.md DQ-01
任务编号: DQ-01
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────
#  数据模型
# ─────────────────────────────────────────


class ListingStatus(str, Enum):
    """标的上市状态"""

    LISTED = "listed"          # 当前存续
    DELISTED = "delisted"      # 已退市/摘牌
    SUSPENDED = "suspended"    # 停牌中
    UNKNOWN = "unknown"        # 未知


@dataclass
class TickerLifecycle:
    """标的生命周期记录"""

    symbol: str                         # 标的代码 (如 US.AAPL, HK.00700)
    name: str = ""                      # 名称
    market: str = ""                    # 市场 (US/HK/SH/SZ)
    list_date: Optional[date] = None    # 上市日期
    delist_date: Optional[date] = None  # 退市日期
    status: ListingStatus = ListingStatus.UNKNOWN
    delist_reason: str = ""             # 退市原因
    source: str = "manual"              # 数据来源 (futu/yfinance/manual)
    updated_at: Optional[datetime] = None

    def is_alive_on(self, check_date: date) -> bool:
        """判断该标的在指定日期是否存续"""
        if self.status == ListingStatus.DELISTED and self.delist_date:
            # 退市标的：在退市日期之前（不含当日）存续
            return check_date < self.delist_date
        if self.list_date:
            # 有上市日期：在上市日期之后存续
            return check_date >= self.list_date
        # 无明确日期信息，默认为存续（保守策略）
        return True

    def was_alive_on(self, check_date: date) -> bool:
        """别名，语义更清晰"""
        return self.is_alive_on(check_date)


@dataclass
class UniverseSnapshot:
    """标的池快照（某一时点的存续标的集合）"""

    as_of_date: date
    tickers: List[str] = field(default_factory=list)
    total_universe: int = 0
    delisted_count: int = 0          # 在该日期已退市的数量
    newly_listed_count: int = 0      # 在该日期新上市的数量
    generated_at: Optional[datetime] = None


# ─────────────────────────────────────────
#  幸存者偏差追踪器
# ─────────────────────────────────────────


class SurvivorshipBiasTracker:
    """
    幸存者偏差追踪器。

    维护全量标的生命周期记录，支持：
    1. 按日期生成动态标的池
    2. 查询特定标的的存续状态
    3. 导入/导出退市标的记录

    用法:
        tracker = SurvivorshipBiasTracker()
        await tracker.load_from_futu()  # 从 Futu 导入
        universe = tracker.get_universe_on(date(2020, 1, 1))
    """

    def __init__(self):
        self._lifecycles: Dict[str, TickerLifecycle] = {}
        self._loaded = False
        self._load_time: Optional[float] = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def total_records(self) -> int:
        return len(self._lifecycles)

    @property
    def delisted_count(self) -> int:
        return sum(1 for lc in self._lifecycles.values() if lc.status == ListingStatus.DELISTED)

    # ─────────────────────────────────
    #  数据导入
    # ─────────────────────────────────

    def add_ticker(self, lifecycle: TickerLifecycle) -> None:
        """添加或更新标的生命周期记录"""
        lifecycle.updated_at = datetime.utcnow()
        self._lifecycles[lifecycle.symbol] = lifecycle

    def add_batch(self, lifecycles: List[TickerLifecycle]) -> int:
        """批量添加标的记录"""
        for lc in lifecycles:
            self.add_ticker(lc)
        logger.info(f"[DQ-01] 批量导入 {len(lifecycles)} 条标的记录")
        return len(lifecycles)

    def remove_ticker(self, symbol: str) -> bool:
        """移除标的记录"""
        if symbol in self._lifecycles:
            del self._lifecycles[symbol]
            return True
        return False

    def get_lifecycle(self, symbol: str) -> Optional[TickerLifecycle]:
        """获取标的生命周期记录"""
        return self._lifecycles.get(symbol)

    # ─────────────────────────────────
    #  标的池生成
    # ─────────────────────────────────

    def get_universe_on(self, check_date: date) -> UniverseSnapshot:
        """
        生成指定日期的标的池快照。

        核心方法：只返回在 check_date 当天实际存续的标的。
        这是消除幸存者偏差的关键——回测时必须调用此方法
        而非使用当前存续列表。
        """
        alive_tickers = []
        delisted_count = 0

        for symbol, lc in self._lifecycles.items():
            if lc.is_alive_on(check_date):
                alive_tickers.append(symbol)
            elif lc.status == ListingStatus.DELISTED:
                delisted_count += 1

        snapshot = UniverseSnapshot(
            as_of_date=check_date,
            tickers=sorted(alive_tickers),
            total_universe=len(alive_tickers),
            delisted_count=delisted_count,
            generated_at=datetime.utcnow(),
        )

        logger.debug(
            f"[DQ-01] 标的池快照 {check_date}: "
            f"存续={snapshot.total_universe}, 已退市={delisted_count}"
        )
        return snapshot

    def get_universe_diff(self, from_date: date, to_date: date) -> Dict[str, Any]:
        """
        计算两个日期之间的标的池变动。

        Returns:
            {
                "added": [...],      # 新上市/恢复交易的标的
                "removed": [...],    # 退市/摘牌的标的
                "net_change": int,
            }
        """
        from_universe = set(self.get_universe_on(from_date).tickers)
        to_universe = set(self.get_universe_on(to_date).tickers)

        added = sorted(to_universe - from_universe)
        removed = sorted(from_universe - to_universe)

        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "added": added,
            "removed": removed,
            "net_change": len(added) - len(removed),
        }

    # ─────────────────────────────────
    #  存续状态查询
    # ─────────────────────────────────

    def is_alive(self, symbol: str, check_date: Optional[date] = None) -> bool:
        """判断标的在指定日期是否存续"""
        lc = self._lifecycles.get(symbol)
        if lc is None:
            return False  # 不在记录中的标的默认为不存在
        if check_date is None:
            check_date = date.today()
        return lc.is_alive_on(check_date)

    def get_delisted_tickers(self, as_of: Optional[date] = None) -> List[str]:
        """获取截至指定日期已退市的所有标的"""
        if as_of is None:
            as_of = date.today()
        return sorted([
            symbol for symbol, lc in self._lifecycles.items()
            if lc.status == ListingStatus.DELISTED and lc.delist_date and lc.delist_date <= as_of
        ])

    def get_survivorship_stats(self, check_date: Optional[date] = None) -> Dict[str, Any]:
        """获取幸存者偏差统计信息"""
        if check_date is None:
            check_date = date.today()

        total = len(self._lifecycles)
        alive = sum(1 for lc in self._lifecycles.values() if lc.is_alive_on(check_date))
        delisted = sum(
            1 for lc in self._lifecycles.values()
            if lc.status == ListingStatus.DELISTED
        )
        suspended = sum(
            1 for lc in self._lifecycles.values()
            if lc.status == ListingStatus.SUSPENDED
        )

        return {
            "as_of_date": check_date.isoformat(),
            "total_records": total,
            "alive_on_date": alive,
            "delisted_total": delisted,
            "suspended_total": suspended,
            "survivorship_rate": alive / total if total > 0 else 0.0,
            "bias_if_ignoring_delisted": f"+{(total - alive) / total * 100:.1f}%" if total > 0 else "0%",
        }

    # ─────────────────────────────────
    #  CSV 导入/导出
    # ─────────────────────────────────

    def load_from_csv(self, filepath: str) -> int:
        """
        从 CSV 文件导入退市标的记录。

        CSV 格式:
            symbol,name,market,list_date,delist_date,status,delist_reason
            US.LEH,Lehman Brothers,US,1850-01-01,2008-09-15,delisted,bankruptcy
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"[DQ-01] CSV 文件不存在: {filepath}")
            return 0

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("symbol", "").strip()
                if not symbol:
                    continue

                list_date = None
                delist_date = None
                if row.get("list_date"):
                    try:
                        list_date = datetime.strptime(row["list_date"], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                if row.get("delist_date"):
                    try:
                        delist_date = datetime.strptime(row["delist_date"], "%Y-%m-%d").date()
                    except ValueError:
                        pass

                status_str = row.get("status", "unknown").lower()
                try:
                    status = ListingStatus(status_str)
                except ValueError:
                    status = ListingStatus.UNKNOWN

                lc = TickerLifecycle(
                    symbol=symbol,
                    name=row.get("name", ""),
                    market=row.get("market", ""),
                    list_date=list_date,
                    delist_date=delist_date,
                    status=status,
                    delist_reason=row.get("delist_reason", ""),
                    source="csv",
                )
                self.add_ticker(lc)
                count += 1

        self._loaded = True
        self._load_time = time.time()
        logger.info(f"[DQ-01] 从 CSV 导入 {count} 条退市标的记录: {filepath}")
        return count

    def export_to_csv(self, filepath: str) -> int:
        """导出所有标的记录到 CSV"""
        path = Path(filepath)
        count = 0

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["symbol", "name", "market", "list_date", "delist_date", "status", "delist_reason"],
            )
            writer.writeheader()
            for lc in self._lifecycles.values():
                writer.writerow({
                    "symbol": lc.symbol,
                    "name": lc.name,
                    "market": lc.market,
                    "list_date": lc.list_date.isoformat() if lc.list_date else "",
                    "delist_date": lc.delist_date.isoformat() if lc.delist_date else "",
                    "status": lc.status.value,
                    "delist_reason": lc.delist_reason,
                })
                count += 1

        logger.info(f"[DQ-01] 导出 {count} 条标的记录到: {filepath}")
        return count

    def export_snapshot(self) -> Dict[str, Any]:
        """DQ-03b：导出 universe sidecar JSON（供快照捆绑）。"""
        symbols = []
        for lc in self._lifecycles.values():
            symbols.append(
                {
                    "symbol": lc.symbol,
                    "market": lc.market,
                    "status": lc.status.value if hasattr(lc.status, "value") else str(lc.status),
                    "list_date": lc.list_date.isoformat() if lc.list_date else None,
                    "delist_date": lc.delist_date.isoformat() if lc.delist_date else None,
                }
            )
        return {
            "symbols": symbols,
            "symbol_count": len(symbols),
            "exported_at": datetime.utcnow().isoformat() + "Z",
        }

    # ─────────────────────────────────
    #  从数据源导入
    # ─────────────────────────────────

    async def load_from_futu(self, futu_service_instance: Any = None) -> int:
        """
        从 Futu OpenD 导入全市场标的信息。

        Futu get_stock_basicinfo 返回的 DataFrame 包含：
        - code: 标的代码
        - name: 名称
        - listing_date: 上市日期
        - delisting_date: 退市日期（如有）
        """
        if futu_service_instance is None:
            from backend.services.futu import futu_service
            futu_service_instance = futu_service

        count = 0
        for market in ["HK", "US"]:
            for sec_type in ["STOCK", "ETF"]:
                try:
                    result = await futu_service_instance.get_stock_basicinfo(market, sec_type)
                    if result.get("status") != "success":
                        continue

                    for row in result.get("data", []):
                        symbol = row.get("code", "")
                        if not symbol:
                            continue

                        # 解析上市/退市日期
                        list_date = None
                        delist_date = None
                        if row.get("listing_date"):
                            try:
                                list_date = datetime.strptime(str(row["listing_date"])[:10], "%Y-%m-%d").date()
                            except (ValueError, TypeError):
                                pass
                        if row.get("delisting_date"):
                            try:
                                delist_date = datetime.strptime(str(row["delisting_date"])[:10], "%Y-%m-%d").date()
                            except (ValueError, TypeError):
                                pass

                        # 判断状态
                        if delist_date and delist_date <= date.today():
                            status = ListingStatus.DELISTED
                        else:
                            status = ListingStatus.LISTED

                        lc = TickerLifecycle(
                            symbol=symbol,
                            name=row.get("name", ""),
                            market=market,
                            list_date=list_date,
                            delist_date=delist_date,
                            status=status,
                            source="futu",
                        )
                        self.add_ticker(lc)
                        count += 1

                except Exception as e:
                    logger.warning(f"[DQ-01] Futu 导入 {market}/{sec_type} 失败: {e}")

        self._loaded = True
        self._load_time = time.time()
        logger.info(f"[DQ-01] 从 Futu 导入 {count} 条标的记录")
        return count

    def mark_loaded(self) -> None:
        """标记数据已加载（用于测试）"""
        self._loaded = True
        self._load_time = time.time()


# ─────────────────────────────────────────
#  全局单例
# ─────────────────────────────────────────

_survivorship_tracker: Optional[SurvivorshipBiasTracker] = None


def get_survivorship_tracker() -> SurvivorshipBiasTracker:
    """获取全局幸存者偏差追踪器单例"""
    global _survivorship_tracker
    if _survivorship_tracker is None:
        _survivorship_tracker = SurvivorshipBiasTracker()
    return _survivorship_tracker


# ─────────────────────────────────────────
#  便捷函数
# ─────────────────────────────────────────


def get_universe_for_backtest(
    check_date: date,
    tracker: Optional[SurvivorshipBiasTracker] = None,
) -> List[str]:
    """
    获取回测用的标的池（消除幸存者偏差）。

    这是回测引擎应该调用的入口函数——
    传入回测日期，返回当日实际存续的所有标的。

    ⚠️ 严禁用当前存续列表替代此函数！
    """
    if tracker is None:
        tracker = get_survivorship_tracker()
    snapshot = tracker.get_universe_on(check_date)
    return snapshot.tickers
