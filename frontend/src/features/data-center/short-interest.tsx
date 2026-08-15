import React from 'react'
import { TrendingDown, Clock, AlertTriangle, FileBarChart } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface UsShortInterestData {
  market: string
  market_name: string
  as_of?: string
  short_sale_volume?: number | null
  total_volume?: number | null
  short_volume_ratio?: number | null
  short_interest_shares?: number | null
  short_interest_ratio?: number | null
  sources?: string[]
  note?: string
  updated_at: string
}

interface ShortInterestPanelProps {
  data: UsShortInterestData | null
  status?: string
  lastUpdated?: string
}

// 大数字缩写（百万/十亿），用于做空总股数这类巨量指标
function abbrNum(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '--'
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(2)}K`
  return n.toLocaleString('zh-CN')
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '--'
  return `${(n * 100).toFixed(2)}%`
}

function fmtDays(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '--'
  return `${n.toFixed(2)} 天`
}

// 安全格式化更新时间：lastUpdated 可能已是格式化好的时间字符串（如 "15:20:33"），
// 若再次 new Date() 解析会失败得到 Invalid Date。先尝试解析，失败时原样返回字符串。
function formatUpdatedAt(v: string | undefined): string {
  if (!v) return ''
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleTimeString('zh-CN', { hour12: false })
}

export function ShortInterestPanel({ data, status, lastUpdated }: ShortInterestPanelProps) {
  // 拿不到就不展示（零幻觉：无真实源则整卡隐藏，不渲染空壳）
  if (!data || status === 'error') {
    return null
  }

  // 仅当至少存在一个有效做空指标时才渲染，否则隐藏
  const hasAny = [
    data.short_sale_volume,
    data.total_volume,
    data.short_volume_ratio,
    data.short_interest_shares,
    data.short_interest_ratio,
  ].some((v) => v != null && !Number.isNaN(v))
  if (!hasAny) return null

  const rows = [
    { label: '做空总股数', value: abbrNum(data.short_interest_shares), hint: 'Short Interest (股)' },
    { label: '回补天数', value: fmtDays(data.short_interest_ratio), hint: 'Days to Cover' },
    { label: '做空成交量占比', value: fmtPct(data.short_volume_ratio), hint: 'Short Vol Ratio' },
  ]

  return (
    <div className="space-y-2">
      {/* 面板标题（与融资融券余额拆分开） */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-foreground/90">美股做空指标 (CBOE/FINRA)</h3>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-600 dark:text-sky-400">
            卖空
          </span>
        </div>
        {lastUpdated && (
          <div className="flex items-center gap-1 text-[9px] text-muted-foreground/50">
            <Clock className="w-3 h-3" />
            <span>更新于 {formatUpdatedAt(lastUpdated)}</span>
          </div>
        )}
      </div>

      <div className="glass-panel p-3 rounded-xl border border-border/20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {rows.map((r) => (
            <div key={r.label} className="flex flex-col">
              <span className="text-[10px] text-muted-foreground/70">{r.label}</span>
              <span className="text-base font-bold font-mono tabular-nums text-foreground/90 mt-0.5">
                {r.value}
              </span>
              <span className="text-[8px] text-muted-foreground/40 font-mono">{r.hint}</span>
            </div>
          ))}
        </div>

        {/* 数据来源 / 备注 */}
        <div className="mt-2 pt-1.5 border-t border-border/10">
          <div className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
            <FileBarChart className="w-2.5 h-2.5" />
            <span>{(data.sources || []).join(' · ') || data.market_name}</span>
            {data.as_of && (
              <span className="ml-1 font-mono">结算日 {data.as_of}</span>
            )}
          </div>
          {data.note && (
            <div className="flex items-center gap-1 mt-0.5 text-[8px] text-amber-500/70">
              <AlertTriangle className="w-2.5 h-2.5" />
              <span>{data.note}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
