"""
Quant Agent Pydantic v2 领域模型（对齐 docs/11 核心领域对象）

所有 API 出入参强类型校验均使用此处定义的 Schema。
严禁在各路由文件中内联定义重复的 Pydantic 模型。
"""
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ==========================================
#  枚举类型
# ==========================================

class Market(str, Enum):
    """市场标识"""
    US = "US"
    HK = "HK"
    SH = "SH"
    SZ = "SZ"
    CRYPTO = "CRYPTO"


class KlinePeriod(str, Enum):
    """K 线周期"""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    M60 = "60m"
    D1 = "D1"
    W1 = "W1"
    MO1 = "M1"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderTIF(str, Enum):
    """Time-In-Force（订单有效期）"""
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class BrokerType(str, Enum):
    FUTU = "futu"
    SIMULATION = "simulation"


# ==========================================
#  核心领域模型
# ==========================================

class SymbolModel(BaseModel):
    """标的信息"""
    model_config = ConfigDict(frozen=True)

    futu_code: str = Field(..., description="Futu 格式主键，如 US.AAPL")
    display_code: str = Field(..., description="展示用代码，如 AAPL 或 00700")
    name: str = Field(..., description="标的名称")
    market: Market
    currency: str = Field(..., description="货币代码，如 USD / HKD / CNY")
    lot_size: int = Field(default=1, description="每手股数（港股 500，美股 1）")


class QuoteModel(BaseModel):
    """实时报价快照"""
    symbol: str = Field(..., description="Futu 格式 symbol")
    price: float
    change: float = Field(default=0.0)
    change_pct: float = Field(default=0.0, description="涨跌幅（0.0056 = 0.56%）")
    open: float = Field(default=0.0)
    high: float = Field(default=0.0)
    low: float = Field(default=0.0)
    prev_close: float = Field(default=0.0)
    volume: int = Field(default=0, description="成交量（股）")
    turnover: float = Field(default=0.0, description="成交额（原始货币）")
    bid: float = Field(default=0.0, description="买一价")
    ask: float = Field(default=0.0, description="卖一价")
    bid_vol: int = Field(default=0, description="买一量")
    ask_vol: int = Field(default=0, description="卖一量")
    ts: int = Field(..., description="UTC 毫秒时间戳")


class KlineModel(BaseModel):
    """单根 K 线"""
    ts: int = Field(..., description="K 线开始时间（UTC 毫秒）")
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(default=0)
    turnover: float = Field(default=0.0)


class KlineSeriesModel(BaseModel):
    """K 线序列"""
    symbol: str
    period: KlinePeriod
    klines: List[KlineModel] = Field(default_factory=list)
    source: Literal["redis_cache", "duckdb_cache", "futu_api", "yfinance_fallback"] = "futu_api"


class PositionModel(BaseModel):
    """持仓"""
    symbol: str
    name: str = ""
    qty: int = Field(..., description="持仓数量")
    avg_cost: float = Field(..., description="平均成本")
    current_price: float = Field(default=0.0)
    market_value: float = Field(default=0.0, description="当前市值")
    unrealized_pnl: float = Field(default=0.0)
    unrealized_pnl_pct: float = Field(default=0.0)
    today_pnl: float = Field(default=0.0, description="今日盈亏")
    cost_ratio: float = Field(default=0.0, description="仓位占比")
    currency: str = Field(default="USD")


class OrderModel(BaseModel):
    """订单"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: int
    filled_qty: int = Field(default=0)
    price: Optional[float] = Field(default=None, description="limit 价，market 单为 null")
    avg_fill_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    tif: OrderTIF = OrderTIF.DAY
    note: str = ""
    created_at: int = Field(..., description="UTC 毫秒时间戳")
    updated_at: int = Field(..., description="UTC 毫秒时间戳")
    is_simulated: bool = Field(default=True, description="沙箱单 or 实盘单")


class AccountModel(BaseModel):
    """账户概况"""
    account_id: str
    broker: BrokerType = BrokerType.SIMULATION
    currency: str = Field(default="USD")
    total_asset: float = Field(default=0.0)
    cash: float = Field(default=0.0)
    market_value: float = Field(default=0.0)
    unrealized_pnl: float = Field(default=0.0)
    unrealized_pnl_pct: float = Field(default=0.0)
    today_pnl: float = Field(default=0.0)
    leverage: float = Field(default=1.0, description="实际杠杆倍数")
    buying_power: float = Field(default=0.0, description="可用购买力")
    updated_at: int = Field(..., description="UTC 毫秒时间戳")


# ==========================================
#  技术指标模型
# ==========================================

class MACDResultModel(BaseModel):
    macd: float
    signal: float
    histogram: float


class BollingerBandsModel(BaseModel):
    upper: float
    middle: float
    lower: float
    bandwidth: float = Field(default=0.0)


class KDJModel(BaseModel):
    k: float
    d: float
    j: float


class TechIndicatorsModel(BaseModel):
    """技术指标计算结果"""
    symbol: str
    period: KlinePeriod
    ts: int = Field(..., description="UTC 毫秒时间戳")
    close: float
    ma: Dict[str, float] = Field(default_factory=dict, description='如 {"MA5": 210.1}')
    ema: Dict[str, float] = Field(default_factory=dict)
    rsi: Dict[str, float] = Field(default_factory=dict, description='如 {"RSI14": 58.3}')
    macd: MACDResultModel
    kdj: KDJModel
    boll: BollingerBandsModel
    atr: float = Field(default=0.0)
    volume_ratio: float = Field(default=1.0, description="量比")
    signals: List[str] = Field(
        default_factory=list,
        description="信号列表，如 MA_GOLDEN_CROSS, MACD_BULL_DIVERGE 等",
    )


# ==========================================
#  通用分页模型
# ==========================================

class PaginatedResponse(BaseModel):
    """Cursor-based 分页响应（对齐 docs/10 §1.5）"""
    items: List[Any] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False


# ==========================================
#  客户端 APM 心跳模型
# ==========================================

class ClientHeartbeatModel(BaseModel):
    """客户端 APM 心跳入参（对齐 docs/11 client_heartbeats 表）"""
    platform: Literal["ios", "android", "harmonyos", "web", "desktop"]
    app_version: Optional[str] = None
    device_id: Optional[str] = None
    fps: Optional[float] = None
    memory_mb: Optional[float] = None
    ws_latency_ms: Optional[int] = None
