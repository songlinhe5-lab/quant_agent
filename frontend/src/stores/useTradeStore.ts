import { create } from 'zustand'

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'LIMIT' | 'STOP'
export type PositionLevel = 'entryPrice' | 'sl' | 'tp'

export interface SimPosition {
  id: string
  symbol: string
  side: OrderSide
  entryPrice: number
  qty: number
  sl?: number
  tp?: number
  createdAt: number
}

export interface PendingOrder {
  symbol: string
  side: OrderSide
  type: OrderType
  price: number
  qty: number
}

interface TradeState {
  /** 按标的聚合的模拟持仓（沙箱推演，非实盘） */
  positions: Record<string, SimPosition[]>
  /** 拖拽完成后待确认的下单草稿 */
  pending: PendingOrder | null
  setPending: (o: PendingOrder | null) => void
  confirmPending: () => void
  cancelPending: () => void
  updatePositionLevel: (symbol: string, id: string, level: PositionLevel, price: number) => void
  removePosition: (symbol: string, id: string) => void
  getPositions: (symbol: string) => SimPosition[]
}

const genId = () => (globalThis.crypto?.randomUUID?.() ?? `pos-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`)

/**
 * PROD-09：承载图表内拖拽式下单的模拟持仓与待确认订单。
 * 当前 OMS 未实装，所有数据为本地沙箱推演，仅作可视化与交互验证。
 */
export const useTradeStore = create<TradeState>((set, get) => ({
  positions: {},
  pending: null,
  setPending: (o) => set({ pending: o }),
  confirmPending: () => {
    const p = get().pending
    if (!p) return
    const pos: SimPosition = {
      id: genId(),
      symbol: p.symbol,
      side: p.side,
      entryPrice: p.price,
      qty: p.qty,
      createdAt: Date.now(),
    }
    set((s) => ({
      positions: { ...s.positions, [p.symbol]: [...(s.positions[p.symbol] ?? []), pos] },
      pending: null,
    }))
  },
  cancelPending: () => set({ pending: null }),
  updatePositionLevel: (symbol, id, level, price) =>
    set((s) => {
      const list = s.positions[symbol] ?? []
      return {
        positions: {
          ...s.positions,
          [symbol]: list.map((p) => (p.id === id ? { ...p, [level]: price } : p)),
        },
      }
    }),
  removePosition: (symbol, id) =>
    set((s) => ({
      positions: { ...s.positions, [symbol]: (s.positions[symbol] ?? []).filter((p) => p.id !== id) },
    })),
  getPositions: (symbol) => get().positions[symbol] ?? [],
}))
