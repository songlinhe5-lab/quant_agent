import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'

interface OptionVolData {
  ticker?: string
  iv?: number
  hv?: number
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
  rho?: number
  bid?: number
  ask?: number
  last_price?: number
  updated_at?: string
  source?: string
  note?: string
}

function greeksTone(v: number | undefined, positiveGood = true): string {
  if (v == null || Number.isNaN(v)) return 'text-slate-300'
  const good = positiveGood ? v >= 0 : v <= 0
  return good ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]'
}

export function OptionVolatilityPanel({ ticker = 'US.AAPL260320C200000' }: { ticker?: string }) {
  const [data, setData] = useState<OptionVolData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    apiClient
      .get<{ data: OptionVolData }>(`/market/option-volatility?ticker=${encodeURIComponent(ticker)}`)
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
  }, [ticker])

  if (loading) return <div className="p-6 text-sm text-slate-400">加载期权波动率 ({ticker})…</div>
  if (error) return <div className="p-6 text-sm text-red-400">期权波动率获取失败：{error}</div>
  if (!data) return <div className="p-6 text-sm text-slate-400">暂无期权波动率数据</div>

  const greeks = [
    { label: 'Delta', v: data.delta },
    { label: 'Gamma', v: data.gamma },
    { label: 'Theta', v: data.theta, posGood: false },
    { label: 'Vega', v: data.vega },
    { label: 'Rho', v: data.rho },
  ]

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">期权波动率 & Greeks</span>
        <span className="font-mono text-xs text-foreground/80 truncate max-w-[180px]">{data.ticker}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">隐含波动率 IV</div>
          <div className="text-base font-semibold font-mono text-[hsl(var(--ai))]">{data.iv != null ? (data.iv * 100).toFixed(1) + '%' : '--'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">历史波动率 HV</div>
          <div className="text-base font-semibold font-mono text-[#3b82f6]">{data.hv != null ? (data.hv * 100).toFixed(1) + '%' : '--'}</div>
        </div>
        <div className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
          <div className="text-[10px] text-slate-500">IV-HV 价差</div>
          <div className={'text-base font-semibold font-mono ' + (data.iv != null && data.hv != null ? (data.iv - data.hv >= 0 ? 'text-[hsl(var(--bull))]' : 'text-[hsl(var(--bear))]') : 'text-slate-300')}>
            {data.iv != null && data.hv != null ? (data.iv - data.hv >= 0 ? '+' : '') + ((data.iv - data.hv) * 100).toFixed(1) + '%' : '--'}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-5 gap-1.5 px-3 pb-3">
        {greeks.map((g) => (
          <div key={g.label} className="rounded border border-border/30 bg-card/30 px-2 py-1.5 text-center">
            <div className="text-[9px] text-slate-500">{g.label}</div>
            <div className={'text-sm font-semibold font-mono ' + greeksTone(g.v, g.posGood)}>
              {g.v != null ? g.v.toFixed(3) : '--'}
            </div>
          </div>
        ))}
      </div>
      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground text-center bg-secondary/10">
        数据源：{data.source || 'Futu 期权波动率'} · 入参须为期权 OCC 合约代码 · 更新于 {data.updated_at || '实时'}
      </div>
    </div>
  )
}
