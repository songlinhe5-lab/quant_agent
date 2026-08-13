'use client'

import { useEffect, useState } from 'react'
import { Activity, Bot, ShieldAlert, Bell, List, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAlertEvents } from '@/hooks/use-alert-api'
import { useOms } from '@/features/trading/use-oms'
import { OmsBotGrid } from '@/features/trading/oms-bot-grid'
import { RiskModule } from '@/features/trading/risk'
import { EventsList } from '@/features/alert/alert-lists'
import { useWatchlist } from '@/stores/use-watchlist'
import { EmptyState } from '@/components/ui/data-display'
import { SymbolContextMenu } from '@/components/symbol-context-menu'

/**
 * PROD-04f: 监控模式专属布局
 * 告警流自动升格为主视图 + Bot 状态矩阵 + 风控仪表盘 优先级布局。
 */
export function MonitorModeLayout() {
  const { events, loading: eventsLoading, fetchEvents, ackEvent } = useAlertEvents()
  const { bots, isKilled, logsEndRefs, handleToggleBotStatus, handleStopBot } = useOms()
  const { watchlist, addTicker, removeTicker } = useWatchlist()

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  const unreadCount = events.filter((e) => !e.acknowledged).length
  const runningBots = bots.filter((b) => b.status === 'running').length

  return (
    <div className="h-[calc(100vh-80px)] flex flex-col gap-3">
      {/* 顶部总览条 */}
      <div className="flex items-center justify-between px-1 shrink-0">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 text-scene scene-accent-transition" />
          <h1 className="text-lg font-bold">监控总览</h1>
          <span className="text-[10px] font-mono text-muted-foreground">
            {runningBots}/{bots.length} 算力节点运行
          </span>
        </div>
        <span
          className={cn(
            'flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full',
            unreadCount > 0 ? 'bg-amber-500/10 text-amber-500' : 'bg-emerald-500/10 text-emerald-400',
          )}
        >
          <Bell className="h-3 w-3" /> {unreadCount} 条未读告警
        </span>
      </div>

      {/* 主区：左侧（告警流主视图 + 自选股监控） + 右侧 Bot 矩阵/风控仪表盘 */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-3 min-h-0">
        {/* 左侧列：告警流（上） + 自选股监控（下） */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* 实时告警流（主视图） */}
          <div className="flex-1 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden min-h-0">
            <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0 flex items-center gap-2">
              <Bell className="h-3.5 w-3.5 text-scene scene-accent-transition" />
              <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">实时告警流</span>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {eventsLoading ? (
                <div className="flex items-center justify-center h-32 text-[10px] text-muted-foreground">加载告警事件...</div>
              ) : events.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
                  <Activity className="h-8 w-8 mb-2 opacity-30" />
                  <p className="text-xs">暂无告警事件</p>
                </div>
              ) : (
                <EventsList events={events} onAck={ackEvent} />
              )}
            </div>
          </div>

          {/* 自选股监控 */}
          <div className="h-[280px] flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden shrink-0">
            <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0 flex items-center gap-2">
              <List className="h-3.5 w-3.5 text-scene scene-accent-transition" />
              <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">自选股监控</span>
              <span className="ml-auto text-[10px] font-mono text-muted-foreground">{watchlist.length} 只标的</span>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              <WatchlistMonitor watchlist={watchlist} removeTicker={removeTicker} addTicker={addTicker} />
            </div>
          </div>
        </div>

        {/* 右侧列：Bot 状态矩阵 + 风控仪表盘 */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Bot 状态矩阵 */}
          <div className="flex-1 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden min-h-0">
            <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0 flex items-center gap-2">
              <Bot className="h-3.5 w-3.5 text-scene scene-accent-transition" />
              <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">Bot 状态矩阵</span>
            </div>
            <div className="flex-1 min-h-0 flex flex-col">
              {bots.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-[10px] text-muted-foreground">暂无运行中的算力节点</div>
              ) : (
                <OmsBotGrid
                  bots={bots}
                  isKilled={isKilled}
                  logsEndRefs={logsEndRefs}
                  onToggleBotStatus={handleToggleBotStatus}
                  onStopBot={handleStopBot}
                />
              )}
            </div>
          </div>

          {/* 风控仪表盘 */}
          <div className="flex-1 flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden min-h-0">
            <div className="px-4 py-2.5 border-b border-border/40 bg-secondary/20 shrink-0 flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-scene scene-accent-transition" />
              <span className="text-[11px] font-bold tracking-widest uppercase text-muted-foreground">风控仪表盘</span>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
              <RiskModule />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const cleanSym = (s: string) =>
  s.replace(/^(US|HK|SH|SZ|JP|SG|UK)\./i, '').replace(/\.(HK|SH|SZ|SS)$/i, '')

