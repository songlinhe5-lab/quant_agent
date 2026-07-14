import { create } from 'zustand'
import type { TradingMode } from '@/features/trading/trading-mode-types'

interface TradingModeState {
  mode: TradingMode
  hydrated: boolean
  setMode: (mode: TradingMode) => void
  setHydrated: (v: boolean) => void
}

export const useTradingModeStore = create<TradingModeState>((set) => ({
  mode: 'SANDBOX',
  hydrated: false,
  setMode: (mode) => set({ mode }),
  setHydrated: (hydrated) => set({ hydrated }),
}))
