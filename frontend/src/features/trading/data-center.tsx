import { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { LayoutGrid, Coins, CalendarRange } from 'lucide-react'
import { useDashboardData, type HubTab } from '@/features/data-center/use-dashboard-data'
import { OverviewTab } from '@/features/data-center/data-center-overview'
import { CapitalFlowTab } from '@/features/data-center/data-center-capital-flow'
import { CalendarsTab } from '@/features/data-center/data-center-calendars'
import { MarketClocks } from '@/features/data-center/shared'
import { useSystemStore } from '@/stores/useSystemStore'

const WS_STATUS = {
  CONNECTED: { dot: 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse', text: '实时推送已连接', color: 'text-emerald-400' },
  CONNECTING: { dot: 'bg-amber-500 animate-pulse', text: '正在连接...', color: 'text-amber-400' },
  DISCONNECTED: { dot: 'bg-red-500', text: '推送已断开', color: 'text-red-400' },
} as const

export const DCNavTab = ({ active, id, label, icon: Icon, onClick }: { active: boolean; id: string; label: string; icon: any; onClick: () => void }) => (
  <button
    id={id}
    onClick={onClick}
    className={cn(
      'relative flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all whitespace-nowrap',
      active
        ? 'bg-primary/15 text-primary shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50',
    )}
  >
    <Icon className="h-4 w-4" />
    {label}
    {active && <span className="absolute -bottom-[1px] left-1/2 -translate-x-1/2 h-[2px] w-8 rounded-full bg-primary" />}
  </button>
)

export function DataCenterContent() {
  const [activeTab, setActiveTab] = useState<HubTab>('overview')
  const d = useDashboardData()
  const wsStatus = useSystemStore((s) => s.wsStatus)

  const tabs: { id: HubTab; label: string; icon: any }[] = [
    { id: 'overview', label: '概览', icon: LayoutGrid },
    { id: 'capital', label: '资金流', icon: Coins },
    { id: 'calendars', label: '宏观日历', icon: CalendarRange },
  ]

  const handleNavigate = (tab: HubTab, _assetSymbol?: string) => setActiveTab(tab)

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/30 bg-card/30 backdrop-blur-sm">
        <div>
          <h1 className="text-lg font-bold text-foreground tracking-tight">数据中心与宏观</h1>
          <p className="text-[11px] text-muted-foreground">多源聚合 · 实时刷新</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[10px] font-mono">
            <span className={cn('h-2 w-2 rounded-full', WS_STATUS[wsStatus].dot)} />
            <span className={cn(WS_STATUS[wsStatus].color)}>{WS_STATUS[wsStatus].text}</span>
          </div>
          {d.last && <span className="text-[10px] text-muted-foreground font-mono">更新 {d.last}</span>}
          <MarketClocks />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-4 pt-2 overflow-x-hidden border-b border-border/20">
        {tabs.map((t) => (
          <DCNavTab key={t.id} active={activeTab === t.id} id={`dc-tab-${t.id}`} label={t.label} icon={t.icon} onClick={() => handleNavigate(t.id)} />
        ))}
        <div className="ml-auto flex items-center gap-2 pr-1">
          {d.fetching && <span className="text-[10px] text-muted-foreground animate-pulse">同步中…</span>}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        {activeTab === 'overview' && <OverviewTab data={d} onNavigate={handleNavigate} />}
        {activeTab === 'capital' && <CapitalFlowTab data={d} onNavigate={handleNavigate} />}
        {activeTab === 'calendars' && <CalendarsTab />}
      </div>
    </div>
  )
}

export function DataCenterModule() {
  return <DataCenterContent />
}
