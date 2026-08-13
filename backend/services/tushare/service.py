"""
Tushare 数据源服务（独立数据源 · A股主源）

职责：
- 封装 Tushare Pro API 的 A股日线历史、实时行情、基本面、沪深港通资金流向
- token 从环境变量 TUSHARE_TOKEN 读取，禁止写死在代码里
- 机房 IP 不被东财反爬封禁，比 akshare(新浪源) 更稳定，作为 A股主源

数据接口范围（2000积分 / 200元 档，每分钟 200 次、每日每 API 10 万次）：
- 基础数据: 股票列表 stock_basic（120积分）
- A股日线历史: pro_bar / daily
- 低频行情: 周线 weekly / 月线 monthly
- A股实时行情: rt_k（实时快照，无积分权限时降级 daily_basic+daily）
- 基本面: 每日指标 daily_basic / 利润表 income / 资产负债表 balancesheet / 现金流量表 cashflow / 财务指标 fina_indicator（财务类限 80次/分）
- 沪深港通资金流向: moneyflow_hsgt
- 宏观经济: cn_gdp / cn_cpi / cn_ppi / cn_money_supply / cn_shibor

运行模式（DATASOURCE_TUSHARE_MODE）：internal（默认直连）/ external（远程 HTTP，待扩展）
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional


def _is_hk_ticker(ticker: str) -> bool:
    """识别港股代码（HK.00700 / 00700.HK / 5位港股代码）。Tushare 仅支持 A 股。"""
    s = (ticker or "").strip().upper()
    if s.startswith("HK.") or s.endswith(".HK"):
        return True
    return False


# ── 频次保护（2000 积分 / 200元 档位限制）─────────────────────
# 档位统一：每分钟 200 次；财务三大报表接口独立限制 80 次/分（接口文档明示）
# 用令牌桶（秒级滑动）限速，避免触发 Tushare 429 熔断
_RPM_LIMITS: Dict[str, int] = {
    "default": 200,  # 2000 档通用上限
    "finance": 80,  # income/balancesheet/cashflow 每分钟 80 次
}
# 各接口归属分组
_API_GROUP: Dict[str, str] = {
    "stock_basic": "default",
    "daily": "default",
    "weekly": "default",
    "monthly": "default",
    "daily_basic": "default",
    "rt_k": "default",
    "moneyflow_hsgt": "default",
    "income": "finance",
    "balancesheet": "finance",
    "cashflow": "finance",
    "fina_indicator": "finance",
    "cn_gdp": "default",
    "cn_cpi": "default",
    "cn_ppi": "default",
    "cn_money_supply": "default",
    "cn_shibor": "default",
}


class TushareError(Exception):
    """Tushare 业务层异常。"""

    def __init__(self, message: str, category: str = "NORMAL") -> None:
        super().__init__(message)
        self.category = category  # NORMAL | IP_BLOCKED | QUOTA_EXHAUSTED | RATE_LIMIT


class TushareService:
    """Tushare Pro API 服务封装（2000积分档）。"""

    def __init__(self, token: Optional[str] = None) -> None:
        self._token = token or os.getenv("TUSHARE_TOKEN", "")
        self._mode = os.getenv("DATASOURCE_TUSHARE_MODE", "internal")
        self._pro = None
        self._started_at = time.monotonic()
        self._error_count = 0
        self._max_errors = 3
        # 令牌桶：{group: [timestamp, ...]}，线程安全
        self._buckets: Dict[str, list] = {g: [] for g in _RPM_LIMITS}
        self._bucket_lock = threading.Lock()

    # ── 初始化 ───────────────────────────────────────────────
    def _ensure_pro(self):
        """惰性初始化 pro_api；缺 token 直接抛错（不可重试）。"""
        if self._pro is not None:
            return self._pro
        if not self._token:
            raise TushareError("TUSHARE_TOKEN 未配置", category="NO_TOKEN")
        try:
            import tushare as ts

            # 关键：tushare 底层走 requests，会读 env 代理。
            # 若本机残留失效代理(如 127.0.0.1:10808)会卡死请求，
            # 这里强制清空，保证直连 tushare.pro
            for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                os.environ.pop(k, None)
            os.environ["NO_PROXY"] = "*"
            ts.set_token(self._token)
            self._pro = ts.pro_api()
        except Exception as e:  # noqa: BLE001
            raise TushareError(f"Tushare 初始化失败({type(e).__name__}): {e}", category="INIT_FAILED")
        return self._pro

    # ── 工具 ─────────────────────────────────────────────────
    @staticmethod
    def _to_ts_code(ticker: str) -> str:
        """将多种格式统一成 Tushare ts_code（如 600519.SH / 000001.SZ）。

        支持输入：SH.600519 / SZ.000001 / 600519 / 600519.SH
        """
        t = str(ticker).strip().upper()
        if t.endswith(".SH") or t.endswith(".SZ"):
            return t
        if t.startswith("SH."):
            return f"{t[3:]}.SH"
        if t.startswith("SZ."):
            return f"{t[3:]}.SZ"
        # 纯数字：按规则判断市场
        code = t.zfill(6)
        if code.startswith(("60", "68", "90", "88")):
            return f"{code}.SH"
        if code.startswith(("00", "30", "20", "15")):
            return f"{code}.SZ"
        # 默认上海（如指数/ETF 类），调用方可显式传 .SZ
        return f"{code}.SH"

    # ── 频次保护（令牌桶）────────────────────────────────────
    def _check_rate_limit(self, api_name: str) -> None:
        """令牌桶限速：超 2000 档每分钟上限则抛 RATE_LIMIT。

        分组：finance 类 80次/分，其余 200次/分。
        """
        group = _API_GROUP.get(api_name, "default")
        limit = _RPM_LIMITS.get(group, 200)
        now = time.monotonic()
        with self._bucket_lock:
            bucket = self._buckets[group]
            # 清理 60s 外的记录
            bucket[:] = [t for t in bucket if now - t < 60]
            if len(bucket) >= limit:
                raise TushareError(
                    f"Tushare {group} 接口达每分钟 {limit} 次上限，触发本地限速",
                    category="RATE_LIMIT",
                )
            bucket.append(now)

    # ── A股日线历史 ──────────────────────────────────────────
    def get_daily_history(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        num: int = 100,
        adj: str = "qfq",
    ) -> Dict[str, Any]:
        """A股日线历史（pro_bar，支持前/后复权）。

        Args:
            ticker: 标的（SH.600519 / 600519 / 600519.SH）
            start_date / end_date: YYYYMMDD 或 YYYY-MM-DD
            num: 取最近 N 根（未给日期区间时生效）
            adj: qfq(前复权) / hfq(后复权) / None(不复权)
        """
        ts_code = self._to_ts_code(ticker)
        try:
            import tushare as ts

            pro = self._ensure_pro()
            # pro_bar 走 bar 接口，支持复权
            adj_arg = None if adj in (None, "none", "") else adj
            df = ts.pro_bar(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                asset="E",
                adj=adj_arg,
                ma=[],
            )
            if df is None or df.empty:
                if start_date is None and end_date is None:
                    # 兜底：用 daily 接口取最近 num 根
                    self._check_rate_limit("daily")
                    df = pro.daily(ts_code=ts_code)
                if df is None or df.empty:
                    return {"success": True, "data": [], "source": "tushare"}

            df = df.sort_values("trade_date").tail(num)
            klines = []
            for _, row in df.iterrows():
                klines.append(
                    {
                        "datetime": str(row.get("trade_date", "")),
                        "open": float(row.get("open", 0) or 0),
                        "high": float(row.get("high", 0) or 0),
                        "low": float(row.get("low", 0) or 0),
                        "close": float(row.get("close", 0) or 0),
                        "volume": int(row.get("vol", 0) or 0),
                        "amount": float(row.get("amount", 0) or 0),
                    }
                )
            return {"success": True, "data": klines, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── A股实时行情（当日快照）─────────────────────────────
    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """A股实时行情快照。

        Tushare 实时行情走 rt_k（需 5000 积分），免费用户降级用
        daily_basic 当日指标 + 最新交易日收盘价近似。
        """
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            # 优先尝试 rt_k（实时）
            try:
                self._check_rate_limit("rt_k")
                df = pro.rt_k(ts_code=ts_code)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    return {
                        "success": True,
                        "data": {
                            "ticker": ticker,
                            "price": float(row.get("price", 0) or 0),
                            "change": float(row.get("change", 0) or 0),
                            "change_pct": float(row.get("pct_change", 0) or 0),
                            "volume": int(row.get("vol", 0) or 0),
                            "amount": float(row.get("amount", 0) or 0),
                            "high": float(row.get("high", 0) or 0),
                            "low": float(row.get("low", 0) or 0),
                            "open": float(row.get("open", 0) or 0),
                            "prev_close": float(row.get("pre_close", 0) or 0),
                        },
                        "source": "tushare",
                    }
            except Exception:  # noqa: BLE001
                # rt_k 无权限时降级
                pass

            # 降级：daily_basic 当日指标 + daily 收盘价
            self._check_rate_limit("daily")
            df_d = pro.daily(ts_code=ts_code, limit=1)
            if df_d is None or df_d.empty:
                return {
                    "success": False,
                    "message": "无当日行情数据（可能非交易日或权限不足）",
                    "category": "NORMAL",
                    "source": "tushare",
                }
            d = df_d.iloc[0]
            quote = {
                "ticker": ticker,
                "price": float(d.get("close", 0) or 0),
                "change": float(d.get("pct_chg", 0) or 0),  # daily 无 change 字段，用 pct_chg
                "change_pct": float(d.get("pct_chg", 0) or 0),
                "volume": int(d.get("vol", 0) or 0),
                "amount": float(d.get("amount", 0) or 0),
                "high": float(d.get("high", 0) or 0),
                "low": float(d.get("low", 0) or 0),
                "open": float(d.get("open", 0) or 0),
                "prev_close": float(d.get("pre_close", 0) or 0),
                "realtime": False,
            }
            return {"success": True, "data": quote, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 基本面 ───────────────────────────────────────────────
    def get_daily_basic(self, ticker: str, trade_date: Optional[str] = None) -> Dict[str, Any]:
        """每日指标（PE/PB/换手率/市值等）。"""
        if _is_hk_ticker(ticker):
            return {
                "success": False,
                "message": f"Tushare 不支持港股 {ticker}",
                "category": "UNSUPPORTED",
                "source": "tushare",
            }
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("daily_basic")
            if trade_date:
                df = pro.daily_basic(ts_code=ts_code, trade_date=trade_date)
            else:
                df = pro.daily_basic(
                    ts_code=ts_code,
                    fields="ts_code,trade_date,close,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,turnover_rate,total_mv,circ_mv",
                )
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            rows = []
            for _, row in df.iterrows():
                rows.append(
                    {
                        "ts_code": row.get("ts_code"),
                        "trade_date": str(row.get("trade_date", "")),
                        "close": float(row.get("close", 0) or 0),
                        "pe": float(row.get("pe", 0) or 0),
                        "pe_ttm": float(row.get("pe_ttm", 0) or 0),
                        "pb": float(row.get("pb", 0) or 0),
                        "ps": float(row.get("ps", 0) or 0),
                        "ps_ttm": float(row.get("ps_ttm", 0) or 0),
                        "dv_ratio": float(row.get("dv_ratio", 0) or 0),
                        "turnover_rate": float(row.get("turnover_rate", 0) or 0),
                        "total_mv": float(row.get("total_mv", 0) or 0),
                        "circ_mv": float(row.get("circ_mv", 0) or 0),
                    }
                )
            return {"success": True, "data": rows, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    def get_income(self, ticker: str, period: Optional[str] = None) -> Dict[str, Any]:
        """利润表（指定报告期，如 20231231）。"""
        if _is_hk_ticker(ticker):
            return {
                "success": False,
                "message": f"Tushare 不支持港股 {ticker}",
                "category": "UNSUPPORTED",
                "source": "tushare",
            }
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("income")
            kwargs: Dict[str, Any] = {"ts_code": ts_code}
            if period:
                kwargs["period"] = period
            df = pro.income(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    def get_fina_indicator(self, ticker: str, period: Optional[str] = None) -> Dict[str, Any]:
        """财务指标（ROE/毛利率/负债率等）。"""
        if _is_hk_ticker(ticker):
            return {
                "success": False,
                "message": f"Tushare 不支持港股 {ticker}",
                "category": "UNSUPPORTED",
                "source": "tushare",
            }
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("fina_indicator")
            kwargs: Dict[str, Any] = {"ts_code": ts_code}
            if period:
                kwargs["period"] = period
            df = pro.fina_indicator(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 沪深港通资金流向 ─────────────────────────────────────
    def get_moneyflow_hsgt(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """沪深港通资金流向（北向/南向净买入）。"""
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("moneyflow_hsgt")
            kwargs: Dict[str, Any] = {}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            df = pro.moneyflow_hsgt(**kwargs) if kwargs else pro.moneyflow_hsgt()
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            df = df.sort_values("trade_date")
            rows = []
            for _, row in df.iterrows():
                rows.append(
                    {
                        "trade_date": str(row.get("trade_date", "")),
                        "north_money": float(row.get("north_money", 0) or 0),
                        "south_money": float(row.get("south_money", 0) or 0),
                        "north_net_buy": float(row.get("north_net_buy", 0) or 0),
                        "south_net_buy": float(row.get("south_net_buy", 0) or 0),
                    }
                )
            return {"success": True, "data": rows, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 基础数据：股票列表（stock_basic, 120积分）─────────────
    def get_stock_basic(
        self,
        list_status: str = "L",
        exchange: Optional[str] = None,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        """股票基础列表（沪A/深A/北交所）。

        Args:
            list_status: L上市 / D退市 / P暂停上市
            exchange: SSE上交所 / SZSE深交所 / BSE北交所（不传取全部）
            fields: 逗号分隔字段，默认 ts_code,name,industry,market,list_date
        """
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("stock_basic")
            kwargs: Dict[str, Any] = {"list_status": list_status}
            if exchange:
                kwargs["exchange"] = exchange
            if fields:
                kwargs["fields"] = fields
            df = pro.stock_basic(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 低频行情：周线 / 月线 ─────────────────────────────────
    def get_lowfreq_history(
        self,
        ticker: str,
        freq: str = "weekly",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        num: int = 100,
    ) -> Dict[str, Any]:
        """周线/月线历史（weekly / monthly 接口，2000积分档）。

        Args:
            freq: weekly(周) / monthly(月)
            num: 取最近 N 根
        """
        api = "weekly" if freq == "weekly" else "monthly"
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit(api)
            df = getattr(pro, api)(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            df = df.sort_values("trade_date" if "trade_date" in df.columns else "cal_date").tail(num)
            klines = []
            date_col = "trade_date" if "trade_date" in df.columns else "cal_date"
            for _, row in df.iterrows():
                klines.append(
                    {
                        "datetime": str(row.get(date_col, "")),
                        "open": float(row.get("open", 0) or 0),
                        "high": float(row.get("high", 0) or 0),
                        "low": float(row.get("low", 0) or 0),
                        "close": float(row.get("close", 0) or 0),
                        "volume": int(row.get("vol", 0) or 0),
                        "amount": float(row.get("amount", 0) or 0),
                    }
                )
            return {"success": True, "data": klines, "source": "tushare", "freq": freq}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 三大报表补全：资产负债表 / 现金流量表 ─────────────────
    def get_balancesheet(self, ticker: str, period: Optional[str] = None) -> Dict[str, Any]:
        """资产负债表（balancesheet）。"""
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("balancesheet")
            kwargs: Dict[str, Any] = {"ts_code": ts_code}
            if period:
                kwargs["period"] = period
            df = pro.balancesheet(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    def get_cashflow(self, ticker: str, period: Optional[str] = None) -> Dict[str, Any]:
        """现金流量表（cashflow）。"""
        ts_code = self._to_ts_code(ticker)
        try:
            pro = self._ensure_pro()
            self._check_rate_limit("cashflow")
            kwargs: Dict[str, Any] = {"ts_code": ts_code}
            if period:
                kwargs["period"] = period
            df = pro.cashflow(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 宏观经济（cn_* 系列，2000积分档）─────────────────────
    def get_macro(self, api_name: str, **kwargs: Any) -> Dict[str, Any]:
        """宏观经济数据统一入口。

        支持：cn_gdp / cn_cpi / cn_ppi / cn_money_supply / cn_shibor
        其余接口按需透传 kwargs（如 start_date/end_date、freq 等）。
        """
        allowed = {"cn_gdp", "cn_cpi", "cn_ppi", "cn_money_supply", "cn_shibor"}
        if api_name not in allowed:
            return {
                "success": False,
                "message": f"不支持的宏观接口: {api_name}",
                "category": "NORMAL",
                "source": "tushare",
            }
        try:
            pro = self._ensure_pro()
            self._check_rate_limit(api_name)
            df = getattr(pro, api_name)(**kwargs)
            if df is None or df.empty:
                return {"success": True, "data": [], "source": "tushare"}
            records = df.where(df.notna(), None).to_dict(orient="records")
            return {"success": True, "data": records, "source": "tushare"}
        except TushareError as e:
            return {"success": False, "message": str(e), "category": e.category, "source": "tushare"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e), "category": "NORMAL", "source": "tushare"}

    # ── 健康 ─────────────────────────────────────────────────
    def get_health_status(self) -> Dict[str, Any]:
        if not self._token:
            return {"name": "Tushare (A股主源)", "status": "no_token", "message": "TUSHARE_TOKEN 未配置"}
        try:
            pro = self._ensure_pro()
            # 轻量探测：取一只股票最近 1 天日线
            df = pro.daily(ts_code="600519.SH", limit=1)
            healthy = df is not None
            return {
                "name": "Tushare (A股主源)",
                "status": "healthy" if healthy else "error",
                "success": healthy,
                "mode": self._mode,
                "message": "正常" if healthy else "探测返回空",
            }
        except TushareError as e:
            return {
                "name": "Tushare (A股主源)",
                "status": "error",
                "success": False,
                "message": str(e),
                "category": e.category,
            }
        except Exception as e:  # noqa: BLE001
            return {"name": "Tushare (A股主源)", "status": "error", "success": False, "message": str(e)}


# 单例
tushare_service = TushareService()
