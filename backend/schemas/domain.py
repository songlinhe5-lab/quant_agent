"""
Pydantic v2 领域模型（BE-14）

按 docs/11 定义 Quote/Kline/Position/Order/Account/TechIndicators 等 Schema，
作为 API 出入参强类型校验。

对齐前端类型定义：frontend/src/types/domain.ts
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────
# 基础枚举
# ─────────────────────────────────────────────


class Market(str, Enum):
    US = "US"
    HK = "HK"
    SH = "SH"
    SZ = "SZ"
    SG = "SG"
    JP = "JP"
    CN = "CN"


class SecurityType(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    OPTION = "OPTION"
    FUTURE = "FUTURE"
    INDEX = "INDEX"
    CRYPTO = "CRYPTO"


class KlinePeriod(str, Enum):
    K_1M = "K_1M"
    K_5M = "K_5M"
    K_15M = "K_15M"
    K_30M = "K_30M"
    K_1H = "K_1H"
    K_DAY = "K_DAY"
    K_WEEK = "K_WEEK"
    K_MONTH = "K_MONTH"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderTIF(str, Enum):
    """订单有效时间 (Time in Force)"""

    DAY = "DAY"
    GTC = "GTC"  # Good Till Canceled
    GTD = "GTD"  # Good Till Date
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


# ─────────────────────────────────────────────
# 标的信息
# ─────────────────────────────────────────────


class SymbolModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., description="标的代码，如 HK.00700")
    name: str = Field(..., description="标的名称")
    market: Market = Field(..., description="所属市场")
    security_type: SecurityType = Field(..., alias="securityType", description="证券类型")  # noqa: E501
    lot_size: Optional[int] = Field(None, alias="lotSize", description="每手股数")
    currency: Optional[str] = Field(None, description="计价货币")


# ─────────────────────────────────────────────
# 行情数据
# ─────────────────────────────────────────────


class QuoteModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    symbol: str = Field(..., description="标的代码")
    last_price: float = Field(..., alias="lastPrice", description="最新价")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    prev_close: float = Field(..., alias="prevClose", description="昨收价")
    volume: int = Field(..., description="成交量")
    turnover: float = Field(..., description="成交额")
    change: float = Field(..., description="涨跌额")
    change_percent: float = Field(..., alias="changePercent", description="涨跌幅")

    # 盘口数据
    bid_price: Optional[float] = Field(None, alias="bidPrice", description="买一价")
    bid_volume: Optional[int] = Field(None, alias="bidVolume", description="买一量")
    ask_price: Optional[float] = Field(None, alias="askPrice", description="卖一价")
    ask_volume: Optional[int] = Field(None, alias="askVolume", description="卖一量")

    # 时间戳
    timestamp: int = Field(..., description="UTC 毫秒时间戳")
    source: Optional[str] = Field(None, description="数据来源")


class KlineModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    timestamp: int = Field(..., description="UTC 毫秒时间戳")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: int = Field(..., description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")


class KlineSeriesModel(BaseModel):
    symbol: str = Field(..., description="标的代码")
    period: KlinePeriod = Field(..., description="K线周期")
    klines: List[KlineModel] = Field(..., description="K线数据列表")


class TickModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: int = Field(..., description="UTC 毫秒时间戳")
    price: float = Field(..., description="成交价")
    volume: int = Field(..., description="成交量")
    bid: Optional[float] = Field(None, description="买一价")
    ask: Optional[float] = Field(None, description="卖一价")
    bid_size: Optional[int] = Field(None, alias="bidSize", description="买一量")
    ask_size: Optional[int] = Field(None, alias="askSize", description="卖一量")


# ─────────────────────────────────────────────
# 持仓与订单
# ─────────────────────────────────────────────


class PositionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(..., description="持仓ID")
    symbol: str = Field(..., description="标的代码")
    side: PositionSide = Field(..., description="持仓方向")
    quantity: float = Field(..., description="持仓数量")
    avg_cost: float = Field(..., alias="avgCost", description="持仓均价")
    current_price: float = Field(..., alias="currentPrice", description="当前价格")
    market_value: float = Field(..., alias="marketValue", description="持仓市值")
    unrealized_pnl: float = Field(..., alias="unrealizedPnL", description="未实现盈亏")
    realized_pnl: float = Field(..., alias="realizedPnL", description="已实现盈亏")
    unrealized_pnl_percent: float = Field(..., alias="unrealizedPnLPercent", description="未实现盈亏百分比")  # noqa: E501
    status: PositionStatus = Field(..., description="持仓状态")
    opened_at: int = Field(..., alias="openedAt", description="开仓时间（UTC 毫秒）")
    updated_at: int = Field(..., alias="updatedAt", description="更新时间（UTC 毫秒）")


class OrderModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(..., description="订单ID")
    symbol: str = Field(..., description="标的代码")
    side: OrderSide = Field(..., description="订单方向")
    type: OrderType = Field(..., description="订单类型")
    quantity: float = Field(..., description="订单数量")
    price: Optional[float] = Field(None, description="限价单价格")
    stop_price: Optional[float] = Field(None, alias="stopPrice", description="止损单触发价")  # noqa: E501
    filled_quantity: float = Field(..., alias="filledQuantity", description="已成交数量")  # noqa: E501
    filled_avg_price: Optional[float] = Field(None, alias="filledAvgPrice", description="成交均价")  # noqa: E501
    status: OrderStatus = Field(..., description="订单状态")
    created_at: int = Field(..., alias="createdAt", description="创建时间（UTC 毫秒）")
    updated_at: int = Field(..., alias="updatedAt", description="更新时间（UTC 毫秒）")

    # 模拟/实盘标识
    is_paper: bool = Field(..., alias="isPaper", description="是否模拟盘")
    strategy_id: Optional[str] = Field(None, alias="strategyId", description="策略ID")


# ─────────────────────────────────────────────
# 账户信息
# ─────────────────────────────────────────────


class AccountModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str = Field(..., alias="accountId", description="账户ID")
    total_assets: float = Field(..., alias="totalAssets", description="总资产")
    cash: float = Field(..., description="现金")
    market_value: float = Field(..., alias="marketValue", description="持仓市值")
    buying_power: float = Field(..., alias="buyingPower", description="购买力")
    unrealized_pnl: float = Field(..., alias="unrealizedPnL", description="未实现盈亏")
    realized_pnl: float = Field(..., alias="realizedPnL", description="已实现盈亏")
    daily_pnl: float = Field(..., alias="dailyPnL", description="当日盈亏")
    daily_pnl_percent: float = Field(..., alias="dailyPnLPercent", description="当日盈亏百分比")  # noqa: E501
    currency: str = Field(..., description="货币单位")
    updated_at: int = Field(..., alias="updatedAt", description="更新时间（UTC 毫秒）")


# ─────────────────────────────────────────────
# 技术指标
# ─────────────────────────────────────────────


class IndicatorType(str, Enum):
    MA = "MA"
    EMA = "EMA"
    MACD = "MACD"
    RSI = "RSI"
    KDJ = "KDJ"
    BOLL = "BOLL"
    ATR = "ATR"
    VWAP = "VWAP"


class IndicatorParams(BaseModel):
    period: Optional[int] = Field(None, description="周期")
    fast_period: Optional[int] = Field(None, alias="fastPeriod", description="快线周期")
    slow_period: Optional[int] = Field(None, alias="slowPeriod", description="慢线周期")
    signal_period: Optional[int] = Field(None, alias="signalPeriod", description="信号周期")  # noqa: E501
    multiplier: Optional[float] = Field(None, description="乘数")


class TechIndicatorsModel(BaseModel):
    type: IndicatorType = Field(..., description="指标类型")
    params: IndicatorParams = Field(..., description="指标参数")
    values: List[Dict[str, float]] = Field(..., description="每个时间点的指标值")
    signal: Optional[str] = Field(None, description="买卖信号")


# ─────────────────────────────────────────────
# 选股相关
# ─────────────────────────────────────────────


class ScreenerFilterModel(BaseModel):
    market: Optional[List[Market]] = Field(None, description="市场过滤")
    security_type: Optional[List[SecurityType]] = Field(None, alias="securityType", description="证券类型过滤")  # noqa: E501
    min_market_cap: Optional[float] = Field(None, alias="minMarketCap", description="最小市值")  # noqa: E501
    max_market_cap: Optional[float] = Field(None, alias="maxMarketCap", description="最大市值")  # noqa: E501
    min_pe: Optional[float] = Field(None, alias="minPE", description="最小市盈率")
    max_pe: Optional[float] = Field(None, alias="maxPE", description="最大市盈率")
    min_pb: Optional[float] = Field(None, alias="minPB", description="最小市净率")
    max_pb: Optional[float] = Field(None, alias="maxPB", description="最大市净率")
    min_volume: Optional[float] = Field(None, alias="minVolume", description="最小成交量")  # noqa: E501
    min_change_percent: Optional[float] = Field(None, alias="minChangePercent", description="最小涨跌幅")  # noqa: E501
    max_change_percent: Optional[float] = Field(None, alias="maxChangePercent", description="最大涨跌幅")  # noqa: E501
    indicators: Optional[Dict[str, Dict[str, float]]] = Field(None, description="技术指标过滤")  # noqa: E501


class ScreenerResultModel(BaseModel):
    symbol: str = Field(..., description="标的代码")
    name: str = Field(..., description="标的名称")
    market: Market = Field(..., description="所属市场")
    last_price: float = Field(..., alias="lastPrice", description="最新价")
    change_percent: float = Field(..., alias="changePercent", description="涨跌幅")
    volume: float = Field(..., description="成交量")
    market_cap: Optional[float] = Field(None, alias="marketCap", description="市值")
    pe: Optional[float] = Field(None, description="市盈率")
    pb: Optional[float] = Field(None, description="市净率")
    indicators: Optional[Dict[str, float]] = Field(None, description="技术指标值")


# ─────────────────────────────────────────────
# 策略相关
# ─────────────────────────────────────────────


class StrategyModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="策略ID")
    name: str = Field(..., description="策略名称")
    description: Optional[str] = Field(None, description="策略描述")
    status: StrategyStatus = Field(..., description="策略状态")
    code: str = Field(..., description="策略代码")
    params: Optional[Dict[str, Any]] = Field(None, description="策略参数")
    created_at: int = Field(..., alias="createdAt", description="创建时间（UTC 毫秒）")
    updated_at: int = Field(..., alias="updatedAt", description="更新时间（UTC 毫秒）")


# ─────────────────────────────────────────────
# WebSocket 消息
# ─────────────────────────────────────────────


class WSSubscribeMessageModel(BaseModel):
    type: str = Field(..., description="消息类型")
    topic: str = Field(..., description="订阅主题")
    symbol: Optional[str] = Field(None, description="标的代码")


class WSQuoteMessageModel(BaseModel):
    type: str = Field(..., description="消息类型")
    data: QuoteModel = Field(..., description="行情数据")


class WSKlineMessageModel(BaseModel):
    type: str = Field(..., description="消息类型")
    data: KlineSeriesModel = Field(..., description="K线数据")


# ─────────────────────────────────────────────
# 统一 API 响应结构
# ─────────────────────────────────────────────


class ApiResponseModel(BaseModel):
    code: int = Field(..., description="业务错误码，0 表示成功")
    msg: str = Field(..., description="可读消息")
    data: Any = Field(..., description="响应数据")
    ts: int = Field(..., description="UTC 毫秒时间戳")


class PaginatedResponseModel(BaseModel):
    items: List[Any] = Field(..., description="数据列表")
    total: int = Field(..., description="总数量")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., alias="pageSize", description="每页数量")
    has_more: bool = Field(..., alias="hasMore", description="是否有更多数据")


# ─────────────────────────────────────────────
# 客户端 APM 心跳（BE-08）
# ─────────────────────────────────────────────


class ClientHeartbeatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    platform: str = Field(..., description="客户端平台（flutter/web/desktop）")
    app_version: str = Field(..., alias="appVersion", description="应用版本")
    device_id: str = Field(..., alias="deviceId", description="设备ID")
    fps: Optional[float] = Field(None, description="帧率")
    memory_mb: Optional[float] = Field(None, alias="memoryMb", description="内存占用（MB）")  # noqa: E501
    ws_latency_ms: Optional[int] = Field(None, alias="wsLatencyMs", description="WebSocket 延迟（ms）")  # noqa: E501
    # OBS-03 / FE-27: Web Vitals（可选，Web 端上报）
    lcp_ms: Optional[float] = Field(None, alias="lcpMs", description="Largest Contentful Paint (ms)")
    cls: Optional[float] = Field(None, description="Cumulative Layout Shift（无量纲）")
    inp_ms: Optional[float] = Field(None, alias="inpMs", description="Interaction to Next Paint (ms)")
    ttfb_ms: Optional[float] = Field(None, alias="ttfbMs", description="Time to First Byte (ms)")
    timestamp: int = Field(..., description="UTC 毫秒时间戳")
