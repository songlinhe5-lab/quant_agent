export interface BotLog {
  time: string
  msg: string
  type: 'info' | 'warn' | 'success'
}

export interface LiveBot {
  id: string
  name: string
  ticker: string
  status: 'running' | 'paused' | 'stopped' | 'error'
  cpu: number
  mem: number
  logs: BotLog[]
}

export interface ActiveOrder {
  id: string
  symbol: string
  side: 'BUY' | 'SELL'
  price: string
  qty: number
  filled: number
  status: 'PENDING' | 'SUBMITTED' | 'PARTIALLY_FILLED'
  time: string
}

export interface HistoricalTrade {
  id: string
  symbol: string
  side: 'BUY' | 'SELL'
  avg_price: string
  qty: number
  pnl: number
  time: string
}

export interface AlgoExecution {
  id: string
  algo_type: 'TWAP' | 'VWAP' | 'ICEBERG'
  symbol: string
  target_qty: number
  filled_qty: number
  avg_price: string
  progress: number
  status: 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'ERROR'
  message?: string
}

export interface Position {
  code: string
  stock_name?: string
  position_side: string
  qty: number
  can_sell_qty?: number
  cost_price: number
  market_val: number
  pl_val: number
  pl_ratio: number
}
