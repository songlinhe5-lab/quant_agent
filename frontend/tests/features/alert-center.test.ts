/**
 * 告警中心前端测试 (ALERT-04)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAlertRules, useAlertEvents } from '@/hooks/use-alert-api'
import type { AlertRule, AlertEvent } from '@/types/alert'
import { RULE_TYPE_LABELS, SEVERITY_LABELS, SEVERITY_COLORS } from '@/types/alert'

// ─── Mock API Client ───────────────────────────────────────────────

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { apiClient } from '@/lib/api-client'
const mockApiClient = vi.mocked(apiClient)

// ─── 测试数据 ──────────────────────────────────────────────────────

const mockRule: AlertRule = {
  rule_id: 'rule-1',
  name: 'AAPL 突破 $200',
  ticker: 'AAPL',
  rule_type: 'price_above',
  threshold: 200,
  severity: 'warning',
  channels: ['in_app'],
  cooldown_seconds: 300,
  enabled: true,
  trigger_count: 0,
  last_triggered_at: null,
  created_at: Date.now() / 1000,
  updated_at: Date.now() / 1000,
}

const mockEvent: AlertEvent = {
  event_id: 'event-1',
  rule_id: 'rule-1',
  ticker: 'AAPL',
  rule_type: 'price_above',
  severity: 'warning',
  message: 'AAPL 突破 $200 目标价',
  trigger_value: 201.5,
  threshold: 200,
  triggered_at: Date.now() / 1000,
  acknowledged: false,
  source: 'user_rule',
  priority: 'p1',
}

// ─── 常量测试 ──────────────────────────────────────────────────────

describe('Alert Types & Constants', () => {
  it('RULE_TYPE_LABELS contains all rule types', () => {
    expect(RULE_TYPE_LABELS.price_cross).toBe('价格穿越')
    expect(RULE_TYPE_LABELS.price_above).toBe('价格突破')
    expect(RULE_TYPE_LABELS.price_below).toBe('价格跌破')
    expect(RULE_TYPE_LABELS.indicator).toBe('技术指标')
    expect(RULE_TYPE_LABELS.strategy_signal).toBe('策略信号')
    expect(RULE_TYPE_LABELS.macro_event).toBe('宏观事件')
  })

  it('SEVERITY_LABELS contains all severity levels', () => {
    expect(SEVERITY_LABELS.info).toBe('信息')
    expect(SEVERITY_LABELS.warning).toBe('警告')
    expect(SEVERITY_LABELS.critical).toBe('严重')
  })

  it('SEVERITY_COLORS maps to correct Tailwind classes', () => {
    expect(SEVERITY_COLORS.info).toContain('text-blue')
    expect(SEVERITY_COLORS.warning).toContain('text-amber')
    expect(SEVERITY_COLORS.critical).toContain('text-red')
  })
})

// ─── useAlertRules Hook 测试 ───────────────────────────────────────

describe('useAlertRules', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetchRules loads rules from API', async () => {
    mockApiClient.get.mockResolvedValueOnce({ data: [mockRule] })

    const { result } = renderHook(() => useAlertRules())

    expect(result.current.rules).toEqual([])
    expect(result.current.loading).toBe(false)

    await act(async () => {
      await result.current.fetchRules()
    })

    expect(result.current.rules).toEqual([mockRule])
    expect(result.current.loading).toBe(false)
    expect(mockApiClient.get).toHaveBeenCalledWith('/alert/rules', undefined)
  })

  it('fetchRules handles API error', async () => {
    mockApiClient.get.mockRejectedValueOnce(new Error('Network error'))

    const { result } = renderHook(() => useAlertRules())

    await act(async () => {
      await result.current.fetchRules()
    })

    expect(result.current.error).toBe('Network error')
    expect(result.current.rules).toEqual([])
  })

  it('createRule adds a new rule', async () => {
    mockApiClient.post.mockResolvedValueOnce({ data: mockRule })

    const { result } = renderHook(() => useAlertRules())

    let createdRule: AlertRule | null = null
    await act(async () => {
      createdRule = await result.current.createRule({
        name: 'AAPL 突破 $200',
        ticker: 'AAPL',
        rule_type: 'price_above',
        threshold: 200,
      })
    })

    expect(createdRule).toEqual(mockRule)
    expect(result.current.rules).toEqual([mockRule])
  })

  it('toggleRule toggles rule enabled state', async () => {
    mockApiClient.get.mockResolvedValueOnce({ data: [mockRule] })
    mockApiClient.post.mockResolvedValueOnce({ data: { ...mockRule, enabled: false } })

    const { result } = renderHook(() => useAlertRules())

    await act(async () => {
      await result.current.fetchRules()
    })

    await act(async () => {
      await result.current.toggleRule('rule-1')
    })

    expect(result.current.rules[0].enabled).toBe(false)
  })

  it('deleteRule removes rule from list', async () => {
    mockApiClient.get.mockResolvedValueOnce({ data: [mockRule] })
    mockApiClient.delete.mockResolvedValueOnce({})

    const { result } = renderHook(() => useAlertRules())

    await act(async () => {
      await result.current.fetchRules()
    })

    expect(result.current.rules.length).toBe(1)

    await act(async () => {
      const success = await result.current.deleteRule('rule-1')
      expect(success).toBe(true)
    })

    expect(result.current.rules.length).toBe(0)
  })
})

// ─── useAlertEvents Hook 测试 ──────────────────────────────────────

describe('useAlertEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetchEvents loads events from API', async () => {
    mockApiClient.get.mockResolvedValueOnce({ data: [mockEvent] })

    const { result } = renderHook(() => useAlertEvents())

    await act(async () => {
      await result.current.fetchEvents()
    })

    expect(result.current.events).toEqual([mockEvent])
  })

  it('ackEvent marks event as acknowledged', async () => {
    mockApiClient.get.mockResolvedValueOnce({ data: [mockEvent] })
    mockApiClient.post.mockResolvedValueOnce({ data: { ...mockEvent, acknowledged: true } })

    const { result } = renderHook(() => useAlertEvents())

    await act(async () => {
      await result.current.fetchEvents()
    })

    expect(result.current.events[0].acknowledged).toBe(false)

    await act(async () => {
      await result.current.ackEvent('event-1')
    })

    expect(result.current.events[0].acknowledged).toBe(true)
  })

  it('ackAll acknowledges all unacknowledged events', async () => {
    const event2 = { ...mockEvent, event_id: 'event-2' }
    mockApiClient.get.mockResolvedValueOnce({ data: [mockEvent, event2] })
    mockApiClient.post.mockResolvedValue({ data: { ...mockEvent, acknowledged: true } })

    const { result } = renderHook(() => useAlertEvents())

    await act(async () => {
      await result.current.fetchEvents()
    })

    expect(result.current.events.filter(e => !e.acknowledged).length).toBe(2)

    await act(async () => {
      await result.current.ackAll()
    })

    expect(result.current.events.every(e => e.acknowledged)).toBe(true)
  })
})
