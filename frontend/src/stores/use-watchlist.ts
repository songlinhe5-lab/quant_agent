import { create } from 'zustand'
import { persist, devtools } from 'zustand/middleware'
import { MOCK_WATCHLIST } from '@/services/mock'

export interface WatchlistItem {
  symbol: string
  price: number
  change: number
  vol: string
  sparkDir: number[]
}

interface WatchlistState {
  watchlist: WatchlistItem[]
  addTicker: (symbol: string) => void
  removeTicker: (symbol: string) => void
  updateTicker: (symbol: string, data: Partial<WatchlistItem>) => void
  reorderWatchlist: (oldIndex: number, newIndex: number) => void
}

export const useWatchlist = create<WatchlistState>()(
  devtools(
    persist(
      (set) => ({
        // 初始默认提供 MOCK_WATCHLIST 兜底，展示一些常用标的
        watchlist: MOCK_WATCHLIST,

        addTicker: (symbol) => set((state) => {
          // 防止重复添加
          if (state.watchlist.some((w) => w.symbol === symbol)) return state
          return {
            watchlist: [
              ...state.watchlist,
              {
                symbol,
                price: 0,
                change: 0,
                vol: '--',
                sparkDir: [0, 0, 0, 0, 0, 0, 0, 0], // 默认平滑火花线
              },
            ],
          }
        }),

        removeTicker: (symbol) => set((state) => ({
          watchlist: state.watchlist.filter((w) => w.symbol !== symbol),
        })),

        updateTicker: (symbol, data) => set((state) => ({
          watchlist: state.watchlist.map((w) =>
            (w.symbol === symbol || w.symbol.replace('/', '') === symbol) ? { ...w, ...data } : w
          ),
        })),

        reorderWatchlist: (oldIndex, newIndex) => set((state) => {
          const newList = [...state.watchlist]
          const [removed] = newList.splice(oldIndex, 1)
          newList.splice(newIndex, 0, removed)
          return { watchlist: newList }
        }),
      }),
      {
        name: 'quant-watchlist-storage', // LocalStorage 的键名
      }
    )
  )
)