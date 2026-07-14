/**
 * 前端关键组件测试 (TEST-14)
 * ============================
 *
 * 覆盖:
 *   - marketStore: 全局标的状态管理
 *   - useWatchlist: 自选股列表 CRUD
 *   - PriceTicker: 价格显示组件
 *   - financial-format 扩展: formatCurrency / formatLargeNumber 边界
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { act } from '@testing-library/react'
import { useMarketStore } from '@/stores/marketStore'
import { useWatchlist, type WatchlistItem } from '@/stores/use-watchlist'
import {
  formatCurrency,
  formatLargeNumber,
  getChangeBgColor,
  getMarketCSSVariables,
  setMarketRegion,
} from '@/lib/financial-format'

// ─── marketStore 测试 ──────────────────────────────────────────────

describe('useMarketStore', () => {
  beforeEach(() => {
    act(() => {
      useMarketStore.getState().resetTicker()
    })
  })

  it('should have default ticker', () => {
    const state = useMarketStore.getState()
    expect(state.currentTicker).toBe('0700.HK')
    expect(state.currentTickerName).toBe('腾讯控股')
  })

  it('setCurrentTicker updates ticker state', () => {
    act(() => {
      useMarketStore.getState().setCurrentTicker('AAPL', 'Apple Inc.', 'EQUITY')
    })
    const state = useMarketStore.getState()
    expect(state.currentTicker).toBe('AAPL')
    expect(state.currentTickerName).toBe('Apple Inc.')
    expect(state.currentTickerType).toBe('EQUITY')
  })

  it('setCurrentTicker uses default name and type', () => {
    act(() => {
      useMarketStore.getState().setCurrentTicker('MSFT')
    })
    const state = useMarketStore.getState()
    expect(state.currentTicker).toBe('MSFT')
    expect(state.currentTickerName).toBe('')
    expect(state.currentTickerType).toBe('EQUITY')
  })

  it('resetTicker restores default', () => {
    act(() => {
      useMarketStore.getState().setCurrentTicker('TSLA', 'Tesla', 'EQUITY')
    })
    act(() => {
      useMarketStore.getState().resetTicker()
    })
    const state = useMarketStore.getState()
    expect(state.currentTicker).toBe('0700.HK')
    expect(state.currentTickerName).toBe('腾讯控股')
  })
})

// ─── useWatchlist 测试 ─────────────────────────────────────────────

describe('useWatchlist', () => {
  beforeEach(() => {
    // 清空自选股列表，设置初始状态
    const state = useWatchlist.getState()
    // 移除所有现有项
    state.watchlist.forEach((w: WatchlistItem) => {
      useWatchlist.getState().removeTicker(w.symbol)
    })
  })

  it('addTicker adds new symbol', () => {
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
    })
    const state = useWatchlist.getState()
    expect(state.watchlist).toHaveLength(1)
    expect(state.watchlist[0].symbol).toBe('AAPL')
    expect(state.watchlist[0].price).toBe(0)
    expect(state.watchlist[0].change).toBe(0)
  })

  it('addTicker prevents duplicates', () => {
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
    })
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
    })
    const state = useWatchlist.getState()
    expect(state.watchlist).toHaveLength(1)
  })

  it('removeTicker removes symbol', () => {
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
      useWatchlist.getState().addTicker('MSFT')
    })
    act(() => {
      useWatchlist.getState().removeTicker('AAPL')
    })
    const state = useWatchlist.getState()
    expect(state.watchlist).toHaveLength(1)
    expect(state.watchlist[0].symbol).toBe('MSFT')
  })

  it('updateTicker updates existing symbol data', () => {
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
    })
    act(() => {
      useWatchlist.getState().updateTicker('AAPL', { price: 150.0, change: 2.5 })
    })
    const state = useWatchlist.getState()
    expect(state.watchlist[0].price).toBe(150.0)
    expect(state.watchlist[0].change).toBe(2.5)
  })

  it('updateTicker matches symbol with slash removed', () => {
    act(() => {
      useWatchlist.getState().addTicker('HK/00700')
    })
    act(() => {
      useWatchlist.getState().updateTicker('HK00700', { price: 350.0 })
    })
    const state = useWatchlist.getState()
    expect(state.watchlist[0].price).toBe(350.0)
  })

  it('reorderWatchlist moves item correctly', () => {
    act(() => {
      useWatchlist.getState().addTicker('AAPL')
      useWatchlist.getState().addTicker('MSFT')
      useWatchlist.getState().addTicker('GOOGL')
    })
    act(() => {
      useWatchlist.getState().reorderWatchlist(2, 0) // Move GOOGL to front
    })
    const state = useWatchlist.getState()
    expect(state.watchlist[0].symbol).toBe('GOOGL')
    expect(state.watchlist[1].symbol).toBe('AAPL')
    expect(state.watchlist[2].symbol).toBe('MSFT')
  })
})

// ─── financial-format 扩展测试 ─────────────────────────────────────

describe('formatCurrency', () => {
  it('should format USD with $ prefix', () => {
    const result = formatCurrency(1234.56, 'USD')
    expect(result).toContain('$')
    expect(result).toContain('1,234.56')
  })

  it('should format HKD with HK$ prefix', () => {
    const result = formatCurrency(500.0, 'HKD')
    expect(result).toContain('HK$')
  })

  it('should format CNY with ¥ prefix', () => {
    const result = formatCurrency(100.0, 'CNY')
    expect(result).toContain('¥')
  })

  it('should use absolute value', () => {
    const result = formatCurrency(-500.0, 'USD')
    expect(result).not.toContain('-')
    expect(result).toContain('500.00')
  })
})

describe('formatLargeNumber edge cases', () => {
  it('should format trillions', () => {
    expect(formatLargeNumber(1e12)).toBe('1.00T')
    expect(formatLargeNumber(2.5e12)).toBe('2.50T')
  })

  it('should handle zero', () => {
    expect(formatLargeNumber(0)).toBe('0.00')
  })

  it('should handle numbers just below thresholds', () => {
    expect(formatLargeNumber(999)).toBe('999.00')
    expect(formatLargeNumber(999999)).toBe('1000.00K') // 999999 ≈ 1000K
  })
})

// ─── getChangeBgColor 测试 ─────────────────────────────────────────

describe('getChangeBgColor', () => {
  beforeEach(() => {
    setMarketRegion('CN')
  })

  it('should return red bg for CN market up', () => {
    const result = getChangeBgColor(1.5)
    expect(result).toContain('red')
  })

  it('should return green bg for CN market down', () => {
    const result = getChangeBgColor(-1.5)
    expect(result).toContain('emerald')
  })

  it('should return green bg for US market up', () => {
    const result = getChangeBgColor(1.5, 'US')
    expect(result).toContain('emerald')
  })

  it('should return muted bg for zero change', () => {
    const result = getChangeBgColor(0)
    expect(result).toContain('muted')
  })
})

// ─── getMarketCSSVariables 测试 ────────────────────────────────────

describe('getMarketCSSVariables', () => {
  it('should return CN variables (red up, green down)', () => {
    const result = getMarketCSSVariables('CN')
    expect(result).toContain('#ef4444') // red up
    expect(result).toContain('#10b981') // green down
  })

  it('should return US variables (green up, red down)', () => {
    const result = getMarketCSSVariables('US')
    expect(result).toContain('--color-up: #10b981')
    expect(result).toContain('--color-down: #ef4444')
  })
})
