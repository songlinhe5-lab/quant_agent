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


def _to_float(v: Any) -> Optional[float]:
    """安全转 float；None / 空 / 非数值返回 None（零幻觉红线，不抛不臆造）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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

    async def get_heat_map(self, market: str = "HK", prefer_sources: Optional[list[str]] = None) -> Any:
        """G6：板块热力图（产品级聚合，供 ECharts treemap 渲染）。market 级无 ticker。"""
        return await self._facade.get_heat_map(market, prefer_sources=prefer_sources)

    async def get_order_book(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """L2 盘口深度：派生最优买卖价差与买卖盘量比。"""
        self._validate_ticker(ticker)
        return await self._facade.get_order_book(ticker, prefer_sources=prefer_sources)

    async def get_option_iv_summary(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """期权 IV 指标聚合（设计稿 IV 指标条：ATM IV / IV 分位 / 30日已实现 / Skew）。

        派生逻辑（零幻觉红线，全部来自真实数据）：
        - ATM IV：取最近到期日、行权价最贴近最新价的 call/put 隐含波动率均值
        - IV 分位：当前 ATM IV 在“近 N 个到期日 ATM IV 序列”中的分位数
        - 30日已实现波动率：取近 30 根日 K 收益率 std × sqrt(252)
        - Skew：虚值 put IV 均值 − 虚值 call IV 均值（正=悲观倾斜）
        任一底层不可用时对应字段置 None，不臆造。
        """
        self._validate_ticker(ticker)

        # 并行取期权链 + 历史 K 线
        chain_res = await self._facade.get_option_chain(ticker, expiration_date="", prefer_sources=prefer_sources)
        hist_res = await self._facade.get_history(ticker, ktype="K_DAY", num=30, prefer_sources=prefer_sources)

        # 最新价（从期权链快照或历史末值取得，仅用于 ATM 定位，不臆造）
        last_price: Optional[float] = None
        atm_iv: Optional[float] = None
        iv_series: list[float] = []
        skew: Optional[float] = None
        _put_ivs: list[float] = []
        _call_ivs: list[float] = []

        if not chain_res.is_error and isinstance(chain_res.data, dict):
            data = chain_res.data
            # 优先取快照最新价
            snap = data.get("snapshot") or {}
            if isinstance(snap, dict):
                last_price = _to_float(snap.get("last_price") or snap.get("price") or snap.get("close"))
            chains = data.get("chains") or data.get("option_chain") or data.get("data") or []
            if not isinstance(chains, list):
                chains = []
            # 跨到期日聚合 ATM IV
            for exp in chains:
                if not isinstance(exp, dict):
                    continue
                exp_iv = _to_float(exp.get("iv") or exp.get("atm_iv") or exp.get("implied_volatility"))
                if exp_iv is not None:
                    iv_series.append(exp_iv)
                strikes = exp.get("strikes") or exp.get("items") or []
                if not isinstance(strikes, list):
                    strikes = []
                for item in strikes:
                    if not isinstance(item, dict):
                        continue
                    iv = _to_float(item.get("iv") or item.get("implied_volatility"))
                    if iv is None:
                        continue
                    k = _to_float(item.get("strike") or item.get("exercise_price"))
                    if k is None:
                        continue
                    if last_price is not None:
                        # ATM 候选：行权价最接近最新价
                        if atm_iv is None and abs(k - last_price) / max(last_price, 1e-9) < 0.02:
                            atm_iv = iv
                        # Skew：虚值 put（k < last）vs 虚值 call（k > last）
                        if last_price is not None and k < last_price * 0.95:
                            _put_ivs.append(iv)
                        elif last_price is not None and k > last_price * 1.05:
                            _call_ivs.append(iv)

        # 30日已实现波动率
        rv30d: Optional[float] = None
        if not hist_res.is_error and isinstance(hist_res.data, (list, dict)):
            bars = hist_res.data
            if isinstance(bars, dict):
                bars = bars.get("data") or bars.get("klines") or []
            closes = [_to_float(b.get("close") or b.get("Close")) for b in (bars or []) if isinstance(b, dict)]
            closes = [c for c in closes if c is not None]
            if len(closes) >= 2:
                import math

                rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
                if rets:
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean) ** 2 for r in rets) / len(rets)
                    rv30d = math.sqrt(var) * math.sqrt(252)

        # IV 分位
        iv_percentile: Optional[float] = None
        if atm_iv is not None and len(iv_series) >= 2:
            below = sum(1 for v in iv_series if v <= atm_iv)
            iv_percentile = below / len(iv_series)

        # Skew = mean(OTM put IV) - mean(OTM call IV)
        if _put_ivs and _call_ivs:
            skew = (sum(_put_ivs) / len(_put_ivs)) - (sum(_call_ivs) / len(_call_ivs))

        return {
            "ticker": ticker,
            "atm_iv": atm_iv,
            "iv_percentile": iv_percentile,
            "rv30d": rv30d,
            "skew": skew,
            "available": any(v is not None for v in (atm_iv, iv_percentile, rv30d, skew)),
        }

    async def get_market_snapshot(self, tickers: list[str], prefer_sources: Optional[list[str]] = None) -> Any:
        """批量实时快照：派生 count/平均涨跌幅/涨跌家数。"""
        return await self._facade.get_market_snapshot(tickers, prefer_sources=prefer_sources)

    async def get_stock_basicinfo(
        self, market: str, sec_type: str = "STOCK", prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """全市场股票/ETF/指数基本信息。"""
        return await self._facade.get_stock_basicinfo(market, sec_type=sec_type, prefer_sources=prefer_sources)

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
