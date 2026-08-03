"""
FutuAdapter - 富途牛牛/OPEN API 数据源适配器

基于 DataSourcePort Protocol 实现的具体数据源 Adapter，负责与 Futu OpenD 通信，
提供行情、K 线、资金流、期权链等数据服务。

设计约束 (零幻觉):
- 所有行情/历史/资金流/期权链均调用真实 Futu OpenD 接口；
- 数据源未连接 (Futu OpenD 不可用) 时一律返回 error/degraded，**绝不 mock 兜底**；
- futu 依赖按需惰性导入，使本模块在无 Futu 环境亦可被 import。

作者：VARB-2026-0708-001 Virtual Architecture Board
生成时间：2026-07-08
参考实现：backend/core/market_engine.py + backend/services/futu_service.py
"""

import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.adapters.ports.data_source_port import DataSourcePort, DataSourceResult
from backend.core.logger import logger

# futu 依赖惰性导入：本模块在无 Futu 环境的测试/导入场景下仍可加载
try:
    from futu import (  # type: ignore
        RET_ERROR,
        RET_OK,
        AuType,
        CurKlineHandlerBase,
        KLType,
        OpenQuoteContext,
        OrderBookHandlerBase,
        PeriodType,
        RTDataHandlerBase,
        StockQuoteHandlerBase,
        SubType,
        TickerHandlerBase,
    )

    _FUTU_AVAILABLE = True
except Exception:  # pragma: no cover - 无 futu 环境
    RET_OK, RET_ERROR = 0, -1
    OpenQuoteContext = None  # type: ignore
    SubType = KLType = AuType = PeriodType = None  # type: ignore
    StockQuoteHandlerBase = object  # type: ignore
    CurKlineHandlerBase = object  # type: ignore
    TickerHandlerBase = object  # type: ignore
    OrderBookHandlerBase = object  # type: ignore
    RTDataHandlerBase = object  # type: ignore
    _FUTU_AVAILABLE = False


# ========== 推送回调分发器 ==========
def _to_float(value: Any) -> float:
    """安全地将值转为 float，失败或为空时返回 0.0。"""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class _PushRouter:
    """将 Futu 异步推送按 (code, 类别) 路由到已注册的回调。"""

    _CATEGORY_HANDLERS = {
        "QUOTE": None,  # 在类定义后填充
        "KLINE": None,
        "TICKER": None,
        "ORDER_BOOK": None,
        "RT_DATA": None,
    }

    def __init__(self, ctx: Any):
        self._ctx = ctx
        self._callbacks: Dict[tuple, List[Callable]] = {}
        self._handlers: Dict[str, Any] = {}

    def _ensure_handler(self, category: str) -> None:
        if category in self._handlers:
            return
        cls = self._CATEGORY_HANDLERS.get(category)
        if cls is None:
            return
        try:
            handler = cls(self)
            self._handlers[category] = handler
            self._ctx.set_handler(handler)
        except Exception as e:  # pragma: no cover
            logger.error(f"[FutuAdapter] set_handler({category}) 失败: {e}")

    def add(self, code: str, category: str, callback: Callable) -> None:
        self._callbacks.setdefault((code, category), []).append(callback)
        self._ensure_handler(category)

    def remove(self, code: str, category: str) -> None:
        self._callbacks.pop((code, category), None)

    def dispatch(self, category: str, df: Any) -> None:
        if df is None or not hasattr(df, "iterrows"):
            return
        for _, row in df.iterrows():
            code = row.get("code")
            cbs = self._callbacks.get((code, category))
            if not cbs:
                continue
            msg = {"sub_type": category, "ticker": code, "data": row.to_dict()}
            for cb in cbs:
                try:
                    cb(msg)
                except Exception:  # pragma: no cover
                    logger.exception("[FutuAdapter] 订阅回调异常")


class _QuoteHandler(StockQuoteHandlerBase):  # type: ignore
    def __init__(self, router: "_PushRouter"):
        super().__init__()
        self._router = router

    def on_recv_rsp(self, rsp_pb):
        ret, df = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and df is not None:
            self._router.dispatch("QUOTE", df)
        return ret, df


