/**
 * FE-PROD-03: AlertOverlay / Toast / ui_hint / STALE
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useAlertOverlayStore } from '@/stores/useAlertOverlayStore'
import { parseAlertPush, resolveAlertNavigation } from '@/features/alert/alert-nav'
import type { AlertPushPayload } from '@/types/alert'

function makePush(over: Partial<AlertPushPayload> = {}): AlertPushPayload {
  return {
    type: 'alert',
    event_id: 'e1',
    priority: 'p1',
    severity: 'warning',
    message: 'AAPL 突破',
    ticker: 'AAPL',
    triggered_at: 1,
    ui_hint: { mode: 'toast', route: '/market', symbol: 'AAPL' },
    rule_id: 'r1',
    source: 'user_rule',
    ack_required: false,
    ...over,
  }
}

describe('parseAlertPush', () => {
  it('parses InApp adapter payload', () => {
    const p = parseAlertPush({
      type: 'alert',
      event_id: 'x',
      priority: 'p0',
      severity: 'critical',
      message: 'Kill Switch',
      ticker: '',
      triggered_at: 99,
      ui_hint: { mode: 'fullscreen', flash: true },
      rule_id: '',
      source: 'kill_switch',
      ack_required: true,
    })
    expect(p?.priority).toBe('p0')
    expect(p?.ui_hint.mode).toBe('fullscreen')
    expect(p?.ack_required).toBe(true)
  })

  it('returns null for garbage', () => {
    expect(parseAlertPush(null)).toBeNull()
    expect(parseAlertPush({ foo: 1 })).toBeNull()
  })
})

describe('resolveAlertNavigation', () => {
  it('maps /market + symbol to /quotes', () => {
    expect(resolveAlertNavigation({ route: '/market', symbol: 'AAPL' })).toEqual({
      path: '/quotes',
      symbol: 'AAPL',
    })
  })

  it('falls back to /alerts without symbol/route', () => {
    expect(resolveAlertNavigation({})).toEqual({ path: '/alerts', symbol: undefined })
  })

  it('uses ticker when hint.symbol missing', () => {
    expect(resolveAlertNavigation({ route: '/market' }, 'TSLA').symbol).toBe('TSLA')
  })
})

describe('useAlertOverlayStore', () => {
  beforeEach(() => {
    act(() => {
      useAlertOverlayStore.setState({
        p0Queue: [],
        toastStack: [],
        badgeCount: 0,
        wsStale: false,
      })
    })
  })

  it('routes P0 to overlay queue and bumps badge', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    act(() => {
      result.current.enqueuePush(makePush({ event_id: 'p0-1', priority: 'p0', ack_required: true }))
    })
    expect(result.current.p0Queue).toHaveLength(1)
    expect(result.current.toastStack).toHaveLength(0)
    expect(result.current.badgeCount).toBe(1)
  })

  it('routes P1 to toast stack', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    act(() => {
      result.current.enqueuePush(makePush({ event_id: 'p1-1', priority: 'p1' }))
    })
    expect(result.current.toastStack[0].event_id).toBe('p1-1')
    expect(result.current.p0Queue).toHaveLength(0)
  })

  it('P3 only increments badge', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    act(() => {
      result.current.enqueuePush(makePush({ event_id: 'p3-1', priority: 'p3' }))
    })
    expect(result.current.toastStack).toHaveLength(0)
    expect(result.current.p0Queue).toHaveLength(0)
    expect(result.current.badgeCount).toBe(1)
  })

  it('dedupes P0 by event_id', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    const p0 = makePush({ event_id: 'same', priority: 'p0' })
    act(() => {
      result.current.enqueuePush(p0)
      result.current.enqueuePush(p0)
    })
    expect(result.current.p0Queue).toHaveLength(1)
  })

  it('setWsStale marks history stale', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    act(() => result.current.setWsStale(true))
    expect(result.current.wsStale).toBe(true)
  })

  it('clearP0Queue empties overlay', () => {
    const { result } = renderHook(() => useAlertOverlayStore())
    act(() => {
      result.current.enqueuePush(makePush({ event_id: 'a', priority: 'p0' }))
      result.current.clearP0Queue()
    })
    expect(result.current.p0Queue).toHaveLength(0)
  })
})

describe('sessionStorage navigation side-effect', () => {
  it('applyAlertNavigation writes symbol for quotes', async () => {
    const { applyAlertNavigation } = await import('@/features/alert/alert-nav')
    const nav = vi.fn()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    applyAlertNavigation(nav, { route: '/market', symbol: 'MSFT' }, 'MSFT')
    expect(nav).toHaveBeenCalledWith('/quotes')
    expect(setItem).toHaveBeenCalledWith('quant_target_symbol', 'MSFT')
    setItem.mockRestore()
  })
})
