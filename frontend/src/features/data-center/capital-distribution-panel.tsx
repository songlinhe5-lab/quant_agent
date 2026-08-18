import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface CapitalDistSignal {
  type: 'main_inflow_price_down' | 'main_outflow_price_up' | string
  label: string
  note?: string
}

interface CapitalDistributionData {
  ticker?: string
  main_net?: number
  retail_net?: number
  institution_dominance?: number
  signals?: CapitalDistSignal[]
  updated_at?: string
  source?: string
  note?: string
}

function signalTone(t: string): string {
  if (t === 'main_inflow_price_down') return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
  if (t === 'main_outflow_price_up') return 'text-red-400 border-red-500/30 bg-red-500/10'
  return 'text-slate-300 border-border/40 bg-secondary/10'
}

export function CapitalDistributionPanel({ ticker = 'HK.00700' }: { ticker?: string }) {
  const [data, setData] = useState<CapitalDistributionData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: CapitalDistributionData }>(`/market/capital-distribution/${ticker}`)
      .then((res) => {
        // 响应被 response_envelope_middleware 二次包装为 {code,msg,data:{status,data,source},ts}
        // 需再解一层 .data 才能拿到真正的 CapitalDistributionData（与 analyst-vs-fundamental-panel 一致）
        if (!cancelled) setData((res.data as any)?.data ?? (res.data as any) ?? null)
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
  }, [ticker])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载主力筹码分层 ({ticker})…</div>
  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        主力筹码数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无主力筹码数据</div>

  const fmt = (v?: number) => (v == null || Number.isNaN(v) ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(2)} 亿`)

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">主力筹码分层</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker}</span>
        {data.note && <span className="ml-auto text-[9px] text-amber-400/80">{data.note}</span>}
      </div>
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">主力净额</div>
          <div className={'text-base font-semibold font-mono ' + (data.main_net != null && data.main_net >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>{fmt(data.main_net)}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">散户净额</div>
          <div className={'text-base font-semibold font-mono ' + (data.retail_net != null && data.retail_net >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]')}>{fmt(data.retail_net)}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">机构主导度</div>
          <div className="text-base font-semibold font-mono text-[#8b5cf6]">{data.institution_dominance != null ? `${(data.institution_dominance * 100).toFixed(1)}%` : '--'}</div>
        </div>
      </div>
      {data.signals && data.signals.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pb-3">
          {data.signals.map((s, i) => (
            <span key={i} className={'text-[10px] font-mono px-2 py-0.5 rounded border ' + signalTone(s.type)} title={s.note || ''}>
              {s.label}
            </span>
          ))}
        </div>
      )}
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 主力资金分层'} · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
