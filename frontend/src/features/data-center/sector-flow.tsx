import React, { useState } from 'react'
import { TrendingUp, TrendingDown, Clock, AlertTriangle, BarChart3 } from 'lucide-react'
import { cn } from '@/lib/utils'

// ── 类型定义 ──────────────────────────────────────────────────────────────

export interface AShareSectorItem {
  name: string
  change_pct: number
  main_net_inflow: number
  main_net_pct: number
}

export interface HKSectorItem {
  name: string
  net_inflow: number
  pct: number
}

export interface USSectorItem {
  ticker: string
  name: string
  sector: string
  net_inflow: number
  unit: string
  dir: number
}

export interface SectorFundFlowData {
  a_share?: {
    status: string
    data?: {
      inflow_top: AShareSectorItem[]
      outflow_top: AShareSectorItem[]
      unit: string
      updated_at: string
      source: string
    }
  }
  hk?: {
    status: string
    data?: {
      sectors: HKSectorItem[]
      unit: string
      updated_at: string
      source: string
      note?: string
    }
  }
  us?: {
    status: string
    data?: {
      sectors: USSectorItem[]
      updated_at: string
      source: string
    }
  }
  updated_at?: string
}

interface SectorFlowPanelProps {
  data: SectorFundFlowData
  status?: string
}

// ── Tab 配置 ──────────────────────────────────────────────────────────────

const TABS = [
  { key: 'a_share', label: 'A股行业', flag: '🇨🇳' },
  { key: 'hk', label: '港股南向', flag: '🇭🇰' },
  { key: 'us', label: '美股板块', flag: '🇺🇸' },
] as const

type TabKey = (typeof TABS)[number]['key']

// ── A股行业 Tab ───────────────────────────────────────────────────────────

