import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { EmptyState } from '@/components/ui/data-display/EmptyState'

/** 后端 derived 字段（facade.get_short_selling）。占比均为**百分比数值**，前端不得再 ×100。 */
interface ShortSellDerived {
  /** 个股卖空成交占比（%）——daily 模式产出 */
  short_sale_ratio?: number
  /** 卖空榜中位占比（%）——rank 模式产出 */
  short_sale_ratio_median?: number
  crowding_level?: 'high' | 'mid' | 'low'
  /** T-1 数据日期 */
  as_of?: string
  daily_series?: { date?: string; ratio?: number | null }[]
  alert_signal?: { type?: string; severity?: string; message?: string } | null
}

interface ShortSellData {
  ticker?: string
  mode?: string
  futu?: { status?: string; count?: number; message?: string }
  regulatory?: { short_volume_ratio?: number; as_of?: string; note?: string }
  derived?: ShortSellDerived | null
  source?: string
  degraded?: boolean
}

const CROWDING: Record<string, { text: string; cls: string }> = {
  high: { text: '拥挤', cls: 'text-red-400' },
  mid: { text: '中性', cls: 'text-amber-500' },
  low: { text: '清淡', cls: 'text-emerald-400' },
}

const ALERT: Record<string, { text: string; cls: string }> = {
  squeeze_candidate: { text: '⚠️ 挤空候选', cls: 'text-amber-400 border-amber-500/30 bg-amber-500/10' },
  collapse_warning: { text: '一致性异常', cls: 'text-slate-300 border-border/40 bg-secondary/10' },
}

function pct(v?: number | null): string {
  return v == null || Number.isNaN(v) ? '--' : `${v.toFixed(2)}%`
}

export function ShortSellingPanel({
  ticker = 'HK.00700',
  mode = 'daily',
}: {
  ticker?: string
  /** daily=个股级 T-1 卖空量；rank=全市场卖空榜（与 ticker 无关） */
  mode?: 'daily' | 'rank'
}) {
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

  if (loading) return <div className="p-6 text-sm text-slate-400">加载卖空数据 ({ticker})…</div>

  if (error)
    return (
      <div className="p-6 text-sm text-amber-400/90">
        卖空数据暂不可用：{error}
        <span className="ml-1 text-[10px] text-amber-400/60">· 数据源恢复后将自动重试</span>
      </div>
    )

  // T-1 红线：当日盘后无结算数据时如实展示空态，禁止把缺失渲染成 0
  const derived = data?.derived
  if (!data || data.futu?.status === 'no_data' || !derived)
    return (
      <EmptyState
        title="当日卖空数据尚未结算"
        description="港股/美股卖空量为 T-1 结算数据，盘后当日通常尚不可得。下一交易日结算后将自动展示。"
      />
    )

  const alert = derived.alert_signal
  const alertStyle = alert?.type ? ALERT[alert.type] : undefined
  const crowding = derived.crowding_level ? CROWDING[derived.crowding_level] : undefined
  const cards = [
    { label: '个股卖空成交占比', v: pct(derived.short_sale_ratio) },
    { label: '市场卖空占比 (HKEX)', v: pct(data.regulatory?.short_volume_ratio) },
    { label: '拥挤度', v: crowding?.text ?? '--', cls: crowding?.cls },
    { label: '数据日期', v: derived.as_of || '--' },
  ]

  return (
    <div className="glass-card rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">个股卖空</span>
        <span className="font-mono text-xs text-foreground/80">{data.ticker || ticker}</span>
        {data.degraded && <span className="text-[10px] font-mono text-amber-500">DEGRADED</span>}
        {alertStyle && (
          <span className={'ml-auto text-[10px] font-mono px-2 py-0.5 rounded border ' + alertStyle.cls}>
            {alertStyle.text}
          </span>
        )}
      </div>

      <div className="grid grid-cols-4 gap-2 p-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-border/40 bg-card/40 px-3 py-2">
            <div className="text-[10px] text-slate-500">{c.label}</div>
            <div className={'text-sm font-semibold font-mono ' + (c.cls || 'text-foreground/90')}>{c.v}</div>
          </div>
        ))}
      </div>

      <div className="px-3 py-2 border-t border-border/20 text-[9px] text-muted-foreground flex items-center justify-center gap-2 bg-secondary/10">
        <span>
          数据源：{data.source || 'Futu 卖空 + HKEX 交叉验证'} ·{' '}
          {data.regulatory?.note || '经 HKEX 市场级卖空占比校准'} · T-1 {derived.as_of || '—'}
        </span>
        <span className="px-1.5 py-px rounded border border-sky-500/30 bg-sky-500/10 text-sky-500 font-mono">日更</span>
      </div>
    </div>
  )
}
