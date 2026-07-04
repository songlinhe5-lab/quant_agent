'use client'

import React, { useState, useEffect, useRef } from 'react'
import { ShieldAlert, Cpu, MemoryStick, Activity, Terminal, ListOrdered, History, GitPullRequest, X, ChevronUp, ChevronDown, Bot, Play, Pause, PowerOff, MapPin, ShieldCheck, ShieldOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { useToast } from '@/hooks/use-toast'
import { apiClient, API_BASE_URL, getAccessToken } from '@/lib/api-client'
import { confirmDanger } from '@/components/confirm-dialog'

// ── Type Definitions ───────────────────────────────────────────────────────
interface BotLog {
  time: string;
  msg: string;
  type: 'info' | 'warn' | 'success';
}

interface LiveBot {
  id: string;
  name: string;
  ticker: string;
  status: 'running' | 'paused' | 'stopped' | 'error';
  cpu: number;
  mem: number;
  logs: BotLog[];
}

interface ActiveOrder {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  price: string;
  qty: number;
  filled: number;
  status: 'PENDING' | 'SUBMITTED' | 'PARTIALLY_FILLED';
  time: string;
}

interface HistoricalTrade {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  avg_price: string;
  qty: number;
  pnl: number;
  time: string;
}

interface AlgoExecution {
  id: string;
  algo_type: 'TWAP' | 'VWAP' | 'ICEBERG';
  symbol: string;
  target_qty: number;
  filled_qty: number;
  avg_price: string;
  progress: number;
  status: 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'ERROR';
  message?: string;
}

interface Position {
  code: string;
  stock_name?: string;
  position_side: string;
  qty: number;
  can_sell_qty?: number;
  cost_price: number;
  market_val: number;
  pl_val: number;
  pl_ratio: number;
}

// ── 算法拆单表单组件 ────────────────────────────────────────────────────────
function AlgoOrderModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast()
  const [algoType, setAlgoType] = useState('TWAP')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('BUY')
  const [qty, setQty] = useState('')
  const [duration, setDuration] = useState('60')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!symbol || !qty || Number(qty) <= 0) {
      toast({ variant: 'destructive', title: '验证失败', description: '请填写正确的标的代码和数量' })
      return
    }
    setIsSubmitting(true)
    try {
      await apiClient.post('/oms/algo/start', {
        algo_type: algoType,
        symbol: symbol.toUpperCase(),
        side,
        target_qty: Number(qty),
        duration_minutes: Number(duration)
      })
      toast({ title: '算法单已下发', description: `成功启动 ${algoType} 拆单任务` })
      onClose()
    } catch (error: any) {
      toast({ variant: 'destructive', title: '下发失败', description: error.message || '网络异常' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-md bg-card border border-border/50 rounded-xl shadow-2xl flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
          <h3 className="text-sm font-bold flex items-center gap-2"><GitPullRequest className="w-4 h-4 text-indigo-500" /> 新建算法拆单任务</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/50 transition-colors"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">算法类型 (Algo Type)</label>
              <select value={algoType} onChange={e => setAlgoType(e.target.value)} className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary">
                <option value="TWAP">TWAP (时间加权)</option>
                <option value="VWAP">VWAP (成交量加权)</option>
                <option value="ICEBERG">Iceberg (冰山委托)</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">标的代码 (Symbol)</label>
              <input type="text" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="如: US.AAPL" className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono uppercase" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">买卖方向 (Side)</label>
              <div className="flex bg-background border border-border/50 rounded-md p-1">
                <button onClick={() => setSide('BUY')} className={cn("flex-1 text-xs py-1.5 rounded transition-colors font-bold", side === 'BUY' ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "text-muted-foreground hover:bg-secondary/50")}>买入 BUY</button>
                <button onClick={() => setSide('SELL')} className={cn("flex-1 text-xs py-1.5 rounded transition-colors font-bold", side === 'SELL' ? "bg-red-500/10 text-red-600 dark:text-red-400" : "text-muted-foreground hover:bg-secondary/50")}>卖出 SELL</button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground font-medium">目标数量 (Target Qty)</label>
              <input type="number" value={qty} onChange={e => setQty(e.target.value)} placeholder="0" className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono tabular-nums" />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-muted-foreground font-medium">执行时长 ({algoType === 'ICEBERG' ? '单笔可见数量' : '分钟'})</label>
            <input type="number" value={duration} onChange={e => setDuration(e.target.value)} className="bg-background border border-border/50 rounded-md px-3 py-2 text-sm outline-none focus:border-primary font-mono tabular-nums" />
          </div>
        </div>
        <div className="px-4 py-3 border-t border-border/30 bg-secondary/10 flex justify-end gap-2 shrink-0">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 text-xs">取消</Button>
          <Button size="sm" className="h-8 text-xs bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm" onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? '下发中...' : '提交执行'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── 订单详情弹窗组件 ────────────────────────────────────────────────────────
function OrderDetailModal({ order, onClose }: { order: ActiveOrder; onClose: () => void }) {
  const { toast } = useToast()
  const [newPrice, setNewPrice] = useState(order.price)
  const [isModifying, setIsModifying] = useState(false)

  const handleModify = async () => {
    if (!newPrice || isNaN(Number(newPrice))) {
      toast({ variant: 'destructive', title: '验证失败', description: '请输入有效的修改价格' })
      return
    }
    setIsModifying(true)
    try {
      // 调用后端改单接口 (假设后端支持该路由)
      await apiClient.post(`/oms/orders/${order.id}/modify`, { price: Number(newPrice) })
      toast({ title: '改单指令已下发', description: `订单 ${order.id} 价格更新为 ${newPrice}` })
      onClose()
    } catch (error: any) {
      toast({ variant: 'destructive', title: '改单失败', description: error.message || '网络或接口异常' })
    } finally {
      setIsModifying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200" onClick={onClose}>
      <div className="w-full max-w-sm bg-card border border-border/50 rounded-xl shadow-2xl flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
          <h3 className="text-sm font-bold flex items-center gap-2"><ListOrdered className="w-4 h-4 text-indigo-500" /> 订单详情</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary/50 transition-colors"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="flex justify-between items-center pb-3 border-b border-border/20">
            <span className="text-2xl font-bold font-mono">{order.symbol}</span>
            <span className={cn("px-2 py-1 rounded font-bold text-xs", order.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
              {order.side}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-y-4 gap-x-6">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">订单号 (Order ID)</span>
              <span className="text-sm font-mono break-all">{order.id}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">状态 (Status)</span>
              <span className="text-sm font-bold">{order.status}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">委托价 (Price)</span>
              <span className="text-sm font-mono">{order.price}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground uppercase">委托量/已成交</span>
              <span className="text-sm font-mono">{order.qty} / {order.filled}</span>
            </div>
            <div className="flex flex-col gap-1 col-span-2">
              <span className="text-[10px] text-muted-foreground uppercase">下发时间 (Time)</span>
              <span className="text-sm font-mono">{order.time}</span>
            </div>
            
            {/* 💡 增加修改价格的快捷表单 */}
            <div className="flex flex-col gap-2 col-span-2 mt-2 pt-4 border-t border-border/20">
              <span className="text-[10px] text-muted-foreground uppercase">修改挂单价格 (Modify Price)</span>
              <div className="flex items-center gap-2">
                <input 
                  type="number" 
                  value={newPrice} 
                  onChange={e => setNewPrice(e.target.value)} 
                  className="flex-1 bg-background border border-border/50 rounded-md px-3 py-1.5 text-sm outline-none focus:border-primary font-mono tabular-nums" 
                />
                <Button 
                  size="sm" 
                  onClick={handleModify} 
                  disabled={isModifying || String(newPrice) === String(order.price)} 
                  className="h-8 text-xs bg-amber-500/10 text-amber-600 dark:text-amber-500 border border-amber-500/20 hover:bg-amber-500/20 shadow-none font-bold"
                >
                  {isModifying ? '提交中...' : '确认改单'}
                </Button>
              </div>
            </div>
          </div>
        </div>
        <div className="px-4 py-3 border-t border-border/30 bg-secondary/10 flex justify-end shrink-0">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 text-xs">关闭</Button>
        </div>
      </div>
    </div>
  )
}

// ── Components ─────────────────────────────────────────────────────────────

export function OMSModule() {
  const { toast } = useToast()
  const [bots, setBots] = useState<LiveBot[]>([])
  const [activeOrders, setActiveOrders] = useState<ActiveOrder[]>([])
  const [historicalTrades, setHistoricalTrades] = useState<HistoricalTrade[]>([])
  const [algoExecutions, setAlgoExecutions] = useState<AlgoExecution[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [cancelingOrders, setCancelingOrders] = useState<Set<string>>(new Set())
  const [showAlgoModal, setShowAlgoModal] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<ActiveOrder | null>(null)
  const [isConsoleOpen, setIsConsoleOpen] = useState(true)
  const [isKilled, setIsKilled] = useState(false)
  const [isStale, setIsStale] = useState(false)
  const [tradingMode, setTradingMode] = useState<'SANDBOX' | 'LIVE'>('SANDBOX')
  const logsEndRefs = useRef<{ [key: string]: HTMLDivElement | null }>({})

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
          if (trading_mode) setTradingMode(trading_mode)
        }
        // OMS-04: 拉取真实持仓
        const posRes = await apiClient.get('/oms/positions', { market: 'HK' })
        if (isMounted && posRes?.status === 'success') {
          setPositions(posRes.data || [])
        } else if (isMounted && posRes?.data?.status === 'success') {
          setPositions(posRes.data.data || [])
        }
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
    const connect = () => {
      if (!isMounted) return
      
      // 💡 动态构建 WebSocket URL，适配 HTTPS (wss) 与跨域环境变量
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const token = getAccessToken()
      const wsUrl = API_BASE_URL.startsWith('http')
        ? API_BASE_URL.replace(/^http/, 'ws') + '/oms/ws' + (token ? `?token=${token}` : '')
        : `${protocol}//${window.location.host}${API_BASE_URL}/oms/ws` + (token ? `?token=${token}` : '')
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        if (isMounted) setIsStale(false)
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
              if (msg.data?.mode) setTradingMode(msg.data.mode)
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
          reconnectTimer = setTimeout(connect, 3000)
        }
      }

      ws.onerror = (err) => {
        console.error('[OMS WS] Error:', err)
        ws?.close()
      }
    }

    fetchInitialState()
    connect()

    return () => {
      isMounted = false
      clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [toast])

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
  
  // 🔄 模式切换确认 (OMS-11) — 热切换，立即生效
  const handleModeSwitch = async () => {
    const targetMode = tradingMode === 'SANDBOX' ? 'LIVE' : 'SANDBOX'
    const confirmed = await confirmDanger(
      `切换交易模式: ${tradingMode} → ${targetMode}`,
      targetMode === 'LIVE'
        ? '即将进入实盘模式，所有交易将使用真实资金。请确认您已充分了解风险。'
        : '即将切换到沙箱模式，所有交易将在模拟环境中执行。',
      { confirmLabel: '确认切换', cancelLabel: '取消' }
    )
    if (!confirmed) return
    try {
      const res = await apiClient.post('/oms/mode/switch', { mode: targetMode })
      if (res.data?.status === 'success') {
        // 立即更新本地状态 (WebSocket 也会广播，双保险)
        setTradingMode(targetMode)
        toast({ title: '模式已切换', description: res.data.message })
      }
    } catch (error) {
      toast({ variant: 'destructive', title: '切换失败', description: '网络异常' })
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

  return (
    <div className="relative h-[calc(100vh-80px)] w-full flex flex-col overflow-hidden">
      
      {showAlgoModal && <AlgoOrderModal onClose={() => setShowAlgoModal(false)} />}
      {selectedOrder && <OrderDetailModal order={selectedOrder} onClose={() => setSelectedOrder(null)} />}
      
      {/* 💡 断流优雅降级保护 */}
      {isStale && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 z-[100]">
          <ShieldAlert className="h-12 w-12 text-amber-500 animate-pulse drop-shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
          <p className="mt-4 text-lg font-bold text-amber-500">OMS 数据网关断开 (STALE)</p>
          <p className="text-sm text-muted-foreground mt-1">正在尝试重新连接订单总线，页面状态已挂起...</p>
        </div>
      )}

      {/* ── OMS-11: 交易模式横幅 ─────────────────────────────────────────── */}
      <div className={cn(
        "flex-shrink-0 px-4 py-1.5 flex items-center justify-between border rounded-md mb-2 text-xs font-bold transition-colors",
        tradingMode === 'LIVE'
          ? "bg-red-500/10 border-red-500/30 text-red-500"
          : "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
      )}>
        <div className="flex items-center gap-2">
          {tradingMode === 'LIVE' ? <ShieldOff className="w-3.5 h-3.5" /> : <ShieldCheck className="w-3.5 h-3.5" />}
          <span>{tradingMode === 'LIVE' ? '实盘模式 (LIVE)' : '沙箱模式 (SANDBOX)'}</span>
          <span className="text-[10px] font-normal opacity-70">— {tradingMode === 'LIVE' ? '真实资金交易' : '模拟环境，无真实资金风险'}</span>
        </div>
        <button onClick={handleModeSwitch} className="px-2 py-0.5 rounded border border-current/30 hover:bg-current/10 transition-colors text-[10px]">
          切换模式
        </button>
      </div>

      {/* ── Top Bar & Kill Switch ─────────────────────────────────────────── */}
      <div className="flex-shrink-0 mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-1.5 rounded-full bg-amber-500 dark:bg-amber-400" aria-hidden="true" />
          <h1 className="text-base font-bold tracking-tight">订单中枢与算力节点</h1>
          <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5">
            OMS & Live Bots
          </span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* 💡 算法拆单新建按钮 */}
          <Button 
            onClick={() => setShowAlgoModal(true)}
            variant="outline"
            className="h-9 px-4 font-bold border-indigo-500/30 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-500/10 shadow-sm"
          >
            <GitPullRequest className="w-4 h-4 mr-1.5" />
            新建算法单
          </Button>

          {/* 🚨 物理级防误触大红按钮 */}
          <Button 
            onClick={handleKillSwitch}
            disabled={isKilled}
            className={cn(
              "h-9 px-6 font-bold tracking-widest uppercase transition-all duration-300 shadow-lg border",
              isKilled 
                ? "bg-red-950 text-red-500/50 border-red-900 cursor-not-allowed" 
                : "bg-red-600 hover:bg-red-500 text-white border-red-500 shadow-[0_0_15px_rgba(220,38,38,0.4)] hover:shadow-[0_0_25px_rgba(220,38,38,0.6)] animate-pulse"
            )}
          >
            <ShieldAlert className="w-4 h-4 mr-2" />
            {isKilled ? "已熔断 (KILLED)" : "全局熔断 (KILL SWITCH)"}
          </Button>
        </div>
      </div>

      {/* ── Main Canvas: Bots Factory ───────────────────────────────────── */}
      <div className={cn("flex-1 overflow-y-auto custom-scrollbar pb-[400px] transition-all", isKilled && "saturate-0 opacity-80")}>
        <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4 p-1">
          {bots.map(bot => (
            <div key={bot.id} className="glass-card rounded-xl overflow-hidden border border-border/40 shadow-sm flex flex-col h-[320px] transition-all hover:border-primary/30">
              
              {/* Bot Header */}
              <div className="px-4 py-3 border-b border-border/30 bg-secondary/20 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className={cn(
                    "p-1.5 rounded-md text-white shadow-sm",
                    bot.status === 'running' ? "bg-emerald-500" : bot.status === 'paused' ? "bg-amber-500" : "bg-red-500"
                  )}>
                    <Bot className="w-4 h-4" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-bold tracking-tight leading-none">{bot.name}</span>
                    <span className="text-[10px] text-muted-foreground font-mono mt-1">{bot.ticker}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider border",
                    bot.status === 'running' ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20" : 
                    bot.status === 'paused' ? "bg-amber-500/10 text-amber-600 border-amber-500/20" : 
                    "bg-red-500/10 text-red-600 border-red-500/20"
                  )}>
                    {bot.status}
                  </span>
                  <button 
                    onClick={() => handleToggleBotStatus(bot.id, bot.status)}
                    disabled={bot.status === 'error' || bot.status === 'stopped'}
                    className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50 disabled:cursor-not-allowed" 
                    title={bot.status === 'running' ? '暂停执行' : bot.status === 'paused' ? '恢复执行' : '节点已终止'}
                  >
                    {bot.status === 'running' ? <Pause className="w-3.5 h-3.5" /> : bot.status === 'paused' ? <Play className="w-3.5 h-3.5" /> : <PowerOff className="w-3.5 h-3.5" />}
                  </button>
                  {(bot.status === 'running' || bot.status === 'paused') && (
                    <button 
                      onClick={() => handleStopBot(bot.id)}
                      className="p-1 rounded text-red-500/70 hover:text-red-400 hover:bg-red-500/10 transition-colors" 
                      title="终止 Bot"
                    >
                      <PowerOff className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
              
              {/* Micro Resource Indicators */}
              <div className="px-4 py-3 border-b border-border/20 grid grid-cols-2 gap-4 bg-background/50">
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between items-center text-[10px] font-mono text-muted-foreground">
                    <span className="flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
                    <span>{bot.cpu.toFixed(1)}%</span>
                  </div>
                  <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-500 transition-all duration-500" style={{ width: `${bot.cpu}%` }} />
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between items-center text-[10px] font-mono text-muted-foreground">
                    <span className="flex items-center gap-1"><MemoryStick className="w-3 h-3" /> MEM</span>
                    <span>{bot.mem.toFixed(0)} MB</span>
                  </div>
                  <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
                    <div className="h-full bg-sky-500 transition-all duration-500" style={{ width: `${(bot.mem / 512) * 100}%` }} />
                  </div>
                </div>
              </div>

              {/* Cyberpunk Terminal Logs */}
              <div className="flex-1 bg-[#0a0a0a] dark:bg-black p-3 overflow-y-auto custom-scrollbar font-mono text-[10px] leading-relaxed relative">
                {bot.logs.map((log, idx) => (
                  <div key={idx} className="flex items-start gap-2 mb-1.5 opacity-90 hover:opacity-100">
                    <span className="text-slate-500 shrink-0">[{log.time}]</span>
                    <span className={cn(
                      "break-words",
                      log.type === 'success' ? "text-emerald-400" : 
                      log.type === 'warn' ? "text-amber-400" : 
                      "text-slate-300"
                    )}>
                      {log.msg}
                    </span>
                  </div>
                ))}
                <div ref={(el) => { logsEndRefs.current[bot.id] = el }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Bottom Console: OMS Terminal ──────────────────────────────────── */}
      <div className={cn(
        "absolute bottom-0 left-0 right-0 glass-card border-t border-border/50 shadow-2xl transition-all duration-300 flex flex-col z-50",
        isConsoleOpen ? "h-[350px] translate-y-0" : "h-[40px] translate-y-[calc(100%-40px)]"
      )}>
        <div 
          className="h-[40px] px-4 flex items-center justify-between cursor-pointer bg-secondary/30 hover:bg-secondary/50 transition-colors shrink-0"
          onClick={() => setIsConsoleOpen(!isConsoleOpen)}
        >
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-wider">
            <Terminal className="w-4 h-4" />
            OMS 控制台 (Console)
          </div>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-mono">
            <span className="hidden sm:inline-flex items-center gap-1"><Activity className="w-3 h-3 text-emerald-500" /> API: 12ms</span>
            <span className="hidden sm:inline-block">快捷键: ~</span>
            {isConsoleOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </div>
        </div>

        {isConsoleOpen && (
          <div className="flex-1 overflow-hidden bg-background">
            <Tabs defaultValue="active" className="h-full flex flex-col">
              <TabsList className="bg-transparent border-b border-border/30 rounded-none h-10 px-4 justify-start shrink-0">
                <TabsTrigger value="active" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                  <ListOrdered className="w-3.5 h-3.5 mr-1.5" /> 活动挂单 ({activeOrders.length})
                </TabsTrigger>
                <TabsTrigger value="history" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                  <History className="w-3.5 h-3.5 mr-1.5" /> 历史成交
                </TabsTrigger>
                <TabsTrigger value="algo" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                  <GitPullRequest className="w-3.5 h-3.5 mr-1.5" /> 算法拆单进度
                </TabsTrigger>
                <TabsTrigger value="positions" className="text-xs data-[state=active]:bg-transparent data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none h-10 px-4">
                  <MapPin className="w-3.5 h-3.5 mr-1.5" /> 真实持仓 ({positions.length})
                </TabsTrigger>
              </TabsList>

              {/* Active Orders Grid */}
              <TabsContent value="active" className="flex-1 m-0 overflow-auto custom-scrollbar">
                <table className="w-full text-xs text-left whitespace-nowrap">
                  <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">订单号</th>
                      <th className="px-4 py-2.5 font-medium">时间</th>
                      <th className="px-4 py-2.5 font-medium">标的</th>
                      <th className="px-4 py-2.5 font-medium">方向</th>
                      <th className="px-4 py-2.5 font-medium text-right">报单价</th>
                      <th className="px-4 py-2.5 font-medium text-right">数量</th>
                      <th className="px-4 py-2.5 font-medium text-right">已成交</th>
                      <th className="px-4 py-2.5 font-medium text-center">状态</th>
                      <th className="px-4 py-2.5 font-medium text-center">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20 font-mono">
                    {activeOrders.map(order => (
                      <tr key={order.id} className="hover:bg-secondary/10 transition-colors cursor-pointer" onClick={() => setSelectedOrder(order)}>
                        <td className="px-4 py-2 text-muted-foreground">{order.id}</td>
                        <td className="px-4 py-2 text-muted-foreground">{order.time}</td>
                        <td className="px-4 py-2 font-bold text-foreground">{order.symbol}</td>
                        <td className="px-4 py-2">
                          <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]", order.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
                            {order.side}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right">{order.price}</td>
                        <td className="px-4 py-2 text-right">{order.qty}</td>
                        <td className="px-4 py-2 text-right">{order.filled}</td>
                        <td className="px-4 py-2 text-center">
                          <span className={cn("text-[10px] px-2 py-0.5 rounded-full border", 
                            order.status === 'PENDING' ? 'border-amber-500/30 text-amber-500' : 
                            order.status === 'PARTIALLY_FILLED' ? 'border-sky-500/30 text-sky-500' : 
                            'border-slate-500/30 text-slate-500'
                          )}>
                            {order.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-center">
                          <button 
                            onClick={(e) => { e.stopPropagation(); handleCancelOrder(order.id); }}
                            disabled={cancelingOrders.has(order.id)}
                            className="text-[10px] text-red-500 hover:text-red-400 hover:underline disabled:opacity-50 disabled:no-underline disabled:cursor-not-allowed"
                          >
                            {cancelingOrders.has(order.id) ? '撤单中...' : '撤单'}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {activeOrders.length === 0 && (
                      <tr><td colSpan={9} className="text-center py-8 text-muted-foreground">暂无活动挂单</td></tr>
                    )}
                  </tbody>
                </table>
              </TabsContent>

              {/* Historical Trades Grid */}
              <TabsContent value="history" className="flex-1 m-0 overflow-auto custom-scrollbar">
                <table className="w-full text-xs text-left whitespace-nowrap">
                  <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">成交编号</th>
                      <th className="px-4 py-2.5 font-medium">时间</th>
                      <th className="px-4 py-2.5 font-medium">标的</th>
                      <th className="px-4 py-2.5 font-medium">方向</th>
                      <th className="px-4 py-2.5 font-medium text-right">成交均价</th>
                      <th className="px-4 py-2.5 font-medium text-right">数量</th>
                      <th className="px-4 py-2.5 font-medium text-right">实现盈亏</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20 font-mono">
                    {historicalTrades.map(trade => (
                      <tr key={trade.id} className="hover:bg-secondary/10 transition-colors">
                        <td className="px-4 py-2 text-muted-foreground">{trade.id}</td>
                        <td className="px-4 py-2 text-muted-foreground">{trade.time}</td>
                        <td className="px-4 py-2 font-bold text-foreground">{trade.symbol}</td>
                        <td className="px-4 py-2">
                          <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]", trade.side === 'BUY' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500')}>
                            {trade.side}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right">{trade.avg_price}</td>
                        <td className="px-4 py-2 text-right">{trade.qty}</td>
                        <td className={cn("px-4 py-2 text-right font-bold", trade.pnl > 0 ? "text-emerald-500" : trade.pnl < 0 ? "text-red-500" : "text-muted-foreground")}>
                          {trade.pnl > 0 ? '+' : ''}{trade.pnl !== 0 ? trade.pnl.toFixed(2) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TabsContent>

              {/* Algo Execution Grid */}
              <TabsContent value="algo" className="flex-1 m-0 overflow-auto custom-scrollbar p-4 flex flex-col gap-4">
                {algoExecutions.map(algo => (
                  <div key={algo.id} className="border border-border/40 rounded-lg p-4 bg-secondary/10 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-foreground">{algo.algo_type} 拆单执行</span>
                        <span className="text-[10px] text-muted-foreground font-mono bg-secondary/50 px-2 py-0.5 rounded">{algo.symbol}</span>
                      </div>
                      <span className={cn("text-xs font-mono", algo.status === 'RUNNING' ? 'text-emerald-500' : algo.status === 'PAUSED' ? 'text-amber-500' : 'text-slate-500')}>
                        {algo.progress}% 完成 {algo.status === 'PAUSED' && '(暂停中)'}
                      </span>
                    </div>
                    <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
                      <div className={cn("h-full transition-all", algo.status === 'RUNNING' ? 'bg-emerald-500' : algo.status === 'PAUSED' ? 'bg-amber-500' : 'bg-slate-500')} style={{ width: `${algo.progress}%` }} />
                    </div>
                    <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
                      <span>目标: {algo.target_qty} 股</span>
                      <span>已成: {algo.filled_qty} 股 | 均价: {algo.avg_price}</span>
                      <span>{algo.message || (algo.status === 'RUNNING' ? '算法正在执行中...' : '已结束')}</span>
                    </div>
                  </div>
                ))}
                {algoExecutions.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-muted-foreground py-8">
                    <GitPullRequest className="h-8 w-8 mb-2 opacity-20" />
                    <p className="text-sm">暂无运行中的算法拆单任务</p>
                  </div>
                )}
              </TabsContent>

              {/* Real Positions (OMS-04) */}
              <TabsContent value="positions" className="flex-1 m-0 overflow-auto custom-scrollbar">
                <table className="w-full text-xs text-left whitespace-nowrap">
                  <thead className="bg-secondary/30 text-muted-foreground sticky top-0 z-10 backdrop-blur-sm">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">代码</th>
                      <th className="px-4 py-2.5 font-medium">名称</th>
                      <th className="px-4 py-2.5 font-medium">方向</th>
                      <th className="px-4 py-2.5 font-medium text-right">数量</th>
                      <th className="px-4 py-2.5 font-medium text-right">成本价</th>
                      <th className="px-4 py-2.5 font-medium text-right">市值</th>
                      <th className="px-4 py-2.5 font-medium text-right">盈亏</th>
                      <th className="px-4 py-2.5 font-medium text-right">盈亏比</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20 font-mono">
                    {positions.map((pos, idx) => (
                      <tr key={`${pos.code}-${idx}`} className="hover:bg-secondary/10 transition-colors">
                        <td className="px-4 py-2 font-bold text-foreground">{pos.code}</td>
                        <td className="px-4 py-2 text-muted-foreground">{pos.stock_name || '-'}</td>
                        <td className="px-4 py-2">
                          <span className={cn("px-1.5 py-0.5 rounded font-bold text-[10px]",
                            pos.position_side === 'LONG' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-red-500/15 text-red-500'
                          )}>
                            {pos.position_side}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right">{pos.qty}</td>
                        <td className="px-4 py-2 text-right">{pos.cost_price?.toFixed(2)}</td>
                        <td className="px-4 py-2 text-right">{pos.market_val?.toFixed(0)}</td>
                        <td className={cn("px-4 py-2 text-right font-bold", pos.pl_val > 0 ? "text-emerald-500" : pos.pl_val < 0 ? "text-red-500" : "text-muted-foreground")}>
                          {pos.pl_val > 0 ? '+' : ''}{pos.pl_val?.toFixed(2) || '0.00'}
                        </td>
                        <td className={cn("px-4 py-2 text-right font-bold",
                          pos.pl_ratio > 0 ? "text-emerald-500" : pos.pl_ratio < 0 ? "text-red-500" : "text-muted-foreground"
                        )}>
                          {pos.pl_ratio > 0 ? '+' : ''}{pos.pl_ratio != null ? (pos.pl_ratio * 100).toFixed(2) + '%' : '-'}
                        </td>
                      </tr>
                    ))}
                    {positions.length === 0 && (
                      <tr><td colSpan={8} className="text-center py-8 text-muted-foreground">暂无持仓数据 (等待 Futu 同步...)</td></tr>
                    )}
                  </tbody>
                </table>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  )
}