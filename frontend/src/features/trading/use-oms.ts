'use client'

import { useState, useEffect, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'
import { apiClient, API_BASE_URL, getValidAccessToken } from '@/lib/api-client'
import { confirmDanger } from '@/components/confirm-dialog'
import type { LiveBot, ActiveOrder, HistoricalTrade, AlgoExecution, Position } from './oms-types'
import { useTradingModeStore } from '@/stores/useTradingModeStore'
import { useBackendStatusStore } from '@/stores/useBackendStatusStore'
import {
  applyTradingModeFromWs,
  requestTradingModeSwitch,
} from './trading-mode-actions'
import { formatModeLabel, type TradingMode, TRADING_MODES } from './trading-mode-types'
import { useKeepAliveActive } from '@/components/layout/keep-alive-outlet'

export function useOms() {
  const { toast } = useToast()
  const [bots, setBots] = useState<LiveBot[]>([])
  const [activeOrders, setActiveOrders] = useState<ActiveOrder[]>([])
  const [historicalTrades, setHistoricalTrades] = useState<HistoricalTrade[]>([])
  const [algoExecutions, setAlgoExecutions] = useState<AlgoExecution[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  // 💡 Futu OpenD 连接状态：区分"未连接"与"真·0 持仓"，避免误导用户
  const [futuStatus, setFutuStatus] = useState<{ connected: boolean; status: string; error_msg?: string } | null>(null)
  const [cancelingOrders, setCancelingOrders] = useState<Set<string>>(new Set())
  const [showAlgoModal, setShowAlgoModal] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<ActiveOrder | null>(null)
  const [isConsoleOpen, setIsConsoleOpen] = useState(true)
  const [isKilled, setIsKilled] = useState(false)
  const [isStale, setIsStale] = useState(false)
  const tradingMode = useTradingModeStore((s) => s.mode)
  const setTradingMode = useTradingModeStore((s) => s.setMode)
  const logsEndRefs = useRef<{ [key: string]: HTMLDivElement | null }>({})
  const keepAliveActive = useKeepAliveActive()

  // 💡 探测 Futu OpenD 连接状态（供持仓空态区分"未连接" vs "真·0 仓"）
  const fetchFutuStatus = async () => {
    try {
      const res = await apiClient.get('/api/v1/futu/source')
      const local = res?.data?.local
      if (local) {
        setFutuStatus({
          connected: !!local.connected,
          status: local.status || '',
          error_msg: local.error_msg,
        })
      }
    } catch {
      // 状态探测失败不阻断主流程，保持上一次的状态
    }
  }

  // 💡 接入真实 WebSocket 数据流
  useEffect(() => {
    let isMounted = true
    let ws: WebSocket | null = null
    let reconnectTimer: NodeJS.Timeout

    // 1. Fetch initial state via REST
    const fetchInitialState = async () => {
      try {
        const res = await apiClient.get('/oms/state')
        if (isMounted && res.data?.status === 'success') {
          const { bots: botsData, active_orders, historical_trades, algo_executions, trading_mode } = res.data.data
          setBots(botsData || [])
          setActiveOrders(active_orders || [])
          setHistoricalTrades(historical_trades || [])
          setAlgoExecutions(algo_executions || [])
          if (trading_mode && (TRADING_MODES as string[]).includes(trading_mode)) {
            setTradingMode(trading_mode as TradingMode)
          }
        }
        // OMS-04: 拉取真实持仓
        const posRes = await apiClient.get('/oms/positions', { market: 'HK' })
        if (isMounted && posRes?.status === 'success') {
          setPositions(posRes.data || [])
        } else if (isMounted && posRes?.data?.status === 'success') {
          setPositions(posRes.data.data || [])
        }
        // OMS-04.1: 同步拉取 Futu 连接状态，区分"未连接"与"真·0 仓"
        if (isMounted) await fetchFutuStatus()
      } catch (error) {
        console.error("Failed to fetch initial OMS state:", error)
        toast({
          variant: 'destructive',
          title: '获取初始状态失败',
          description: '无法连接到 OMS 数据网关，请检查后端服务。',
        })
      }
    }

    // 2. Connect to WebSocket for real-time updates
    const connect = async () => {
      if (!isMounted) return
      // 💡 keep-alive 后台模块 / 页面隐藏时不建立 WS，避免多模块 WS 并发重连风暴
      if (!keepAliveActive || document.visibilityState !== 'visible') return

      // 💡 统一 Token 获取：内部自动处理过期检测 + Refresh 续期
      const token = await getValidAccessToken()
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = API_BASE_URL.startsWith('http')
        ? API_BASE_URL.replace(/^http/, 'ws') + '/oms/ws' + (token ? `?token=${token}` : '')
        : `${protocol}//${window.location.host}${API_BASE_URL}/oms/ws` + (token ? `?token=${token}` : '')
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        if (isMounted) {
          setIsStale(false)
        }
        // WS 握手成功 = 后端在线（覆盖"REST 正常但 WS 故障"的纯 WS 不可达场景）
        useBackendStatusStore.getState().registerSuccess()
        console.log('[OMS WS] Connected.')
      }

      ws.onmessage = (event) => {
        if (!isMounted) return
        try {
          const msg = JSON.parse(event.data)
          
          switch (msg.type) {
            case 'bots_update':
              setBots(msg.data)
              break
            case 'bot_log':
              setBots(prev => prev.map(b => {
                if (b.id === msg.data.bot_id) {
                  const newLogs = [...b.logs, msg.data.log].slice(-50) // Keep last 50 logs
                  return { ...b, logs: newLogs }
                }
                return b
              }))
              break
            case 'active_orders_update':
              setActiveOrders(msg.data)
              break
            case 'new_trade':
              setHistoricalTrades(prev => [msg.data, ...prev].slice(0, 50)) // Keep last 50 trades
              break
            case 'algo_executions_update':
              setAlgoExecutions(msg.data)
              break
            case 'positions_update':
              if (msg.data?.market === 'HK') setPositions(msg.data.positions || [])
              break
            case 'mode_change':
              applyTradingModeFromWs(msg.data?.mode)
              break
            default:
              break
          }
        } catch (e) {
          console.error('[OMS WS] Error parsing message:', e)
        }
      }

      ws.onclose = () => {
        if (isMounted) {
          setIsStale(true)
          console.warn('[OMS WS] Disconnected. Reconnecting in 3s...')
          // 💡 后台/隐藏模块不重连，交由可见性/激活态恢复时统一重连
          if (!keepAliveActive || document.visibilityState !== 'visible') return
          reconnectTimer = setTimeout(connect, 3000)
        }
      }

      ws.onerror = () => {
        // WebSocket 的 error 事件规范上不携带可读错误信息（仅 type:'error' 的 Event 空壳），
        // 连接级错误统一视为后端不可达，计入离线检测；重连交由 onclose 处理。
        useBackendStatusStore.getState().registerFailure('OMS WebSocket 连接失败')
        console.warn('[OMS WS] 连接错误，等待 onclose 触发重连（后端可能不可达）')
        // 不在此显式 close()：error 后浏览器必定自动触发 onclose，重复 close 可能引发重连风暴
      }
    }

    fetchInitialState()
    connect()

    // 💡 每 30s 轮询 Futu 连接状态（与持仓同步守护进程同频），连接恢复时实时反映
    const futuStatusTimer = setInterval(fetchFutuStatus, 30000)

    // 💡 页面可见性 / keep-alive 激活态变化
    const handleVisibilityOrActive = () => {
      if (!isMounted) return
      if (!keepAliveActive || document.visibilityState !== 'visible') {
        if (ws) { ws.onclose = null; ws.close(); ws = null }
      } else {
        connect()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityOrActive)

    return () => {
      isMounted = false
      clearTimeout(reconnectTimer)
      clearInterval(futuStatusTimer)
      document.removeEventListener('visibilitychange', handleVisibilityOrActive)
      ws?.close()
    }
  }, [toast, keepAliveActive])

  // 💡 自动滚动日志到底部
  useEffect(() => {
    bots.forEach(b => {
      const ref = logsEndRefs.current[b.id]
      if (ref) ref.scrollIntoView({ behavior: 'smooth' })
    })
  }, [bots])

  // 💡 快捷键监听：`~` 键唤起或收起控制台
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '`' || e.key === '~') {
        e.preventDefault()
        setIsConsoleOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // 🚨 全局熔断逻辑 (OMS-10: 使用 ConfirmDialog + CLOSE ALL 文字确认)
  const handleKillSwitch = async () => {
    if (isKilled) return
    const confirmed = await confirmDanger(
      '⚠️ 全局物理熔断 (KILL SWITCH)',
      '将立刻切断所有算力节点，撤销全部挂单，并以市价平掉所有多空仓位。此操作不可撤销！',
      { confirmLabel: '执行熔断', cancelLabel: '取消', requireInputConfirm: 'CLOSE ALL' }
    )
    if (!confirmed) return
    setIsKilled(true)
    try {
      await apiClient.post('/oms/kill_switch', { timestamp: Date.now() })
      toast({ variant: 'destructive', title: '🚨 全局熔断已触发', description: '所有算力节点已强行下线，市价清仓指令已下达！' })
      setBots(prev => prev.map(b => ({
        ...b, 
        status: 'error' as const, 
        cpu: 0, 
        logs: [...b.logs, { time: new Date().toLocaleTimeString('zh-CN', { hour12: false }), msg: '🚨 KILL SWITCH ENGAGED. FORCE CLOSE ALL POSITIONS.', type: 'warn' as const }] 
      })))
    } catch (error) {
      toast({ variant: 'destructive', title: '熔断指令发送失败', description: '请立即检查网络或登录券商 APP 强制平仓！' })
      setIsKilled(false)
    }
  }
  
  // 🔄 模式切换确认 (OMS-11 → FE-PROD-02 三模式)
  const handleModeSwitch = async () => {
    const cycle: TradingMode[] = ['SANDBOX', 'PAPER', 'LIVE']
    const idx = cycle.indexOf(tradingMode)
    const targetMode = cycle[(idx + 1) % cycle.length]
    const ok = await requestTradingModeSwitch(targetMode)
    if (ok) {
      toast({ title: '模式已切换', description: formatModeLabel(targetMode) })
    }
  }

  // 🛑 防并发的撤单逻辑
  const handleCancelOrder = async (orderId: string) => {
    if (cancelingOrders.has(orderId)) return
    setCancelingOrders(prev => new Set(prev).add(orderId))
    try {
      // 💡 幂等性防重复提交锁 (Idempotency Key)
      const idempotencyKey = crypto.randomUUID()
      await apiClient.post(`/oms/orders/${orderId}/cancel`, { idempotency_key: idempotencyKey })
      toast({ title: '撤单指令已发送', description: `订单号: ${orderId}` })
    } catch (error) {
      toast({ variant: 'destructive', title: '撤单失败', description: `订单 ${orderId} 撤销请求被拒绝` })
    } finally {
      setCancelingOrders(prev => {
        const next = new Set(prev)
        next.delete(orderId)
        return next
      })
    }
  }

  // 🛑 单独暂停/恢复算力节点 (机器人) 逻辑
  const handleToggleBotStatus = async (botId: string, currentStatus: string) => {
    // 处于 error 状态的机器人通常需要人工介入排查或重启，拒绝直接 toggle
    if (currentStatus === 'error') return
    
    const action = currentStatus === 'running' ? 'pause' : 'resume'
    try {
      // 乐观更新 UI (界面瞬间响应，随后等待 WebSocket 确认真实状态)
      setBots(prev => prev.map(b => b.id === botId ? { ...b, status: action === 'pause' ? 'paused' : 'running' } : b))
      
      await apiClient.post(`/oms/bots/${botId}/${action}`)
      toast({ title: `指令已发送`, description: `正在尝试${action === 'pause' ? '暂停' : '恢复'}机器人 ${botId}` })
    } catch (error) {
      toast({ variant: 'destructive', title: '操作失败', description: `无法${action === 'pause' ? '暂停' : '恢复'}机器人，网络异常` })
    }
  }

  // 🛑 终止单个 Bot 算力节点 (OMS-05)
  const handleStopBot = async (botId: string) => {
    if (!confirm(`⚠️ 确认终止 Bot ${botId}？此操作不可逆。`)) return
    try {
      setBots(prev => prev.map(b => b.id === botId ? { ...b, status: 'stopped' } : b))
      await apiClient.post(`/oms/bots/${botId}/stop`)
      toast({ title: 'Bot 已终止', description: `算力节点 ${botId} 已安全下线` })
    } catch (error) {
      toast({ variant: 'destructive', title: '终止失败', description: '网络异常或节点已离线' })
    }
  }

  return {
    bots,
    activeOrders,
    historicalTrades,
    algoExecutions,
    positions,
    cancelingOrders,
    futuStatus,
    showAlgoModal,
    setShowAlgoModal,
    selectedOrder,
    setSelectedOrder,
    isConsoleOpen,
    setIsConsoleOpen,
    isKilled,
    isStale,
    tradingMode,
    logsEndRefs,
    handleKillSwitch,
    handleModeSwitch,
    handleCancelOrder,
    handleToggleBotStatus,
    handleStopBot,
  }
}