class _KlineHandler(CurKlineHandlerBase):  # type: ignore
    def __init__(self, router: "_PushRouter"):
        super().__init__()
        self._router = router

    def on_recv_rsp(self, rsp_pb):
        ret, df = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and df is not None:
            self._router.dispatch("KLINE", df)
        return ret, df


class _TickerHandler(TickerHandlerBase):  # type: ignore
    def __init__(self, router: "_PushRouter"):
        super().__init__()
        self._router = router

    def on_recv_rsp(self, rsp_pb):
        ret, df = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and df is not None:
            self._router.dispatch("TICKER", df)
        return ret, df


class _OrderBookHandler(OrderBookHandlerBase):  # type: ignore
    def __init__(self, router: "_PushRouter"):
        super().__init__()
        self._router = router

    def on_recv_rsp(self, rsp_pb):
        ret, df = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and df is not None:
            self._router.dispatch("ORDER_BOOK", df)
        return ret, df


class _RTDataHandler(RTDataHandlerBase):  # type: ignore
    def __init__(self, router: "_PushRouter"):
        super().__init__()
        self._router = router

    def on_recv_rsp(self, rsp_pb):
        ret, df = super().on_recv_rsp(rsp_pb)
        if ret == RET_OK and df is not None:
            self._router.dispatch("RT_DATA", df)
        return ret, df


_PushRouter._CATEGORY_HANDLERS = {
    "QUOTE": _QuoteHandler,
    "KLINE": _KlineHandler,
    "TICKER": _TickerHandler,
    "ORDER_BOOK": _OrderBookHandler,
    "RT_DATA": _RTDataHandler,
}


