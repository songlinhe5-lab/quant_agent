import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface ShortSellData {
  ticker?: string
  mode?: string
  short_sale_ratio?: number
  short_value?: number
  total_value?: number
  shareable_ratio?: number
  market_short_ratio?: number
  crowdedness_pct?: number
  signal?: string
  updated_at?: string
  source?: string
  note?: string
}

function signalTone(s?: string): string {
  if (s === 'squeeze_alert') return 'text-red-400 border-red-500/30 bg-red-500/10'
  if (s === 'crowded_short') return 'text-amber-400 border-amber-500/30 bg-amber-500/10'
  if (s === 'low_short') return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
  return 'text-slate-300 border-border/40 bg-secondary/10'
}

function signalText(s?: string): string {
  if (s === 'squeeze_alert') return '⚠️ 挤空预警'
  if (s === 'crowded_short') return '做空拥挤'
  if (s === 'low_short') return '做空清淡'
  return '中性'
}

export function ShortSellingPanel({ ticker = 'HK.00700', mode = 'rank' }: { ticker?: string; mode?: string }) {
  const [data, setData] = useState<ShortSellData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: ShortSellData }>(`/market/short-selling/${ticker}/${mode}`)
      .then((res) => {
        // 方案 B：路由返回扁平 payload（{ticker, mode, futu, regulatory, derived, source, degraded}），直接读信封层
        if (!cancelled) setData((res.data as any) ?? null)
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
  }, [ticker, mode])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载港股卖空拥挤度 ({ticker})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        卖空数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无卖空数据</div>

  const cards = [
    { label: '卖空成交占比', v: data.short_sale_ratio != null ? (data.short_sale_ratio * 100).toFixed(1) + '%' : '--' },
    { label: '可借券比例', v: data.shareable_ratio != null ? (data.shareable_ratio * 100).toFixed(1) + '%' : '--' },
    { label: '市场卖空占比', v: data.market_short_ratio != null ? (data.market_short_ratio * 100).toFixed(1) + '%' : '--' },
    { label: '拥挤度分位', v: data.crowdedness_pct != null ? (data.crowdedness_pct * 100).toFixed(1) + '%' : '--' },
  ]

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">港股卖空拥挤度</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker}</span>
        <span className="text-[10px] text-slate-500">({data.mode || mode})</span>
        {data.signal && (
          <span className={'ml-auto text-[10px] font-mono px-2 py-0.5 rounded border ' + signalTone(data.signal)}>
            {signalText(data.signal)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-4 gap-2 p-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
            <div className="text-[10px] text-slate-500">{c.label}</div>
            <div className="text-sm font-semibold font-mono text-foreground/90">{c.v}</div>
          </div>
        ))}
      </div>
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 卖空 + HKEX 交叉验证'} · {data.note || '卖空占比经 HKEX 市场级校准'} · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