function fmtSymbol(sym: string) {
  if (sym.startsWith('US.')) return sym.replace('US.', '')
  if (sym.startsWith('HK.')) return `${sym.replace('HK.', '')}.HK`
  if (sym.startsWith('SH.')) return `${sym.replace('SH.', '')}.SH`
  if (sym.startsWith('SZ.')) return `${sym.replace('SZ.', '')}.SZ`
  return sym
}

/**
 * 自选股监控面板：实时监听 quote_update 事件刷新价格/涨跌幅。
 * PROD 下 watchlist 默认空，自动回落 EmptyState 并给出添加引导（不注入假数据）。
 */
function WatchlistMonitor({
  watchlist,
  removeTicker,
  addTicker,
}: {
  watchlist: { symbol: string; price: number; change: number }[]
  removeTicker: (s: string) => void
  addTicker: (s: string) => void
}) {
  const [live, setLive] = useState<Record<string, { price: number; change: number }>>({})

  useEffect(() => {
    const handler = (e: Event) => {
      const q = (e as CustomEvent).detail
      const ticker = q.ticker || q.requested_ticker
      if (!ticker) return
      const sym = cleanSym(String(ticker))
      const price = parseFloat(q.last_price) || 0
      const change = parseFloat(String(q.change_pct ?? '0').replace('%', '')) || 0
      setLive((prev) => ({ ...prev, [sym]: { price, change } }))
    }
    window.addEventListener('quote_update', handler)
    return () => window.removeEventListener('quote_update', handler)
  }, [])

  if (watchlist.length === 0) {
    return (
      <EmptyState
        className="h-full"
        title="自选列表为空"
        description="监控总览需要订阅标的才能展示实时行情。请在行情页添加自选股，或手动输入代码。"
        icon={<List className="h-8 w-8 opacity-30" />}
        action={
          <div className="flex items-center gap-2 justify-center">
            <input
              type="text"
              placeholder="输入代码，如 AAPL / 00700.HK"
              className="h-8 px-3 rounded-md bg-secondary/30 border border-border/50 text-[11px] font-mono focus:outline-none focus:border-[hsl(var(--scene-accent))]/50"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.target as HTMLInputElement).value.trim()) {
                  addTicker((e.target as HTMLInputElement).value.trim().toUpperCase())
                  ;(e.target as HTMLInputElement).value = ''
                }
              }}
            />
            <button
              onClick={(e) => {
                const input = (e.currentTarget.previousElementSibling as HTMLInputElement)
                if (input?.value.trim()) {
                  addTicker(input.value.trim().toUpperCase())
                  input.value = ''
                }
              }}
              className="h-8 px-3 rounded-md bg-[hsl(var(--scene-accent))]/15 border border-[hsl(var(--scene-accent))]/30 text-[hsl(var(--scene-accent))] text-[11px] font-bold flex items-center gap-1 hover:bg-[hsl(var(--scene-accent))]/25 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" /> 添加
            </button>
          </div>
        }
      />
    )
  }

  return (
    <div className="divide-y divide-border/20">
      {watchlist.map((item) => {
        const sym = cleanSym(item.symbol)
        const l = live[sym]
        const price = l?.price || item.price
        const change = l?.change ?? (typeof item.change === 'number' ? item.change : 0)
        return (
          <SymbolContextMenu
            key={item.symbol}
            symbol={item.symbol}
            onRemove={removeTicker}
          >
            <div className="flex items-center justify-between gap-2 px-4 py-2 cursor-pointer hover:bg-secondary/50 transition-colors">
              <span className="text-[11px] font-bold font-mono truncate">{fmtSymbol(item.symbol)}</span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
                  {price ? price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--'}
                </span>
                <span className={cn('text-[10px] font-mono font-semibold tabular-nums w-12 text-right', change >= 0 ? 'text-emerald-500' : 'text-red-500')}>
                  {change >= 0 ? '+' : ''}{change.toFixed(2)}%
                </span>
              </div>
            </div>
          </SymbolContextMenu>
        )
      })}
    </div>
  )
}
