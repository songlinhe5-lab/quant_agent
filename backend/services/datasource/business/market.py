"""
行情领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「行情」语义的封装：get_quote / get_history /
get_fund_flow / get_option_chain。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class MarketDataService:
    """行情领域业务适配器：封装行情相关策略（ticker 校验、ktype 映射、期权过滤）。

    策略逻辑收敛于此层；薄适配器只负责连底层 + 基础检测。
    """

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_quote(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """行情快照：含 ticker 基础校验 + 多源融合 + Stale 检测 + 归一化。"""
        self._validate_ticker(ticker)
        return await self._facade.get_quote(ticker, prefer_sources=prefer_sources)

    async def get_history(
        self,
        ticker: str,
        ktype: str = "K_DAY",
        num: int = 60,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """历史 K 线：ktype 归一（K_DAY/K_MIN 等 → 数据源可接受枚举）+ OHLCV 归一化。"""
        self._validate_ticker(ticker)
        norm_ktype = self._normalize_ktype(ktype)
        return await self._facade.get_history(ticker, ktype=norm_ktype, num=num, prefer_sources=prefer_sources)

    async def get_fund_flow(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """当日主力资金净流入 + 经纪商买卖盘席位。"""
        self._validate_ticker(ticker)
        return await self._facade.get_fund_flow(ticker, prefer_sources=prefer_sources)

    async def get_capital_distribution(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """G3：主力筹码分层 + 背离信号（产品级聚合，供筹码图与告警消费）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_capital_distribution(ticker, prefer_sources=prefer_sources)

    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权链 + OCC 合约代码；expiration_date 为空时由源返回最近到期链。"""
        self._validate_ticker(ticker)
        return await self._facade.get_option_chain(
            ticker, expiration_date=expiration_date, prefer_sources=prefer_sources
        )

    # ── 行情领域策略原语 ──

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        """ticker 基础校验：非空、去除首尾空白、禁止注入式字符。"""
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")
        clean = str(ticker).strip()
        if any(ch in clean for ch in (";", "'", '"', "--", "/*", "*/")):
            raise ValueError(f"ticker 含非法字符: {clean!r}")
        if clean != ticker:
            # 调用方应传干净 ticker；这里仅防御
            pass

    @staticmethod
    def _normalize_ktype(ktype: str) -> str:
        """ktype 归一：统一为大写下划线风格（K_DAY / K_WEEK / K_MIN_1 ...）。"""
        k = str(ktype).strip().upper().replace("-", "_")
        mapping = {
            "DAY": "K_DAY",
            "D": "K_DAY",
            "WEEK": "K_WEEK",
            "W": "K_WEEK",
            "MONTH": "K_MON",
            "M": "K_MON",
            "MIN": "K_MIN_1",
            "1MIN": "K_MIN_1",
            "5MIN": "K_MIN_5",
            "15MIN": "K_MIN_15",
            "30MIN": "K_MIN_30",
            "60MIN": "K_MIN_60",
        }
        return mapping.get(k, k if k.startswith("K_") else f"K_{k}")


# 领域单例
market_data_service = MarketDataService()
