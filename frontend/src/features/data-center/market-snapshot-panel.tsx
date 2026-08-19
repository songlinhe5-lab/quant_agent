import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface SnapshotRecord {
  code?: string
  name?: string
  cur_price?: number
  last_price?: number
  price?: number
  change_rate?: number
  change?: number
  [k: string]: unknown
}

interface SnapshotData {
  data?: SnapshotRecord[]
  panel?: {
    available?: boolean
    count?: number
    avg_change?: number
    ups?: number
    downs?: number
    flats?: number
    note?: string
  }
  source?: string
  updated_at?: string
}

export function MarketSnapshotPanel({ tickers = 'HK.00700,US.AAPL,HK.09988' }: { tickers?: string }) {
  const [data, setData] = useState<SnapshotData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: SnapshotData }>(`/market/snapshot?tickers=${encodeURIComponent(tickers)}`)
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
  }, [tickers])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载批量快照…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        快照数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data || !data.data?.length) return <div className="p-6 text-sm text-slate-400">暂无快照数据</div>

  const panel = data.panel || {}
  const rows = data.data.slice(0, 12)

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">批量实时快照</span>
        {panel.avg_change != null && (
          <span className={'ml-auto text-[10px] font-mono font-bold ' + (panel.avg_change >= 0 ? 'text-[#34D399]' : 'text-[#F87171]')}>
            均值 {panel.avg_change >= 0 ? '+' : ''}{panel.avg_change.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="rounded border border-[#34D399]/30 bg-[#34D399]/5 px-2 py-1 text-center">
          <div className="text-[9px] text-slate-500">涨</div>
          <div className="text-sm font-bold text-[#34D399]">{panel.ups ?? 0}</div>
        </div>
        <div className="rounded border border-border/30 bg-secondary/10 px-2 py-1 text-center">
          <div className="text-[9px] text-slate-500">平</div>
          <div className="text-sm font-bold text-slate-300">{panel.flats ?? 0}</div>
        </div>
        <div className="rounded border border-[#F87171]/30 bg-[#F87171]/5 px-2 py-1 text-center">
          <div className="text-[9px] text-slate-500">跌</div>
          <div className="text-sm font-bold text-[#F87171]">{panel.downs ?? 0}</div>
        </div>
      </div>
      <div className="space-y-1 px-3 pb-3">
        {rows.map((r, i) => {
          const code = r.code || r.name || '--'
          const price = r.cur_price ?? r.last_price ?? r.price
          const chg = r.change_rate ?? r.change
          const tone = chg == null ? 'text-slate-300' : chg >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
          return (
            <div key={i} className="flex items-center justify-between text-[11px] px-2 py-0.5 rounded bg-secondary/5">
              <span className="font-mono text-foreground/80 truncate max-w-[120px]">{code}</span>
              <span className="font-mono text-slate-400">{price != null ? Number(price).toFixed(2) : '--'}</span>
              <span className={'font-mono ' + tone}>{chg != null ? (chg >= 0 ? '+' : '') + Number(chg).toFixed(2) + '%' : '--'}</span>
            </div>
          )
        })}
      </div>
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 实时快照'} · 共 {panel.count ?? rows.length} 只 · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
