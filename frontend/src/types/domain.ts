/**
 * 前端 TypeScript 领域类型定义
 * FE-18: 与 docs/11 领域对象严格对齐
 * 
 * 对应后端 Pydantic Schema: backend/schemas/domain.py
 */

// ─── 基础类型 ──────────────────────────────────────────────────────

/** 市场类型 */
export type Market = 'US' | 'HK' | 'CN' | 'SG' | 'JP'

/** 证券类型 */
export type SecurityType = 'STOCK' | 'ETF' | 'OPTION' | 'FUTURE' | 'INDEX' | 'CRYPTO'

/** K线周期 */
export type KlinePeriod = 'K_1M' | 'K_5M' | 'K_15M' | 'K_30M' | 'K_1H' | 'K_DAY' | 'K_WEEK' | 'K_MONTH'

// ─── 标的信息 ──────────────────────────────────────────────────────

/** 标的符号 */
export interface Symbol {
  code: string           // 标的代码，如 "HK.00700"
  name: string           // 标的名称
  market: Market         // 所属市场
  securityType: SecurityType  // 证券类型
  lotSize?: number       // 每手股数
  currency?: string      // 计价货币
}

// ─── 行情数据 ──────────────────────────────────────────────────────

/** 实时报价 */
export interface Quote {
  symbol: string
  lastPrice: number
  open: number
  high: number
  low: number
  prevClose: number
  volume: number
  turnover: number
  change: number
  changePercent: number
  
  // 盘口数据
  bidPrice?: number
  bidVolume?: number
  askPrice?: number
  askVolume?: number
  
  // 时间戳
  timestamp: number
  source?: string
}

/** K线数据 */
export interface Kline {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover?: number
}

/** 带 symbol 的 K线 */
export interface KlineData {
  symbol: string
  period: KlinePeriod
  klines: Kline[]
}

/** Tick 数据 */
export interface Tick {
  timestamp: number
  price: number
  volume: number
  bid?: number
  ask?: number
  bidSize?: number
  askSize?: number
}

// ─── 持仓与订单 ────────────────────────────────────────────────────

/** 持仓方向 */
export type PositionSide = 'LONG' | 'SHORT'

/** 持仓状态 */
export type PositionStatus = 'OPEN' | 'CLOSED'

/** 持仓 */
export interface Position {
  id: string
  symbol: string
  side: PositionSide
  quantity: number
  avgCost: number
  currentPrice: number
  marketValue: number
  unrealizedPnL: number
  realizedPnL: number
  unrealizedPnLPercent: number
  status: PositionStatus
  openedAt: number
  updatedAt: number
}

/** 订单方向 */
export type OrderSide = 'BUY' | 'SELL'

/** 订单类型 */
export type OrderType = 'MARKET' | 'LIMIT' | 'STOP' | 'STOP_LIMIT'

/** 订单状态 */
export type OrderStatus = 'PENDING' | 'SUBMITTED' | 'PARTIAL' | 'FILLED' | 'CANCELLED' | 'REJECTED'

/** 订单 */
export interface Order {
  id: string
  symbol: string
  side: OrderSide
  type: OrderType
  quantity: number
  price?: number           // 限价单价格
  stopPrice?: number       // 止损单触发价
  filledQuantity: number
  filledAvgPrice?: number
  status: OrderStatus
  createdAt: number
  updatedAt: number
  
  // 模拟/实盘标识
  isPaper: boolean
  strategyId?: string
}

// ─── 账户信息 ──────────────────────────────────────────────────────

/** 账户 */
export interface Account {
  accountId: string
  totalAssets: number      // 总资产
  cash: number             // 现金
  marketValue: number      // 持仓市值
  buyingPower: number      // 购买力
  unrealizedPnL: number    // 未实现盈亏
  realizedPnL: number      // 已实现盈亏
  dailyPnL: number         // 当日盈亏
  dailyPnLPercent: number
  currency: string
  updatedAt: number
}

// ─── 技术指标 ──────────────────────────────────────────────────────

/** 技术指标类型 */
export type IndicatorType = 'MA' | 'EMA' | 'MACD' | 'RSI' | 'KDJ' | 'BOLL' | 'ATR' | 'VWAP'

/** 技术指标参数 */
export interface IndicatorParams {
  period?: number
  fastPeriod?: number
  slowPeriod?: number
  signalPeriod?: number
  multiplier?: number
}

/** 技术指标结果 */
export interface TechnicalIndicator {
  type: IndicatorType
  params: IndicatorParams
  values: Record<string, number>[]  // 每个时间点的指标值
  signal?: string                    // 买卖信号
}

// ─── 选股相关 ──────────────────────────────────────────────────────

/** 选股条件 */
export interface ScreenerFilter {
  market?: Market[]
  securityType?: SecurityType[]
  minMarketCap?: number
  maxMarketCap?: number
  minPE?: number
  maxPE?: number
  minPB?: number
  maxPB?: number
  minVolume?: number
  minChangePercent?: number
  maxChangePercent?: number
  indicators?: Record<string, { min?: number; max?: number }>
}

/** 选股结果 */
export interface ScreenerResult {
  symbol: string
  name: string
  market: Market
  lastPrice: number
  changePercent: number
  volume: number
  marketCap?: number
  pe?: number
  pb?: number
  indicators?: Record<string, number>
}

// ─── 策略相关 ──────────────────────────────────────────────────────

/** 策略状态 */
export type StrategyStatus = 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'ARCHIVED'

/** 策略 */
export interface Strategy {
  id: string
  name: string
  description?: string
  status: StrategyStatus
  code: string           // 策略代码
  params?: Record<string, unknown>
  createdAt: number
  updatedAt: number
}

// ─── 客户端心跳 ────────────────────────────────────────────────────

/** 客户端心跳 */
export interface ClientHeartbeat {
  platform: 'web' | 'ios' | 'android' | 'harmonyos'
  version: string
  fps?: number
  memoryUsage?: number
  wsLatency?: number
  timestamp: number
}

// ─── API 响应 ──────────────────────────────────────────────────────

/** 统一 API 响应结构 */
export interface ApiResponse<T = unknown> {
  code: number
  msg: string
  data: T
  ts: number
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  hasMore: boolean
}

// ─── WebSocket 消息 ────────────────────────────────────────────────

/** WS 订阅消息 */
export interface WSSubscribeMessage {
  type: 'subscribe' | 'unsubscribe'
  topic: string
  symbol?: string
}

/** WS 行情推送 */
export interface WSQuoteMessage {
  type: 'quote'
  data: Quote
}

/** WS K线推送 */
export interface WSKlineMessage {
  type: 'kline'
  data: KlineData
}

/** WS 消息联合类型 */
export type WSMessage = WSSubscribeMessage | WSQuoteMessage | WSKlineMessage

// ─── 工具类型 ──────────────────────────────────────────────────────

/** 将后端 snake_case 转换为前端 camelCase */
export type SnakeToCamel<T extends string> = T extends `${infer A}_${infer B}`
  ? `${A}${SnakeToCamel<Capitalize<B>>}`
  : T

/** 将后端响应转换为前端类型 */
export type FromBackend<T> = {
  [K in keyof T as SnakeToCamel<K & string>]: T[K]
}
