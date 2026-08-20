import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface BasicInfoRecord {
  code?: string
  name?: string
  list_time?: string
  lot_size?: number
  stock_type?: string
  [k: string]: unknown
}

interface BasicInfoData {
  data?: BasicInfoRecord[]
  panel?: {
    available?: boolean
    count?: number
    market?: string
    sec_type?: string
    note?: string
  }
  source?: string
  updated_at?: string
}

export function StockBasicInfoPanel({ market = 'HK', secType = 'STOCK' }: { market?: string; secType?: string }) {
  const [data, setData] = useState<BasicInfoData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: BasicInfoData }>(`/market/stock-basicinfo?market=${encodeURIComponent(market)}&sec_type=${encodeURIComponent(secType)}`)
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
  }, [market, secType])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载基础信息 ({market}/{secType})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        基础信息暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data || !data.data?.length) return <div className="p-6 text-sm text-slate-400">暂无基础信息数据</div>

  const rows = data.data.slice(0, 20)

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">全市场基础信息</span>
        <span className="font-mono text-xs text-foreground/80">{data.panel?.market || market}/{data.panel?.sec_type || secType}</span>
        <span className="ml-auto text-[10px] font-mono text-[hsl(var(--ai))]">共 {data.panel?.count ?? rows.length} 只</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-slate-500 border-b border-border/20">
              <th className="text-left px-3 py-1.5 font-medium">代码</th>
              <th className="text-left px-3 py-1.5 font-medium">名称</th>
              <th className="text-right px-3 py-1.5 font-medium">每手</th>
              <th className="text-left px-3 py-1.5 font-medium">上市日</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-border/10 hover:bg-secondary/20">
                <td className="px-3 py-1 font-mono text-foreground/80">{r.code || '--'}</td>
                <td className="px-3 py-1 text-foreground/70 truncate max-w-[120px]">{r.name || '--'}</td>
                <td className="px-3 py-1 text-right font-mono text-slate-400">{r.lot_size ?? '--'}</td>
                <td className="px-3 py-1 font-mono text-slate-400">{r.list_time || '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 全市场基础信息'} · 仅展示前 {rows.length} 条 · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
