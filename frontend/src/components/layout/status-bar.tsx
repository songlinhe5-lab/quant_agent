/**
 * 底部 StatusBar 组件
 * FE-02: 显示 WS 连接状态灯、当前延迟 ms、账户净值、当日盈亏
 */

import { Activity, Wifi, WifiOff, RefreshCw, DollarSign, TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { WSConnectionState } from '@/hooks/use-ws-manager'

// ─── 状态配置 ───────────────────────────────────────────────────────
const stateConfig: Record<WSConnectionState, { color: string; label: string; icon: typeof Wifi }> = {
  connecting: { color: 'text-amber-400', label: '连接中', icon: RefreshCw },
  connected: { color: 'text-emerald-400', label: '已连接', icon: Wifi },
  disconnected: { color: 'text-red-400', label: '已断开', icon: WifiOff },
  reconnecting: { color: 'text-amber-400', label: '重连中', icon: RefreshCw },
  failed: { color: 'text-red-500', label: '连接失败', icon: WifiOff },
}

// ─── Props ──────────────────────────────────────────────────────────
interface StatusBarProps {
  // WebSocket 状态
  wsState: WSConnectionState
  latency: number | null
  onReconnect?: () => void

  // 账户信息（可选）
  accountValue?: number
  dailyPnL?: number
  dailyPnLPercent?: number

  // 额外信息
  className?: string
}

// ─── 主组件 ─────────────────────────────────────────────────────────
export function StatusBar({
  wsState,
  latency,
  onReconnect,
  accountValue,
  dailyPnL,
  dailyPnLPercent,
  className,
}: StatusBarProps) {
  const config = stateConfig[wsState]
  const StatusIcon = config.icon
  const isConnected = wsState === 'connected'
  const isReconnecting = wsState === 'reconnecting' || wsState === 'connecting'

  // 延迟颜色
  const latencyColor = latency === null
    ? 'text-muted-foreground'
    : latency < 50
      ? 'text-emerald-400'
      : latency < 100
        ? 'text-amber-400'
        : 'text-red-400'

  // 盈亏颜色
  const pnlColor = (dailyPnL ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
  const PnLIcon = (dailyPnL ?? 0) >= 0 ? TrendingUp : TrendingDown

  return (
    <div
      className={cn(
        'h-6 px-3 flex items-center justify-between text-[10px] font-mono',
        'bg-muted/30 border-t border-border/40',
        'select-none',
        className
      )}
      role="status"
      aria-label="系统状态栏"
    >
      {/* 左侧：连接状态 */}
      <div className="flex items-center gap-3">
        {/* WS 连接状态 */}
        <button
          className="flex items-center gap-1.5 hover:bg-secondary/50 rounded px-1 py-0.5 transition-colors"
          onClick={onReconnect}
          title={`WebSocket: ${config.label}${isConnected ? '' : ' (点击重连)'}`}
          aria-label={`WebSocket 状态: ${config.label}`}
        >
          <span className="relative flex h-2 w-2">
            {/* 脉冲动画 */}
            {isConnected && (
              <span
                className={cn('animate-ping absolute inline-flex h-full w-full rounded-full opacity-75', config.color.replace('text-', 'bg-'))}
                aria-hidden="true"
              />
            )}
            {/* 状态点 */}
            <span className={cn('relative inline-flex rounded-full h-2 w-2', config.color.replace('text-', 'bg-'))} />
          </span>
          <StatusIcon className={cn('h-3 w-3', config.color, isReconnecting && 'animate-spin')} aria-hidden="true" />
          <span className={cn('hidden sm:inline', config.color)}>{config.label}</span>
        </button>

        {/* 延迟显示 */}
        <div className="flex items-center gap-1" title="网络延迟">
          <Activity className={cn('h-3 w-3', latencyColor)} aria-hidden="true" />
          <span className={latencyColor}>
            {latency !== null ? `${latency}ms` : '--'}
          </span>
        </div>
      </div>

      {/* 右侧：账户信息 */}
      <div className="flex items-center gap-3">
        {/* 账户净值 */}
        {accountValue !== undefined && (
          <div className="hidden md:flex items-center gap-1" title="账户净值">
            <DollarSign className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            <span className="text-foreground tabular-nums">
              {formatNumber(accountValue)}
            </span>
          </div>
        )}

        {/* 当日盈亏 */}
        {dailyPnL !== undefined && (
          <div className="flex items-center gap-1" title={`当日盈亏: ${formatCurrency(dailyPnL)}`}>
            <PnLIcon className={cn('h-3 w-3', pnlColor)} aria-hidden="true" />
            <span className={cn('tabular-nums', pnlColor)}>
              {dailyPnL >= 0 ? '+' : ''}{formatCurrency(dailyPnL)}
            </span>
            {dailyPnLPercent !== undefined && (
              <span className={cn('tabular-nums text-muted-foreground')}>
                ({dailyPnLPercent >= 0 ? '+' : ''}{dailyPnLPercent.toFixed(2)}%)
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── 工具函数 ───────────────────────────────────────────────────────
function formatNumber(num: number): string {
  if (num >= 1e9) return `${(num / 1e9).toFixed(2)}B`
  if (num >= 1e6) return `${(num / 1e6).toFixed(2)}M`
  if (num >= 1e3) return `${(num / 1e3).toFixed(2)}K`
  return num.toFixed(2)
}

function formatCurrency(num: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

// ─── 简化版状态指示器（用于 Header） ────────────────────────────────
interface StatusIndicatorProps {
  state: WSConnectionState
  latency: number | null
  compact?: boolean
}

export function StatusIndicator({ state, latency, compact }: StatusIndicatorProps) {
  const config = stateConfig[state]
  const StatusIcon = config.icon

  return (
    <div className="flex items-center gap-1.5" title={`连接: ${config.label} | 延迟: ${latency ?? '--'}ms`}>
      <span className="relative flex h-2 w-2">
        {state === 'connected' && (
          <span
            className={cn('animate-ping absolute inline-flex h-full w-full rounded-full opacity-75', config.color.replace('text-', 'bg-'))}
            aria-hidden="true"
          />
        )}
        <span className={cn('relative inline-flex rounded-full h-2 w-2', config.color.replace('text-', 'bg-'))} />
      </span>
      {!compact && <StatusIcon className={cn('h-3 w-3', config.color)} aria-hidden="true" />}
    </div>
  )
}

export default StatusBar
