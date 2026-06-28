/**
 * WebSocket 连接管理器
 * FE-03: 断线5步处理流程
 * 断线 → 状态灯变红 → 图表 STALE overlay → 指数退避重连 → 重连成功后重订阅
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import logger from '@/lib/logger'

// ─── 连接状态 ───────────────────────────────────────────────────────
export type WSConnectionState = 
  | 'connecting'    // 正在连接
  | 'connected'     // 已连接
  | 'disconnected'  // 已断开
  | 'reconnecting'  // 重连中
  | 'failed'        // 连接失败

export interface WSStatus {
  state: WSConnectionState
  latency: number | null
  lastMessageTime: Date | null
  reconnectAttempts: number
  isStale: boolean
}

// ─── 配置 ───────────────────────────────────────────────────────────
interface WSManagerConfig {
  url: string
  protocols?: string | string[]
  maxReconnectAttempts: number
  baseReconnectDelay: number
  maxReconnectDelay: number
  heartbeatInterval: number
  heartbeatTimeout: number
  onMessage?: (data: unknown) => void
  onStateChange?: (status: WSStatus) => void
}

const DEFAULT_CONFIG: Partial<WSManagerConfig> = {
  maxReconnectAttempts: 10,
  baseReconnectDelay: 1000,
  maxReconnectDelay: 30000,
  heartbeatInterval: 30000,
  heartbeatTimeout: 5000,
}

// ─── WebSocket 管理器 Hook ──────────────────────────────────────────
export function useWSManager(config: WSManagerConfig) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const isManualCloseRef = useRef(false)
  const subscriptionsRef = useRef<Set<string>>(new Set())

  const [status, setStatus] = useState<WSStatus>({
    state: 'disconnected',
    latency: null,
    lastMessageTime: null,
    reconnectAttempts: 0,
    isStale: false,
  })

  const mergedConfig = { ...DEFAULT_CONFIG, ...config }

  // ─── 更新状态 ───────────────────────────────────────────────────
  const updateStatus = useCallback((partial: Partial<WSStatus>) => {
    setStatus(prev => {
      const next = { ...prev, ...partial }
      mergedConfig.onStateChange?.(next)
      return next
    })
  }, [mergedConfig])

  // ─── 指数退避计算 ───────────────────────────────────────────────
  const getReconnectDelay = useCallback((attempt: number): number => {
    const delay = Math.min(
      mergedConfig.baseReconnectDelay! * Math.pow(2, attempt),
      mergedConfig.maxReconnectDelay!
    )
    // 添加随机抖动防止惊群
    const jitter = delay * 0.2 * Math.random()
    return delay + jitter
  }, [mergedConfig])

  // ─── 清理定时器 ─────────────────────────────────────────────────
  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current)
      heartbeatTimerRef.current = null
    }
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current)
      heartbeatTimeoutRef.current = null
    }
  }, [])

  // ─── 心跳检测 ───────────────────────────────────────────────────
  const startHeartbeat = useCallback(() => {
    clearTimers()

    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        // 发送 ping
        wsRef.current.send(JSON.stringify({ type: 'ping', ts: Date.now() }))

        // 设置超时检测
        heartbeatTimeoutRef.current = setTimeout(() => {
          logger.warn('[WS] 心跳超时，判定连接失效')
          wsRef.current?.close(4000, 'Heartbeat timeout')
        }, mergedConfig.heartbeatTimeout!)
      }
    }, mergedConfig.heartbeatInterval!)
  }, [clearTimers, mergedConfig])

  // ─── 重连逻辑 ───────────────────────────────────────────────────
  const reconnect = useCallback(() => {
    if (isManualCloseRef.current) return
    if (reconnectAttemptsRef.current >= mergedConfig.maxReconnectAttempts!) {
      updateStatus({ state: 'failed', isStale: true })
      logger.error('[WS] 达到最大重连次数', new Error('Max reconnect attempts reached'))
      return
    }

    const delay = getReconnectDelay(reconnectAttemptsRef.current)
    reconnectAttemptsRef.current++

    updateStatus({
      state: 'reconnecting',
      isStale: true,
      reconnectAttempts: reconnectAttemptsRef.current,
    })

    logger.info(`[WS] 第 ${reconnectAttemptsRef.current} 次重连，延迟 ${Math.round(delay)}ms`)

    reconnectTimerRef.current = setTimeout(() => {
      connect()
    }, delay)
  }, [mergedConfig, getReconnectDelay, updateStatus])

  // ─── 重订阅 ─────────────────────────────────────────────────────
  const resubscribe = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN && subscriptionsRef.current.size > 0) {
      logger.info(`[WS] 重连成功，重新订阅 ${subscriptionsRef.current.size} 个频道`)
      subscriptionsRef.current.forEach(topic => {
        wsRef.current?.send(JSON.stringify({ type: 'subscribe', topic }))
      })
    }
  }, [])

  // ─── 建立连接 ───────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
    }

    updateStatus({ state: 'connecting' })
    logger.info('[WS] 正在连接...', { url: mergedConfig.url })

    const ws = new WebSocket(mergedConfig.url, mergedConfig.protocols)
    wsRef.current = ws

    const connectStart = Date.now()

    ws.onopen = () => {
      const latency = Date.now() - connectStart
      reconnectAttemptsRef.current = 0

      updateStatus({
        state: 'connected',
        latency,
        isStale: false,
        reconnectAttempts: 0,
      })

      logger.info('[WS] 连接成功', { latency })
      startHeartbeat()
      resubscribe()
    }

    ws.onmessage = (event) => {
      updateStatus({ lastMessageTime: new Date() })

      // 清除心跳超时
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current)
        heartbeatTimeoutRef.current = null
      }

      try {
        const data = JSON.parse(event.data)
        
        // 处理 pong 响应
        if (data.type === 'pong') {
          const latency = Date.now() - (data.ts || 0)
          updateStatus({ latency })
          return
        }

        mergedConfig.onMessage?.(data)
      } catch (e) {
        logger.warn('[WS] 消息解析失败', { raw: event.data })
      }
    }

    ws.onerror = (event) => {
      logger.error('[WS] 连接错误', event as unknown as Error)
    }

    ws.onclose = (event) => {
      clearTimers()
      
      if (!isManualCloseRef.current) {
        updateStatus({ state: 'disconnected', isStale: true })
        reconnect()
      }
    }
  }, [mergedConfig, updateStatus, startHeartbeat, clearTimers, reconnect, resubscribe])

  // ─── 断开连接 ───────────────────────────────────────────────────
  const disconnect = useCallback(() => {
    isManualCloseRef.current = true
    clearTimers()
    wsRef.current?.close(1000, 'Manual disconnect')
    updateStatus({ state: 'disconnected', isStale: false })
  }, [clearTimers, updateStatus])

  // ─── 订阅管理 ───────────────────────────────────────────────────
  const subscribe = useCallback((topic: string) => {
    subscriptionsRef.current.add(topic)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'subscribe', topic }))
    }
  }, [])

  const unsubscribe = useCallback((topic: string) => {
    subscriptionsRef.current.delete(topic)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'unsubscribe', topic }))
    }
  }, [])

  // ─── 页面可见性处理 ─────────────────────────────────────────────
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // 页面隐藏：暂停心跳，减少资源消耗
        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current)
          heartbeatTimerRef.current = null
        }
      } else {
        // 页面显示：恢复心跳，检查连接状态
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          startHeartbeat()
        } else if (status.state === 'disconnected' || status.state === 'reconnecting') {
          reconnect()
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [startHeartbeat, reconnect, status.state])

  // ─── 组件卸载清理 ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      isManualCloseRef.current = true
      clearTimers()
      wsRef.current?.close()
    }
  }, [clearTimers])

  return {
    status,
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    reconnect,
  }
}

export default useWSManager