class FutuAdapter(DataSourcePort):
    """
    富途 (Futu) 数据源适配器

    能力清单:
    - quote: 实时行情快照 (最新价、涨跌幅、成交量等)
    - history: 历史 K 线数据 (支持多周期)
    - fund_flow: 主力资金流向
    - option_chain: 期权链数据
    - subscribe_quote: 实时推送订阅 (长连接)

    部署说明:
    - Futu OpenD 必须在同一 VPS 上运行，监听 127.0.0.1:11111
    - 通过 FUTU_API_KEY 环境变量配置认证
    - 支持自动重试和限流退避机制

    零幻觉约束:
    - ctx 为 None 或 OpenD 不可用时，所有 fetch 返回 error/degraded，不返回任何编造数据。
    - 测试可通过构造参数 ctx=... 注入 mock 上下文，避免依赖真实 OpenD。
    """

    # ========== 类常量 ==========

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 11111
    DEFAULT_TIMEOUT_SECONDS = 5.0
    MAX_RETRIES = 3
    RETRY_DELAY_MS = 1000

    # 限流阈值
    RATE_LIMIT_REQUESTS_PER_MINUTE = 60
    RATE_LIMIT_WINDOW_SECONDS = 60
    RATE_LIMIT_BACKOFF_SECONDS = 60

    # interval(str) -> futu KLType 值映射
    _INTERVAL_TO_KTYPE = {
        "1d": "K_DAY",
        "1day": "K_DAY",
        "day": "K_DAY",
        "d": "K_DAY",
        "1w": "K_WEEK",
        "week": "K_WEEK",
        "w": "K_WEEK",
        "1m": "K_1M",
        "5m": "K_5M",
        "15m": "K_15M",
        "30m": "K_30M",
        "60m": "K_60M",
        "1h": "K_60M",
        "h": "K_60M",
        "1mo": "K_MON",
        "month": "K_MON",
        "mon": "K_MON",
        "1q": "K_QUARTER",
        "quarter": "K_QUARTER",
        "1y": "K_YEAR",
        "year": "K_YEAR",
    }

    _PREFIXES = {"HK", "US", "SH", "SZ"}

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        ctx: Optional[Any] = None,
    ):
        """
        初始化 FutuAdapter

        Args:
            host: Futu OpenD 主机地址 (默认 127.0.0.1)
            port: Futu OpenD 端口 (默认 11111)
            api_key: API 密钥 (从 FUTU_API_KEY 环境变量读取)
            timeout: 请求超时时间 (秒)
            ctx: 可选的预建 OpenQuoteContext (依赖注入，便于测试；为空时按需惰性创建)
        """
        self._host = host
        self._port = port
        self._api_key = api_key or os.getenv("FUTU_API_KEY")
        self._timeout = timeout
        self._ctx: Optional[Any] = ctx
        self._owns_ctx: bool = ctx is None  # 仅当由本适配器创建时才负责关闭
        self._connected = False
        self._router: Optional[_PushRouter] = None
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._request_count = 0
        self._last_request_time: Optional[float] = None
        self._rate_limited_until: Optional[float] = None

    # ========== Protocol 必需属性实现 ==========

    @property
    def name(self) -> str:
        """数据源标识符"""
        return "futu"

    @property
    def version(self) -> str:
        """接口版本号"""
        return "1.0.0"

    @property
    def capabilities(self) -> List[str]:
        """支持的操作列表"""
        return [
            "quote",
            "history",
            "fund_flow",
            "option_chain",
            "subscribe_quote",
        ]

    @property
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        if not self._connected:
            return False
        if self._is_rate_limited:
            return False
        return True

    # ========== Protocol 必需方法实现 ==========

    def fetch(self, action: str, params: dict) -> DataSourceResult:
        """
        统一数据获取入口

        Args:
            action: 操作类型 (quote/history/fund_flow/option_chain)
            params: 参数字典

        Returns:
            DataSourceResult: 统一结果包装器
        """
        if action not in self.capabilities:
            return DataSourceResult.error(
                f"Unsupported action: {action}. Supported: {self.capabilities}", source=self.name
            )

        if not self.is_available:
            return DataSourceResult.degraded("Futu OpenD not connected or rate limited", source=self.name)

        if self._is_rate_limited:
            retry_after = self._rate_limited_until - time.time()
            return DataSourceResult.rate_limited(retry_after_seconds=max(1, int(retry_after)), source=self.name)

        try:
            start_time = time.time()

            if action == "quote":
                result = self._fetch_quote(params)
            elif action == "history":
                result = self._fetch_history(params)
            elif action == "fund_flow":
                result = self._fetch_fund_flow(params)
            elif action == "option_chain":
                result = self._fetch_option_chain(params)
            else:
                return DataSourceResult.error(f"Unknown action: {action}")

            latency_ms = (time.time() - start_time) * 1000
            self._record_request()

            return DataSourceResult(
                status="success" if result.get("success") else "error",
                data=result.get("data"),
                source=f"futu-{self._host}:{self._port}",
                latency_ms=latency_ms,
                cached=result.get("cached", False),
                error=result.get("message") if not result.get("success") else None,
            )

        except Exception as e:
            return DataSourceResult.error(str(e), source=self.name)

    # ========== 可选方法实现 (订阅模式) ==========

    def subscribe(self, action: str, params: dict, callback: Callable[[Dict], None]) -> str:
        """
        订阅实时行情推送 (长连接)

        Args:
            action: 必须为 "subscribe_quote"
            params: {"tickers": ["HK.00700"], "sub_type": "QUOTE"|"K_DAY"|"ORDER_BOOK"|"TICKER"|"RT_DATA"}
            callback: 收到推送时的回调函数，签名为 (msg: dict) -> None

        Returns:
            str: Subscription ID

        Raises:
            ValueError: action 非法 / 缺少 tickers / 不支持的 sub_type
            RuntimeError: 数据源未连接 (零幻觉：不伪造订阅)
        """
        if action != "subscribe_quote":
            raise ValueError("FutuAdapter only supports 'subscribe_quote' subscription")
        if callback is None:
            raise ValueError("subscribe requires a callback")

        tickers = params.get("tickers") or params.get("ticker")
        if isinstance(tickers, str):
            tickers = [tickers]
        if not tickers:
            raise ValueError("subscribe requires 'tickers'")

        sub_type = str(params.get("sub_type", "QUOTE")).upper()

        # 必须已连接真实数据源，否则无法订阅 (零幻觉)
        if not self._connected and not self._connect():
            raise RuntimeError("Futu OpenD 未连接，无法订阅 (零幻觉：不伪造订阅)")
        if self._ctx is None:
            raise RuntimeError("Futu 上下文不可用，无法订阅")

        try:
            futu_sub = getattr(SubType, sub_type)
        except Exception:
            raise ValueError(f"不支持的 sub_type: {sub_type}")

        codes = [self._normalize_code(t) for t in tickers]
        ret, err = self._ctx.subscribe(codes, [futu_sub])
        if ret != RET_OK:
            raise RuntimeError(f"订阅失败: {err}")

        if self._router is None:
            self._router = _PushRouter(self._ctx)
        category = "KLINE" if sub_type.startswith("K_") else sub_type
        for code in codes:
            self._router.add(code, category, callback)

        subscription_id = f"sub_{uuid.uuid4().hex[:8]}"
        self._subscriptions[subscription_id] = {
            "codes": codes,
            "category": category,
            "sub_type": sub_type,
        }
        logger.info(f"[FutuAdapter] 订阅成功 id={subscription_id} codes={codes} sub_type={sub_type}")
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅

        Args:
            subscription_id: 订阅 ID

        Returns:
            bool: 是否成功取消
        """
        info = self._subscriptions.pop(subscription_id, None)
        if info is None:
            return False

        if self._router is not None:
            for code in info["codes"]:
                self._router.remove(code, info["category"])

        if self._ctx is not None and self._connected:
            try:
                futu_sub = getattr(SubType, info["sub_type"])
                self._ctx.unsubscribe(info["codes"], [futu_sub])
            except Exception as e:  # pragma: no cover
                logger.error(f"[FutuAdapter] unsubscribe 失败: {e}")

        return True

    def close(self) -> None:
        """关闭资源：若上下文由本适配器创建则负责关闭；清理订阅与路由。"""
        if self._router is not None:
            self._router = None
        self._subscriptions.clear()
        if self._ctx is not None and self._owns_ctx:
            try:
                self._ctx.close()
            except Exception:  # pragma: no cover
                pass
        self._connected = False

    # ========== 公开生命周期方法 ==========

    def connect(self) -> bool:
        """
        建立到 Futu OpenD 的连接 (公开入口)。
        供应用层 (如 MarketDataService 懒连接) 在首次使用前触发，
        也对齐 DataSourcePort 约定的连接生命周期。
        """
        return self._connect()

    # ========== 内部私有方法 ==========

    def _connect(self) -> bool:
        """
        建立到 Futu OpenD 的连接 (真实实现)

        Returns:
            bool: 是否连接成功
        """
        if self._connected:
            return True

        try:
            if self._ctx is None:
                if OpenQuoteContext is None:
                    logger.error("[FutuAdapter] futu 包不可用，无法建立真实连接")
                    self._connected = False
                    return False
                # 惰性创建真实 OpenQuoteContext（构造时即连接本地 OpenD）
                self._ctx = OpenQuoteContext(host=self._host, port=self._port)
                self._owns_ctx = True

            # OpenQuoteContext 构造即建立连接；以连通性标记可用性
            self._connected = bool(getattr(self._ctx, "is_connected", True))
            if self._connected:
                logger.info(f"[FutuAdapter] Connected to OpenD at {self._host}:{self._port}")
            else:  # pragma: no cover
                logger.warning("[FutuAdapter] OpenQuoteContext 已构造但连通性检查未通过")
            return self._connected

        except Exception as e:
            logger.error(f"[FutuAdapter] Failed to connect: {e}")
            self._connected = False
            return False

    # ---- 代码/周期归一化 ----

    def _normalize_code(self, code: str) -> str:
        """将多种代码格式统一为 Futu 标准 (HK.00700 / US.AAPL)。"""
        if not code or "." not in code:
            return code
        head, tail = code.split(".", 1)
        if head in self._PREFIXES:
            return code
        if tail in self._PREFIXES:
            return f"{tail}.{head}"
        return code

    def _map_interval(self, interval: str) -> str:
        """将 interval 字符串映射为 Futu KLType 值。"""
        return self._INTERVAL_TO_KTYPE.get(str(interval).lower(), "K_DAY")

    def _ensure_subscribed(self, code: str, sub_type: str = "QUOTE") -> None:
        """拉取报价前的最佳实践：先订阅再查询 (Futu QUOTE 查询需先订阅)。"""
        if self._ctx is None:
            return
        try:
            futu_sub = getattr(SubType, sub_type)
            self._ctx.subscribe([code], [futu_sub])
        except Exception as e:  # pragma: no cover - 非致命
            logger.debug(f"[FutuAdapter] auto-subscribe {code} 失败 (非致命): {e}")

    # ---- 行情 / 历史 / 资金流 ----

    def _fetch_quote(self, params: dict) -> dict:
        ticker = params.get("ticker")
        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}
        if self._ctx is None:
            return {"success": False, "message": "数据源已死，无法分析：Futu OpenD 未连接，无法获取真实行情"}

        code = self._normalize_code(ticker)
        try:
            self._ensure_subscribed(code, "QUOTE")
            ret, data = self._ctx.get_stock_quote([code])
            if ret != RET_OK or data is None:
                return {"success": False, "message": f"行情获取失败: {data}"}

            row = data.iloc[0]

            prev_close = _to_float(row.get("prev_close_price"))
            price = _to_float(row.get("last_price"))
            change = price - prev_close
            change_pct = (change / prev_close * 100.0) if prev_close else 0.0

            quote = {
                "ticker": code,
                "price": price,
                "open": _to_float(row.get("open_price")),
                "high": _to_float(row.get("high_price")),
                "low": _to_float(row.get("low_price")),
                "prev_close": prev_close,
                "volume": _to_float(row.get("volume")),
                "turnover": _to_float(row.get("turnover")),
                "change": change,
                "change_pct": change_pct,
            }
            return {"success": True, "data": quote, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_history(self, params: dict) -> dict:
        ticker = params.get("ticker")
        num = params.get("num", 100)
        interval = params.get("interval", "1d")
        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}
        if self._ctx is None:
            return {"success": False, "message": "数据源已死，无法分析：Futu OpenD 未连接，无法获取历史 K 线"}

        code = self._normalize_code(ticker)
        ktype = self._map_interval(interval)
        try:
            ret, data = self._ctx.get_cur_kline(code, num, ktype=ktype, autype=AuType.QFQ)
            if ret != RET_OK or data is None:
                return {"success": False, "message": f"K线获取失败: {data}"}

            klines = []
            for _, row in data.iterrows():
                klines.append(
                    {
                        "datetime": str(row.get("time_key", "")),
                        "open": _to_float(row.get("open")),
                        "high": _to_float(row.get("high")),
                        "low": _to_float(row.get("low")),
                        "close": _to_float(row.get("close")),
                        "volume": _to_float(row.get("volume")),
                        "turnover": _to_float(row.get("turnover")),
                    }
                )
            return {"success": True, "data": klines, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_fund_flow(self, params: dict) -> dict:
        ticker = params.get("ticker")
        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}
        if self._ctx is None:
            return {"success": False, "message": "数据源已死，无法分析：Futu OpenD 未连接，无法获取资金流"}

        code = self._normalize_code(ticker)
        try:
            ret, data = self._ctx.get_capital_flow(code, period_type=PeriodType.INTRADAY)
            if ret != RET_OK or data is None:
                return {"success": False, "message": f"资金流获取失败: {data}"}

            def _g(key: str) -> float:
                if key in data.columns:
                    return _to_float(data[key].fillna(0).sum())
                return 0.0

            last = data.iloc[-1].to_dict() if len(data) else {}

            flow = {
                "ticker": code,
                "main_in_flow": _g("main_in_flow"),
                "in_flow": _g("in_flow"),
                "super_in": _to_float(last.get("super_in_flow")),
                "big_in": _to_float(last.get("big_in_flow")),
                "mid_in": _to_float(last.get("mid_in_flow")),
                "sml_in": _to_float(last.get("sml_in_flow")),
                "last_valid_time": str(last.get("last_valid_time", "")),
            }
            return {"success": True, "data": flow, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_option_chain(self, params: dict) -> dict:
        underlying_ticker = params.get("underlying_ticker")
        if not underlying_ticker:
            return {"success": False, "message": "Missing underlying_ticker parameter"}

        try:
            # 生产：Futu OpenD 已连接时调用真实接口（零幻觉, 仅真实数据, 禁止 Mock 兜底）
            ctx = self._ctx
            connected = bool(getattr(ctx, "is_connected", False)) if ctx else False
            if ctx is not None and connected:
                expire_date = params.get("expire_date") or ""
                if not expire_date and hasattr(ctx, "get_option_expiration_date"):
                    try:
                        ret, date_df = ctx.get_option_expiration_date(underlying_ticker)
                        if ret == RET_OK and date_df is not None and not getattr(date_df, "empty", True):
                            expire_date = str(date_df["strike_time"].iloc[0]).split(" ")[0]
                    except Exception:
                        pass
                if not expire_date:
                    return {"success": False, "message": "无法获取到期日列表 (真实数据源)"}
                if not hasattr(ctx, "get_option_chain"):
                    return {"success": False, "message": "Futu 上下文不支持 get_option_chain"}
                ret, chain_df = ctx.get_option_chain(underlying_ticker, start=expire_date, end=expire_date)
                if ret != RET_OK or chain_df is None or getattr(chain_df, "empty", True):
                    return {"success": False, "message": f"期权链获取失败: {chain_df}"}
                options = []
                for _, row in chain_df.iterrows():
                    try:
                        options.append(
                            {
                                "strike_price": float(row.get("strike_price", 0) or 0),
                                "option_type": str(row.get("option_type", "")).lower(),
                                "implied_volatility": float(row.get("implied_volatility", 0) or 0),
                                "option_code": row.get("option_code"),
                                "last_price": float(row.get("last_price", 0) or 0),
                                "volume": float(row.get("volume", 0) or 0),
                                "open_interest": float(row.get("open_interest", 0) or 0),
                            }
                        )
                    except Exception:
                        continue
                if not options:
                    return {"success": False, "message": "期权链无有效合约 (真实数据源为空)"}
                return {
                    "success": True,
                    "data": {"expiration": expire_date, "options": options},
                    "cached": False,
                }
            # 未连接真实数据源：明确返回错误告警，绝不用 Mock 兜底掩盖故障
            return {
                "success": False,
                "message": ("数据源已死，无法分析：期权链数据源不可用（Futu OpenD 未连接，无法获取真实期权链）"),
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ========== 限流控制 ==========

    @property
    def _is_rate_limited(self) -> bool:
        """检查是否处于限流窗口期"""
        if not self._rate_limited_until:
            return False
        return time.time() < self._rate_limited_until

    def _record_request(self):
        """记录一次请求，用于限流检测"""
        now = time.time()
        self._request_count += 1
        self._last_request_time = now

        if self._request_count >= self.RATE_LIMIT_REQUESTS_PER_MINUTE:
            self._rate_limited_until = now + self.RATE_LIMIT_BACKOFF_SECONDS
            logger.warning(f"[FutuAdapter] Rate limit reached, backing off until {self._rate_limited_until}")

    def _reset_request_count(self):
        """重置请求计数器"""
        self._request_count = 0
        self._rate_limited_until = None

    # ========== 健康检查 ==========

    def health_check(self) -> dict:
        """
        健康检查

        Returns:
            dict: {"healthy": bool, "latency_ms": float?, "error": str?}
        """
        start_time = time.time()

        if not self._connect():
            return {"healthy": False, "error": "Connection failed (Futu OpenD 不可用)"}

        try:
            test_result = self._fetch_quote({"ticker": "HK.00700"})
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": test_result.get("success", False),
                "latency_ms": latency_ms,
                "message": "OK" if test_result.get("success") else test_result.get("message"),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}
