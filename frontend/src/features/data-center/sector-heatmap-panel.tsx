import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface HeatMapData {
  market?: string
  breadth_ratio?: number
  avg_change?: number
  sentiment?: string
  up?: number
  down?: number
  flat?: number
  top_gainers?: { name: string; code?: string; change: number }[]
  top_losers?: { name: string; code?: string; change: number }[]
  sector_summary?: { sector: string; avg_change: number }[]
  updated_at?: string
  source?: string
  note?: string
}

function toneBg(chg: number): string {
  if (chg >= 3) return 'bg-[#0ecb81]/30 border-[#0ecb81]/50'
  if (chg >= 1) return 'bg-[#0ecb81]/15 border-[#0ecb81]/30'
  if (chg > 0) return 'bg-[#0ecb81]/5 border-[#0ecb81]/20'
  if (chg <= -3) return 'bg-[#f6465d]/30 border-[#f6465d]/50'
  if (chg <= -1) return 'bg-[#f6465d]/15 border-[#f6465d]/30'
  return 'bg-[#f6465d]/5 border-[#f6465d]/20'
}

function sentimentTone(s?: string): string {
  if (s === 'risk_on') return 'text-emerald-400'
  if (s === 'risk_off') return 'text-red-400'
  return 'text-amber-400'
}

export function SectorHeatmapPanel({ market = 'HK' }: { market?: string }) {
  const [data, setData] = useState<HeatMapData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: HeatMapData }>(`/market/heat-map/${market}`)
      .then((res) => {
        if (!cancelled) setData(res.data ?? null)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [market])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载板块热力图 ({market})…</div>
  if (error) return <div className="p-6 text-sm text-red-400">板块热力图获取失败：{error}</div>
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无板块热力图数据</div>

  const sectors = data.sector_summary || []
  const gainers = data.top_gainers || []
  const losers = data.top_losers || []

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">板块热力图</span>
        <span className="font-mono text-xs text-foreground/80">{data.market || market}</span>
        {data.sentiment && (
          <span className={'ml-auto text-[10px] font-mono font-bold ' + sentimentTone(data.sentiment)}>
            情绪: {data.sentiment.toUpperCase()}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 p-3">
        <div className="space-y-1.5">
          <div className="text-[10px] text-slate-500 mb-1">板块涨跌分布（{sectors.length}）</div>
          {sectors.slice(0, 12).map((s, i) => (
            <div key={i} className={'flex items-center justify-between px-2 py-1 rounded border text-[11px] ' + toneBg(s.avg_change)}>
              <span className="truncate text-foreground/80">{s.sector}</span>
              <span className="font-mono tabular-nums">{s.avg_change >= 0 ? '+' : ''}{s.avg_change.toFixed(2)}%</span>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded border border-border/30 bg-card/40 py-1">
              <div className="text-[9px] text-slate-500">涨</div>
              <div className="text-sm font-bold text-[#0ecb81]">{data.up ?? '--'}</div>
            </div>
            <div className="rounded border border-border/30 bg-card/40 py-1">
              <div className="text-[9px] text-slate-500">平</div>
              <div className="text-sm font-bold text-slate-300">{data.flat ?? '--'}</div>
            </div>
            <div className="rounded border border-border/30 bg-card/40 py-1">
              <div className="text-[9px] text-slate-500">跌</div>
              <div className="text-sm font-bold text-[#f6465d]">{data.down ?? '--'}</div>
            </div>
          </div>
          <div className="text-[10px] text-slate-500">领涨</div>
          {gainers.slice(0, 4).map((g, i) => (
            <div key={i} className="flex items-center justify-between text-[11px] px-2 py-0.5 rounded bg-[#0ecb81]/5">
              <span className="truncate text-foreground/80">{g.name}</span>
              <span className="font-mono text-[#0ecb81]">+{g.change.toFixed(2)}%</span>
            </div>
          ))}
          <div className="text-[10px] text-slate-500 mt-1">领跌</div>
          {losers.slice(0, 4).map((l, i) => (
            <div key={i} className="flex items-center justify-between text-[11px] px-2 py-0.5 rounded bg-[#f6465d]/5">
              <span className="truncate text-foreground/80">{l.name}</span>
              <span className="font-mono text-[#f6465d]">{l.change.toFixed(2)}%</span>
            </div>
          ))}
        </div>
      </div>
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 板块热力图'} · 涨跌比 {data.breadth_ratio != null ? (data.breadth_ratio * 100).toFixed(1) + '%' : '--'} · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
