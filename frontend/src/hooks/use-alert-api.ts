/**
 * 告警中心 API Hook (ALERT-04)
 * 封装后端 /api/v1/alert/* 端点的 CRUD 操作
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { apiClient } from '@/lib/api-client'
import logger from '@/lib/logger'
import type {
  AlertRule,
  AlertEvent,
  AlertEngineStatus,
  CreateRulePayload,
  UpdateRulePayload,
} from '@/types/alert'

// ─── API 封装 ──────────────────────────────────────────────────────

const alertApi = {
  // 规则 CRUD
  listRules: (params?: { ticker?: string; enabled?: boolean }) =>
    apiClient.get<{ data: AlertRule[] }>('/alert/rules', params),

  createRule: (payload: CreateRulePayload) =>
    apiClient.post<{ data: AlertRule }>('/alert/rules', payload),

  updateRule: (ruleId: string, payload: UpdateRulePayload) =>
    apiClient.put<{ data: AlertRule }>(`/alert/rules/${ruleId}`, payload),

  deleteRule: (ruleId: string) =>
    apiClient.delete(`/alert/rules/${ruleId}`),

  toggleRule: (ruleId: string) =>
    apiClient.post<{ data: AlertRule }>(`/alert/rules/${ruleId}/toggle`),

  // 事件
  listEvents: (params?: { ticker?: string; severity?: string; since?: number; limit?: number }) =>
    apiClient.get<{ data: AlertEvent[] }>('/alert/events', params),

  ackEvent: (eventId: string) =>
    apiClient.post<{ data: AlertEvent }>(`/alert/events/${eventId}/ack`),

  // 引擎状态
  engineStatus: () =>
    apiClient.get<{ data: AlertEngineStatus }>('/alert/engine/status'),
}

// ─── Hook: useAlertRules ───────────────────────────────────────────

export function useAlertRules() {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchRules = useCallback(async (params?: { ticker?: string; enabled?: boolean }) => {
    setLoading(true)
    setError(null)
    try {
      const res = await alertApi.listRules(params)
      setRules(res.data ?? [])
    } catch (e) {
      const msg = e instanceof Error ? e.message : '获取规则失败'
      setError(msg)
      logger.error('[AlertAPI] 获取规则失败', e as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  const createRule = useCallback(async (payload: CreateRulePayload): Promise<AlertRule | null> => {
    try {
      const res = await alertApi.createRule(payload)
      const rule = res.data
      setRules(prev => [rule, ...prev])
      return rule
    } catch (e) {
      logger.error('[AlertAPI] 创建规则失败', e as Error)
      return null
    }
  }, [])

  const updateRule = useCallback(async (ruleId: string, payload: UpdateRulePayload): Promise<AlertRule | null> => {
    try {
      const res = await alertApi.updateRule(ruleId, payload)
      const updated = res.data
      setRules(prev => prev.map(r => r.rule_id === ruleId ? updated : r))
      return updated
    } catch (e) {
      logger.error('[AlertAPI] 更新规则失败', e as Error)
      return null
    }
  }, [])

  const deleteRule = useCallback(async (ruleId: string): Promise<boolean> => {
    try {
      await alertApi.deleteRule(ruleId)
      setRules(prev => prev.filter(r => r.rule_id !== ruleId))
      return true
    } catch (e) {
      logger.error('[AlertAPI] 删除规则失败', e as Error)
      return false
    }
  }, [])

  const toggleRule = useCallback(async (ruleId: string): Promise<AlertRule | null> => {
    try {
      const res = await alertApi.toggleRule(ruleId)
      const updated = res.data
      setRules(prev => prev.map(r => r.rule_id === ruleId ? updated : r))
      return updated
    } catch (e) {
      logger.error('[AlertAPI] 启停规则失败', e as Error)
      return null
    }
  }, [])

  return { rules, loading, error, fetchRules, createRule, updateRule, deleteRule, toggleRule }
}

// ─── Hook: useAlertEvents ──────────────────────────────────────────

export function useAlertEvents() {
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [loading, setLoading] = useState(false)
  const lastFetchRef = useRef<number>(0)

  const fetchEvents = useCallback(async (params?: { ticker?: string; severity?: string; limit?: number }) => {
    setLoading(true)
    try {
      const res = await alertApi.listEvents(params)
      const data = res.data ?? []
      setEvents(data)
      if (data.length > 0) {
        lastFetchRef.current = data[0].triggered_at
      }
    } catch (e) {
      logger.error('[AlertAPI] 获取事件失败', e as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  const ackEvent = useCallback(async (eventId: string) => {
    try {
      await alertApi.ackEvent(eventId)
      setEvents(prev => prev.map(e => e.event_id === eventId ? { ...e, acknowledged: true } : e))
    } catch (e) {
      logger.error('[AlertAPI] 确认事件失败', e as Error)
    }
  }, [])

  const ackAll = useCallback(async () => {
    try {
      await Promise.all(events.filter(e => !e.acknowledged).map(e => alertApi.ackEvent(e.event_id)))
      setEvents(prev => prev.map(e => ({ ...e, acknowledged: true })))
    } catch (e) {
      logger.error('[AlertAPI] 全部确认失败', e as Error)
    }
  }, [events])

  return { events, loading, fetchEvents, ackEvent, ackAll, lastFetchTime: lastFetchRef.current }
}

// ─── Hook: useAlertEngineStatus ────────────────────────────────────

export function useAlertEngineStatus() {
  const [status, setStatus] = useState<AlertEngineStatus | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await alertApi.engineStatus()
      setStatus(res.data)
    } catch (e) {
      logger.error('[AlertAPI] 获取引擎状态失败', e as Error)
    }
  }, [])

  return { status, fetchStatus }
}

// ─── Hook: useAlertWebSocket ───────────────────────────────────────

export function useAlertWebSocket(
  onEvent: (raw: unknown) => void,
  onStatus?: (connected: boolean) => void,
) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onEventRef = useRef(onEvent)
  const onStatusRef = useRef(onStatus)
  onEventRef.current = onEvent
  onStatusRef.current = onStatus

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    
    // 构建 WebSocket URL
    let wsUrl: string
    if (baseUrl.startsWith('http://') || baseUrl.startsWith('https://')) {
      // 完整 URL，直接替换 http 为 ws
      wsUrl = baseUrl.replace(/^http/, 'ws') + '/alert/ws'
    } else {
      // 相对路径，使用当前域名
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      wsUrl = `${protocol}//${window.location.host}${baseUrl}/alert/ws`
    }

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      logger.info('[AlertWS] 连接成功')
      onStatusRef.current?.(true)
      const heartbeat = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 30000)
      ws.addEventListener('close', () => clearInterval(heartbeat))
    }

    ws.onmessage = (e) => {
      if (e.data === 'pong') return
      try {
        const raw = JSON.parse(e.data as string)
        onEventRef.current(raw)
      } catch {
        // ignore
      }
    }

    ws.onclose = () => {
      logger.info('[AlertWS] 连接断开，5s 后重连')
      onStatusRef.current?.(false)
      reconnectTimerRef.current = setTimeout(connect, 5000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    return () => { disconnect() }
  }, [disconnect])

  return { connect, disconnect }
}
