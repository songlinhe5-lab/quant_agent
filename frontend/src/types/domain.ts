/**
 * 领域对象类型定义
 * 与后端 Pydantic Schema 对齐 (docs/11)
 */

// 行情相关
export interface Quote {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  timestamp: number;
}

// K线数据
export interface Kline {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// 持仓
export interface Position {
  id: string;
  symbol: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
}

// 订单
export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit';
  quantity: number;
  price?: number;
  status: 'pending' | 'filled' | 'cancelled' | 'partial';
  createdAt: number;
}

// 账户信息
export interface Account {
  id: string;
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  marginLevel: number;
}

// 技术指标
export interface TechnicalIndicator {
  name: string;
  value: number;
  signal: 'buy' | 'sell' | 'neutral';
}

// 新闻
export interface News {
  id: string;
  title: string;
  summary: string;
  source: string;
  timestamp: number;
  url: string;
}

// 自选股
export interface Watchlist {
  id: string;
  name: string;
  symbols: string[];
}

// API 响应通用格式
export interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T;
  ts: number;
}