function AShareTab({ data }: { data: SectorFundFlowData['a_share'] }) {
  if (!data || data.status !== 'success' || !data.data) {
    return <EmptyState message="暂无A股行业资金流数据" />
  }

  const { inflow_top, outflow_top, unit, source, updated_at } = data.data

  return (
    <div className="space-y-3">
      {/* 净流入 Top 10 */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingUp className="w-3.5 h-3.5 text-emerald-500" />
          <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">主力净流入 Top 10</span>
        </div>
        <div className="space-y-1">
          {inflow_top.map((item, i) => (
            <div
              key={item.name}
              className="flex items-center justify-between py-1 px-2 rounded-lg bg-emerald-500/5 hover:bg-emerald-500/10 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-muted-foreground/50 w-4">{i + 1}</span>
                <span className="text-xs font-medium text-foreground/90">{item.name}</span>
                <span
                  className={cn(
                    'text-[10px] font-mono px-1 rounded',
                    item.change_pct >= 0
                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                      : 'bg-red-500/10 text-red-600 dark:text-red-400'
                  )}
                >
                  {item.change_pct >= 0 ? '+' : ''}
                  {item.change_pct.toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold font-mono text-emerald-600 dark:text-emerald-400">
                  +{item.main_net_inflow.toLocaleString()}
                  <span className="text-[8px] ml-0.5 opacity-60">{unit}</span>
                </span>
                <span className="text-[10px] font-mono text-muted-foreground/50 w-12 text-right">
                  {item.main_net_pct.toFixed(2)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 净流出 Top 5 */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingDown className="w-3.5 h-3.5 text-red-500" />
          <span className="text-xs font-bold text-red-600 dark:text-red-400">主力净流出 Top 5</span>
        </div>
        <div className="space-y-1">
          {outflow_top.map((item, i) => (
            <div
              key={item.name}
              className="flex items-center justify-between py-1 px-2 rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-muted-foreground/50 w-4">{i + 1}</span>
                <span className="text-xs font-medium text-foreground/90">{item.name}</span>
                <span
                  className={cn(
                    'text-[10px] font-mono px-1 rounded',
                    item.change_pct >= 0
                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                      : 'bg-red-500/10 text-red-600 dark:text-red-400'
                  )}
                >
                  {item.change_pct >= 0 ? '+' : ''}
                  {item.change_pct.toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold font-mono text-red-600 dark:text-red-400">
                  {item.main_net_inflow.toLocaleString()}
                  <span className="text-[8px] ml-0.5 opacity-60">{unit}</span>
                </span>
                <span className="text-[10px] font-mono text-muted-foreground/50 w-12 text-right">
                  {item.main_net_pct.toFixed(2)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <SourceFooter source={source} updatedAt={updated_at} />
    </div>
  )
}

// ── 港股南向 Tab ──────────────────────────────────────────────────────────

function HKTab({ data }: { data: SectorFundFlowData['hk'] }) {
  if (!data || data.status !== 'success' || !data.data || data.data.sectors.length === 0) {
    return <EmptyState message={data?.data?.note || '暂无港股南向行业数据'} />
  }

  const { sectors, unit, source, updated_at, note } = data.data
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.net_inflow)), 1)

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {sectors.map((item) => {
          const isPositive = item.net_inflow >= 0
          const barWidth = Math.min(Math.abs(item.net_inflow) / maxAbs * 100, 100)
          return (
            <div key={item.name} className="flex items-center gap-2">
              <span className="text-xs text-foreground/80 w-16 shrink-0 truncate">{item.name}</span>
              <div className="flex-1 h-4 bg-muted/30 rounded-full overflow-hidden relative">
                <div
                  className={cn(
                    'h-full rounded-full transition-all duration-500',
                    isPositive ? 'bg-emerald-500/60' : 'bg-red-500/60'
                  )}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              <span
                className={cn(
                  'text-[10px] font-mono w-20 text-right shrink-0',
                  isPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
                )}
              >
                {isPositive ? '+' : ''}
                {item.net_inflow.toLocaleString()} {unit}
              </span>
            </div>
          )
        })}
      </div>

      {note && (
        <div className="flex items-center gap-1 text-[9px] text-amber-500/70">
          <AlertTriangle className="w-2.5 h-2.5" />
          <span>{note}</span>
        </div>
      )}

      <SourceFooter source={source} updatedAt={updated_at} />
    </div>
  )
}

// ── 美股板块 Tab ──────────────────────────────────────────────────────────

function USTab({ data }: { data: SectorFundFlowData['us'] }) {
  if (!data || data.status !== 'success' || !data.data || data.data.sectors.length === 0) {
    return <EmptyState message="暂无美股板块资金流数据" />
  }

  const { sectors, source, updated_at } = data.data

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {sectors.map((item) => {
          const isPositive = item.dir >= 0
          return (
            <div
              key={item.ticker}
              className={cn(
                'glass-panel p-2.5 rounded-xl border transition-all duration-300',
                isPositive
                  ? 'border-emerald-500/20 hover:border-emerald-500/40'
                  : 'border-red-500/20 hover:border-red-500/40'
              )}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-foreground/90">{item.name}</span>
                {isPositive ? (
                  <TrendingUp className="w-3 h-3 text-emerald-500" />
                ) : (
                  <TrendingDown className="w-3 h-3 text-red-500" />
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-muted-foreground/50">{item.sector}</span>
                <span
                  className={cn(
                    'text-xs font-bold font-mono',
                    isPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
                  )}
                >
                  {isPositive ? '+' : ''}
                  {item.net_inflow.toFixed(2)}
                  <span className="text-[8px] ml-0.5 opacity-60">{item.unit}</span>
                </span>
              </div>
            </div>
          )
        })}
      </div>

      <SourceFooter source={source} updatedAt={updated_at} />
    </div>
  )
}

// ── 通用组件 ──────────────────────────────────────────────────────────────

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground/50">
      <AlertTriangle className="w-4 h-4" />
      <span className="text-xs">{message}</span>
    </div>
  )
}

function SourceFooter({ source, updatedAt }: { source?: string; updatedAt?: string }) {
  return (
    <div className="flex items-center justify-between pt-2 border-t border-border/10">
      <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
        <span className="inline-block w-1 h-1 rounded-full bg-emerald-400/60" />
        <span>{source}</span>
      </div>
      {updatedAt && (
        <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
          <Clock className="w-2.5 h-2.5" />
          <span className="font-mono tabular-nums">
            {new Date(updatedAt).toLocaleTimeString('zh-CN', { hour12: false })}
          </span>
        </div>
      )}
    </div>
  )
}

// ── 主面板 ────────────────────────────────────────────────────────────────

export function SectorFlowPanel({ data, status }: SectorFlowPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('a_share')

  if (!data || (!data.a_share && !data.hk && !data.us)) {
    return (
      <div className="glass-panel p-4 rounded-xl border border-border/20">
        <div className="flex items-center justify-center gap-2 text-muted-foreground/50">
          <BarChart3 className="w-4 h-4" />
          <span className="text-xs">暂无板块资金流数据</span>
        </div>
      </div>
    )
  }

  return (
    <div className="glass-panel p-4 rounded-xl border border-border/20">
      {/* 面板标题 + Tab 切换 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-bold text-foreground/90">板块资金流向</h3>
          {status === 'partial' && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
              部分数据
            </span>
          )}
        </div>

        {/* Tab 切换按钮 */}
        <div className="flex items-center gap-0.5 bg-muted/30 rounded-lg p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-all duration-200',
                activeTab === tab.key
                  ? 'bg-background shadow-sm text-foreground'
                  : 'text-muted-foreground/60 hover:text-foreground/80'
              )}
            >
              <span>{tab.flag}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Tab 内容 */}
      {activeTab === 'a_share' && <AShareTab data={data.a_share} />}
      {activeTab === 'hk' && <HKTab data={data.hk} />}
      {activeTab === 'us' && <USTab data={data.us} />}
    </div>
  )
}
