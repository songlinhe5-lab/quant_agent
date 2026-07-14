/**
 * FE-PROD-02: 三模式 store + 切换规则文案
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import {
  formatModeLabel,
  getPaperCheckpointPlaceholder,
  MODE_META,
  TRADING_MODES,
} from '@/features/trading/trading-mode-types'
import { applyTradingModeFromWs } from '@/features/trading/trading-mode-actions'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('@/components/confirm-dialog', () => ({
  confirmDanger: vi.fn(),
}))

import { apiClient } from '@/lib/api-client'
import { confirmDanger } from '@/components/confirm-dialog'
import { hydrateTradingMode, requestTradingModeSwitch } from '@/features/trading/trading-mode-actions'

const mockApi = vi.mocked(apiClient)
const mockConfirm = vi.mocked(confirmDanger)

describe('trading mode types', () => {
  it('exposes three modes with distinct banner classes', () => {
    expect(TRADING_MODES).toEqual(['SANDBOX', 'PAPER', 'LIVE'])
    expect(MODE_META.SANDBOX.bannerClass).toContain('amber')
    expect(MODE_META.PAPER.bannerClass).toContain('orange')
    expect(MODE_META.LIVE.bannerClass).toContain('red')
    expect(formatModeLabel('PAPER')).toContain('PAPER')
  })

  it('paper checkpoint placeholder marks PT-02b debt', () => {
    const cp = getPaperCheckpointPlaceholder()
    expect(cp.sharpe).toBe('—')
    expect(cp.note).toMatch(/纸面/)
  })
})

describe('useTradingModeStore', () => {
  beforeEach(() => {
    act(() => {
      useTradingModeStore.setState({ mode: 'SANDBOX', hydrated: false })
    })
    vi.clearAllMocks()
  })

  it('applyTradingModeFromWs ignores invalid payloads', () => {
    applyTradingModeFromWs('BOGUS')
    expect(useTradingModeStore.getState().mode).toBe('SANDBOX')
    applyTradingModeFromWs('LIVE')
    expect(useTradingModeStore.getState().mode).toBe('LIVE')
  })

  it('hydrateTradingMode reads /oms/mode', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: { status: 'success', data: { mode: 'PAPER' } },
    } as never)

    await hydrateTradingMode()
    expect(useTradingModeStore.getState().mode).toBe('PAPER')
    expect(useTradingModeStore.getState().hydrated).toBe(true)
  })

  it('requestTradingModeSwitch aborts when user cancels', async () => {
    mockConfirm.mockResolvedValueOnce(false)
    const ok = await requestTradingModeSwitch('LIVE')
    expect(ok).toBe(false)
    expect(mockApi.post).not.toHaveBeenCalled()
    expect(useTradingModeStore.getState().mode).toBe('SANDBOX')
  })

  it('requestTradingModeSwitch posts and updates store', async () => {
    mockConfirm.mockResolvedValueOnce(true)
    mockApi.post.mockResolvedValueOnce({
      data: { status: 'success', message: 'ok' },
    } as never)

    const ok = await requestTradingModeSwitch('PAPER')
    expect(ok).toBe(true)
    expect(mockApi.post).toHaveBeenCalledWith('/oms/mode/switch', { mode: 'PAPER' })
    expect(useTradingModeStore.getState().mode).toBe('PAPER')
  })

  it('SANDBOX→LIVE requires typing LIVE', async () => {
    mockConfirm.mockResolvedValueOnce(true)
    mockApi.post.mockResolvedValueOnce({
      data: { status: 'success' },
    } as never)

    await requestTradingModeSwitch('LIVE')
    expect(mockConfirm).toHaveBeenCalledWith(
      expect.stringContaining('SANDBOX → LIVE'),
      expect.stringContaining('禁止从 SANDBOX 直接跳 LIVE'),
      expect.objectContaining({ requireInputConfirm: 'LIVE' }),
    )
  })
})

describe('store hook', () => {
  it('exposes mode via renderHook', () => {
    const { result } = renderHook(() => useTradingModeStore())
    expect(result.current.mode).toBeDefined()
  })
})
