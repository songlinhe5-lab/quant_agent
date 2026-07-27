'use client'

import { useEffect } from 'react'
import { Activity, Bot, ShieldAlert, Bell } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAlertEvents } from '@/hooks/use-alert-api'
import { useOms } from '@/features/trading/use-oms'
import { OmsBotGrid } from '@/features/trading/oms-bot-grid'
import { RiskModule } from '@/features/trading/risk'
import { EventsList } from '@/features/alert/alert-lists'

/**
 * PROD-04f: 监控模式专属布局
 * 告警流自动升格为主视图 + Bot 状态矩阵 + 风控仪表盘 优先级布局。
 */
export function MonitorModeLayout() {
  const { events, loading: eventsLoading, fetchEvents, ackEvent } = useAlertEvents()
  const { bots, isKilled, logsEndRefs, handleToggleBotStatus, handleStopBot } = useOms()

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

      {/* 主区：左侧告警流（主视图） + 右侧 Bot 矩阵/风控仪表盘 */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-3 min-h-0">
        {/* 实时告警流（主视图） */}
        <div className="flex flex-col bg-background/50 glass-card rounded-xl border border-border/40 overflow-hidden min-h-0">
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
